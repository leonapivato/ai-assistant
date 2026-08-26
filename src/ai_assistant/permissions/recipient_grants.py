"""A durable :class:`~ai_assistant.core.protocols.RecipientGrantStore` on SQLite (ADR-0193 §1).

The store ADR-0021 §6 names — "durable, per-user policy state with its own
data-rights obligations — **a store, not a field**" — arriving for the recipient
axis. It holds what the user made standing: for one declaration, against one
connected account, over one canonical destination set, until one instant.

**One object, three faces.** It satisfies
:class:`~ai_assistant.core.protocols.RecipientGrantStore` and therefore
:class:`~ai_assistant.core.protocols.RecipientGrants` and
:class:`~ai_assistant.core.protocols.RecipientGrantResolution` too, so a
composition root passes *this* object to the hub's grant operations, to the
``ActionPolicy`` as the query face, and to the ``AuditTrail`` as the resolution
face. Structural typing is what makes that sound: what a policy cannot do is
**name** ``record``, and what a trail cannot do is name ``record`` or
``covering``, because ``mypy --strict`` runs over ``src`` and ``tests`` and those
attributes are not on the annotated types (ADR-0193 §1, on ADR-0097 §3's split).

**The record is the audit record**, as it is for the source-grant store: there is
no separate log of grants because the only writes are appends, a revocation *is*
an append, and nothing may be edited or selectively removed — so this store
cannot hold a history that differs from what happened. ADR-0021 §4's argument is
taken over whole: the user may burn the book, and nobody may tear out a page.

**Where it departs from :mod:`ai_assistant.permissions.grants`, deliberately.**
That store admits at most one live grant per source; this one admits **overlapping
grants over different destination sets**, because a grant over ``{Alice}`` and one
over ``{Alice, Bob}`` are two things a user may reasonably have said. What it
refuses instead is a second grant that **is** the first — same declaration, same
account, same destination set — because revoking one would leave the other
standing and the user would have revoked nothing. That refusal is stated over
**outstanding** rather than live, so the write path reads no clock, and the
liveness the read path evaluates is stated over one clock reading per query
(ADR-0193 §1, §9).

**Two clock disciplines, and they are not interchangeable.** ``covering`` and
``standing`` evaluate liveness, so they read the clock — **once** per call, and
every record they consider is measured against that one instant, because a query
reading an advancing clock per row could return one of two grants sharing an
``expires_at`` and omit the other: a set true at no real instant. ``record``,
``outstanding``, ``recent``, ``export`` and ``clear`` read **no** clock at all.

Local-first (ADR-0002), and **locally only**: ADR-0193 §9 rules these records
Tier 1 and applies ADR-0004 §2's residency clause to them, so nothing here may
reach a remote service. The database file is created owner-only (ADR-0004 §4,
ADR-0084 §9), before the first statement, so a rollback journal SQLite opens for
it inherits that mode rather than the process umask.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import InvalidRecipientGrantError, RecipientGrantError
from ai_assistant.core.types import RecipientGrant
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

    from ai_assistant.core.types import ActionRequest

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too (see
#: :mod:`ai_assistant.permissions.grants`, whose note this repeats because the
#: family shares this method by copy today — #506).
_SIDECARS = ("-journal", "-wal", "-shm")

#: The largest value SQLite will bind as an integer parameter.
_MAX_SQLITE_INT = 2**63 - 1


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The **seventh** copy of this helper rather than an import from a sibling,
    which is the tree's established position rather than a fresh choice: each
    SQLite store carries its own, and #506 and #563 already track consolidating
    the family. A private import from :mod:`ai_assistant.permissions.grants`
    would make one store's helper silently govern another's, and would leave the
    other five out of the arrangement anyway.

    The store serialises one ``sqlite3`` connection behind an
    :class:`asyncio.Lock` and runs the SQL in a worker thread. A thread cannot be
    interrupted, so if the awaiting coroutine were simply cancelled the enclosing
    ``async with self._lock`` would unwind and release the lock **while the worker
    was still using the connection** — letting a second caller use the same
    connection concurrently, which SQLite refuses. The worker records its own
    outcome and sets a :class:`threading.Event` when it physically returns; this
    coroutine waits on *that* signal, so the lock is held for the whole life of
    the worker even under a blanket task cancellation. An absorbed cancellation
    takes precedence over the worker's result and is re-raised once the thread has
    finished: the caller's task still cancels; what is prevented is connection
    reuse.

    Every failure the worker sees is relayed, ``BaseException`` included, and the
    completion wait is submitted **at most once** (#697): a copy that submits a
    fresh one per cancellation leaves every earlier one parked in ``Event.wait``,
    which turns one stalled store operation into a process that cannot run any
    thread work at all.
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
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            # The signal is one job, reused: see the docstring.
            cancellation = exc
            if waiting is None:
                waiting = loop.run_in_executor(None, done.wait)
            pending = waiting
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


#: One shape only, so far. The marker is written by :meth:`SqliteRecipientGrantStore.
#: _setup` on a database this code creates, which is the seam ADR-0049 §1 describes.
#:
#: **There is no ``_migrate`` here and that is not an omission.** Version 1 is the
#: first shape this store has ever had, so there is no population of pre-marker
#: files in the wild to bring forward: an unlabelled database is one this code is
#: creating now, and it is stamped rather than migrated.
_SCHEMA_VERSION = 1

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``recipient_grants`` table is created or
#: read — creating a table is a write, and the refusal precedes any write.
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: The epoch the sort keys count from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The columns beside the ``data`` blob exist only so SQLite can order, constrain
# and narrow; the blob is the record. ``revokes`` is what the outstanding
# anti-join reads, the two instant columns are what the liveness predicate reads,
# and ``decided_at_us`` doubles as the ordering key ``recent`` and ``export``
# share.
#
# **The subject is deliberately *not* projected into a column.** The
# duplicate-subject refusal compares a whole ``ToolDefinition``, a whole
# ``BoundAccount`` and a whole destination tuple by value (ADR-0193 §1), and a
# shadow column holding a serialised form of those would be a second copy of the
# value free to disagree with the one every read answers from — the failure
# ``SqliteSourceGrantStore._standing_sync`` names when it declines to do its own
# duplicate check in SQL. The check runs over decoded outstanding records
# instead, which the ceiling already bounds.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS recipient_grants("
    "id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
    "expires_at_us INTEGER NOT NULL, revokes TEXT, data TEXT NOT NULL)"
)

_INDEXES = (
    # A *unique* index, so the one-revocation-per-grant rule survives even a bug
    # in `_check_revocation`. SQLite treats NULLs as distinct, so it constrains
    # revoking rows only and leaves granting records unaffected. The mechanical
    # sibling of `grants_revokes` on the source-grant store.
    "CREATE UNIQUE INDEX IF NOT EXISTS recipient_grants_revokes ON recipient_grants(revokes)",
    "CREATE INDEX IF NOT EXISTS recipient_grants_order "
    "ON recipient_grants(decided_at_us DESC, id ASC)",
    # The outstanding anti-join narrows on `revokes` first. There is no index
    # expressing "live", because liveness is *derived* — from the `revokes`
    # relation and the clock — rather than stored, and an index that claimed to
    # store it would be a second answer free to disagree with the first.
    "CREATE INDEX IF NOT EXISTS recipient_grants_outstanding ON recipient_grants(revokes)",
)

_ORDERED = "SELECT data FROM recipient_grants ORDER BY decided_at_us DESC, id ASC"

#: Every **outstanding** granting record: rows whose ``revokes`` is NULL that no
#: recorded revocation names. Liveness's clock-free half, and the whole of what
#: ``record`` and ``outstanding`` decide over — no instant appears in this
#: statement at all, which is what keeps the write path free of a clock and lets
#: an expired-but-unrevoked grant still be revoked (ADR-0193 §1, §9).
_OUTSTANDING = (
    "SELECT data FROM recipient_grants AS g "
    "WHERE g.revokes IS NULL "
    "AND NOT EXISTS (SELECT 1 FROM recipient_grants AS r WHERE r.revokes = g.id) "
    "ORDER BY g.decided_at_us DESC, g.id ASC"
)

#: :data:`_OUTSTANDING` narrowed to one id — what :meth:`SqliteRecipientGrantStore.
#: outstanding` answers from. The **same** anti-join rather than a second spelling
#: of "is this grant unrevoked": two spellings are two answers free to drift apart,
#: and the one that drifted would still pass its own half of the suite.
_OUTSTANDING_BY_ID = (
    "SELECT data FROM recipient_grants AS g "
    "WHERE g.revokes IS NULL AND g.id = ? "
    "AND NOT EXISTS (SELECT 1 FROM recipient_grants AS r WHERE r.revokes = g.id)"
)

#: Every **live** grant as of one instant: :data:`_OUTSTANDING` with the interval
#: predicate added. Closed below and open above — ``decided_at <= now <
#: expires_at`` — which is ADR-0193 §1's interval exactly, and bounded below as
#: well as above because a future-dated grant the store called live is one the
#: policy would author an ``ALLOW`` on and ``AuditTrail.record`` would then refuse.
#:
#: The instant is **bound twice from one reading** rather than read per row, which
#: is §9's single-read clause held in SQL rather than by discipline.
_LIVE = (
    "SELECT data FROM recipient_grants AS g "
    "WHERE g.revokes IS NULL "
    "AND g.decided_at_us <= ? AND g.expires_at_us > ? "
    "AND NOT EXISTS (SELECT 1 FROM recipient_grants AS r WHERE r.revokes = g.id) "
    "ORDER BY g.decided_at_us DESC, g.id ASC"
)


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather than
    from ``timestamp()``. Ordering is part of ``recent``'s contract and the
    interval comparison is part of liveness, and a float epoch second carrying
    microsecond precision needs sixteen significant digits at present-day values —
    right at the edge of a double, so two records a microsecond apart could compare
    equal or invert. The subtraction below is exact.

    Both instants a :class:`~ai_assistant.core.types.RecipientGrant` carries are
    ``UtcInstant``, already normalised to UTC by ``core``, so this is a key over
    *instants* — which is what makes the DST repeated hour sort correctly rather
    than by wall clock.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _utc_now() -> datetime:
    """Read the wall clock as an aware UTC instant."""
    return datetime.now(UTC)


class SqliteRecipientGrantStore:
    """A persistent, append-only, validating ``RecipientGrantStore``.

    Structurally implements all three faces of ADR-0193 §1's seam, which is why a
    composition root builds **one** of these and hands it to three consumers under
    three annotations.

    **Records are stored as their JSON dump and rebuilt on every read**, which is
    how the "detached, validated snapshot" obligation is obtained here without a
    copy step to forget: serialising rebuilds every reachable value, so there is no
    object graph shared with the caller in either direction, and the store cannot
    hand back a caller-supplied subclass.

    **The write-side snapshot is taken from the instance's own field state**, not
    from ``model_dump()`` — see :func:`_revalidated`. That is
    ``SqliteSourceGrantStore``'s discipline rather than
    ``SqliteAuditTrail._revalidated``'s, and it matters more here than there: a
    subclass whose dump reports a *wider* destination tuple than the instance
    holds would have the store append an authorisation over recipients the user
    never named.

    **Atomicity** comes from an :class:`asyncio.Lock` around the whole of
    :meth:`record`, with the duplicate-id check, the duplicate-subject refusal,
    the **ceiling count**, the revocation invariants and the insert running in one
    worker call inside a single ``BEGIN IMMEDIATE`` transaction. The ceiling is the
    one that fails the way a duplicate-id check does not: two writers of
    *different* subjects at one below it both see room, both append, and the store
    ends one over — a race the duplicate-subject refusal cannot catch, because the
    two subjects differ (ADR-0193 §1).

    **No busy timeout is set here, and that is the family's posture rather than
    this store's choice** (#564): no SQLite store in this tree sets one
    deliberately, so under cross-process contention ``BEGIN IMMEDIATE`` surfaces
    ``SQLITE_BUSY`` after the driver's default.
    """

    def __init__(
        self,
        *,
        path: Path | str,
        max_outstanding: int,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Open (or create) the recipient-grant store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
                **Required, with no default.** Durability is the whole reason this
                implementation exists — a grant the user made must still be on file
                after a restart — so a default would let the ordinary construction
                produce a store that forgets every standing authorisation on
                restart. An ephemeral store is available and has to be asked for.
                It lives under ``Settings.data_dir`` in a real deployment, which is
                the composition root's choice rather than this class's.
            max_outstanding: ADR-0193 §1's ceiling on **outstanding granting
                records**, which a deployment reads from
                ``Settings.recipient_grant_max_outstanding``. **Required, with no
                default**, so a composition that omits the ceiling does not
                type-check — the shape ADR-0097 §5 uses for the gate itself, taken
                here because the default belongs to ``Settings`` and a second one
                in this constructor would be a figure a deployment could not see it
                was getting. Zero is meaningful and admitted: it declines the
                *next* grant and retracts none.
            now: The clock :meth:`covering` and :meth:`standing` evaluate liveness
                against, wrapped by ``checked_clock`` (ADR-0026). Injected so a
                suite pins the interval boundary rather than racing it. **No caller
                supplies an instant**: a store that enforced liveness against a
                number the party being authorised chose would enforce nothing.

        Raises:
            RecipientGrantError: If the database cannot be opened or initialised.
            ValueError: If ``max_outstanding`` is negative. A negative ceiling
                names no bound and would refuse every granting write for a reason
                no message explains, which is why zero is admitted and this is not.
        """
        if max_outstanding < 0:
            msg = (
                f"max_outstanding must not be negative, got {max_outstanding}; zero is "
                f"meaningful (it declines route (b)) and a negative names no ceiling"
            )
            raise ValueError(msg)
        self._path = path if path == ":memory:" else str(Path(path))
        self._max_outstanding = max_outstanding
        self._clock = checked_clock(now, owner="SqliteRecipientGrantStore")
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            # ``ValueError`` is named because a path carrying an embedded NUL
            # raises it out of the driver rather than a ``sqlite3.Error``, and a
            # bad path is this layer's fault to report rather than a raw builtin
            # escaping past its error boundary (#238's hole, closed here rather
            # than reproduced).
            msg = f"failed to open the recipient-grant store at {self._path!r}: {exc}"
            raise RecipientGrantError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built: SQLite copies the database file's mode onto every rollback
            # journal it creates for it, so a journal opened while the file still
            # carried the process umask is world-readable too — and an interrupted
            # write leaves it on disk holding Tier 1 pages (#489).
            self._restrict_permissions()
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                labelled = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                for statement in _INDEXES:
                    conn.execute(statement)
                if not labelled:
                    # Stamped *after* the create above, and inside the same
                    # transaction, so a failure rolls the marker — and the `meta`
                    # table itself — back with it rather than leaving a database
                    # falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except RecipientGrantError:
            # A refused schema version is already this layer's error; it still
            # leaves a connection to close before it propagates.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the recipient-grant store at {self._path!r}: {exc}"
            raise RecipientGrantError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault, so absence is
        tolerated one name at a time; nothing else is. A *symlink* under a
        sidecar's name is skipped rather than followed, because ``chmod`` follows
        links and restricting one would silently narrow a file this store has no
        business modifying. A no-op in memory.

        **Duplicated from the six other SQLite stores on purpose** (#506): the
        family shares this method by copy today, and consolidating it is that
        issue's, not this lane's.
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
        ``recipient_grants`` table is created or read.

        **An unlabelled database is stamped rather than migrated**: this store
        ships *with* its marker, so version 1 is the only shape it has ever written
        and an unlabelled file is one this open is creating. There is nothing to
        migrate from and no ``_migrate`` to run.

        Returns:
            Whether the database already carries a ``schema_version``.

        Raises:
            RecipientGrantError: If the stored version is not one this code
                understands, is not an integer at all, or is not a single
                unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return False
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code
            # created — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing
            # `meta` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers, and reading the first row would let an
            # unsupported version through on the strength of a sibling that agrees.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the recipient-grant store at {self._path!r} holds {len(rows)} "
                f"schema_version rows ({', '.join(repr(value) for value in found)}); "
                f"the store is corrupt"
            )
            raise RecipientGrantError(msg)
        raw = rows[0][0]
        msg = (
            f"the recipient-grant store at {self._path!r} holds a non-numeric "
            f"schema_version {raw!r}"
        )
        # The marker this code writes is always TEXT, but a hand-built `meta` may
        # declare no type, in which case SQLite hands back whatever was stored.
        # `int(float("inf"))` raises `OverflowError`, which is neither `ValueError`
        # nor an `AssistantError` and would leave this layer's boundary through a
        # hole. `bool` is an `int` in Python, so it is named rather than left to
        # read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise RecipientGrantError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            raise RecipientGrantError(msg) from exc
        if stored != _SCHEMA_VERSION:
            msg = (
                f"the recipient-grant store at {self._path!r} has schema_version={stored}, "
                f"but this code supports only version {_SCHEMA_VERSION}; refusing to open "
                f"it rather than read it blindly"
            )
            raise RecipientGrantError(msg)
        return True

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first write,
        which is what puts :meth:`_record_sync`'s *reads* under it: the free-id
        check, the duplicate-subject refusal, the **ceiling count** and the
        revocation invariants all decide whether the append may happen, so a
        deferred begin would let a second process observe the same free id, the
        same absent subject or the same room under the ceiling between them and the
        append. The ``asyncio`` lock closes that within one process; this closes it
        against the file.

        Raises:
            RecipientGrantError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=RecipientGrantError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, grant: RecipientGrant) -> str:
        """Append ``grant`` and return its id.

        Write-once and atomic over the duplicate-id check, the duplicate-subject
        refusal, the ceiling count, the revocation invariants and the append
        (ADR-0193 §1).

        Raises:
            InvalidRecipientGrantError: If the record does not satisfy its own
                model, if its id is already recorded, if a granting record
                duplicates an outstanding grant's declaration, account and
                destination set, if a granting record would take the outstanding
                count above the configured ceiling, or if it revokes and fails any
                invariant. Pydantic's ``ValidationError`` is deliberately not
                allowed to escape: ``CONTRIBUTING`` has this layer raise only from
                the ``AssistantError`` hierarchy.
            RecipientGrantError: If the database refuses the write.
        """
        snapshot = _revalidated(grant)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: RecipientGrant) -> None:
        """Validate against what is stored and insert, as one transaction."""
        with self._transaction(f"record recipient grant {snapshot.id!r}") as conn:
            if conn.execute(
                "SELECT 1 FROM recipient_grants WHERE id = ?", (snapshot.id,)
            ).fetchone():
                msg = (
                    f"recipient grant {snapshot.id!r} is already recorded; the store is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise InvalidRecipientGrantError(msg)
            if snapshot.revokes is None:
                self._check_granting(conn, snapshot)
            else:
                self._check_revocation(conn, snapshot)
            conn.execute(
                "INSERT INTO recipient_grants("
                "id, decided_at_us, expires_at_us, revokes, data"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    _sort_key(snapshot.decided_at),
                    _sort_key(snapshot.expires_at),
                    snapshot.revokes,
                    snapshot.model_dump_json(),
                ),
            )

    def _check_granting(self, conn: sqlite3.Connection, grant: RecipientGrant) -> None:
        """Refuse a duplicate subject or a breach of the ceiling (ADR-0193 §1).

        **One read of the outstanding set answers both**, which is the point of
        doing it here rather than in two statements: the ceiling counts exactly the
        records the duplicate refusal compares against, so a second query would be
        a second answer to the same question, free to be taken at a different
        moment even inside one transaction.

        The comparison is over whole values — the ``ToolDefinition``, the
        ``BoundAccount`` and the destination tuple — decoded from the ``data``
        blob every other read answers from. A shadow column holding a serialised
        subject would be a second copy free to disagree with it.

        Both refusals are stated over **outstanding** rather than live, so this
        path reads no clock: an expired grant occupies its slot and blocks an
        identical new one until it is revoked, which is the cost of a write path
        that cannot be moved by a clock correction in either direction.

        Raises:
            InvalidRecipientGrantError: If an outstanding grant has the same
                declaration, account and destination set, or if the store already
                holds the configured maximum of outstanding granting records.
        """
        outstanding = [_decode(row) for row in self._read(conn, _OUTSTANDING, ())]
        standing = next(
            (
                held
                for held in outstanding
                if held.tool == grant.tool
                and held.account == grant.account
                and held.destinations == grant.destinations
            ),
            None,
        )
        if standing is not None:
            msg = (
                f"recipient grant {standing.id!r} already stands over this declaration, "
                f"account and destination set; a second is one the user could not revoke, "
                f"because revoking either would leave the other standing (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if len(outstanding) >= self._max_outstanding:
            msg = (
                f"the recipient-grant store holds {len(outstanding)} outstanding grants and "
                f"admits {self._max_outstanding}, so grant {grant.id!r} is refused; nothing "
                f"is evicted, narrowed or expired to make room, and the recourse is to "
                f"revoke a grant you hold (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)

    def _check_revocation(self, conn: sqlite3.Connection, revocation: RecipientGrant) -> None:
        """Enforce ADR-0193 §1's invariant on a revoking record.

        Six refusals, and **no seventh on the timestamp**. That absence is the
        decision, not an oversight: ``decided_at`` is caller-supplied and this
        store reads no clock on the write path, so refusing a revocation that
        predates its grant would make a grant permanently unrevokable across a
        backwards clock correction — and revocation is the recourse the ceiling
        clause depends on, so trapping it would trap a user above the ceiling with
        no way down.

        **A revoking record is never refused for the ceiling either**, which is why
        this path never reaches :meth:`_check_granting`.

        Raises:
            InvalidRecipientGrantError: If the named grant is absent, is itself a
                revoking record, is already revoked, or if any transcribed field
                differs.
        """
        row = conn.execute(
            "SELECT data FROM recipient_grants WHERE id = ?", (str(revocation.revokes),)
        ).fetchone()
        if row is None:
            msg = (
                f"recipient grant {revocation.revokes!r} is not recorded, so nothing "
                f"revokes it (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        target = _decode(str(row[0]))
        if target.revokes is not None:
            msg = (
                f"record {target.id!r} is itself a revocation; only a granting record "
                f"can be revoked (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if conn.execute(
            "SELECT 1 FROM recipient_grants WHERE revokes = ?", (revocation.revokes,)
        ).fetchone():
            msg = (
                f"recipient grant {target.id!r} is already revoked; a grant revoked twice "
                f"is a history that says the user withdrew one thing twice (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.tool != revocation.tool:
            msg = (
                f"revocation {revocation.id!r} transcribes a different declaration from the "
                f"one grant {target.id!r} was established about; a revoking record "
                f"transcribes what it withdraws (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.account != revocation.account:
            msg = (
                f"revocation {revocation.id!r} names a different account from the one grant "
                f"{target.id!r} was established against (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.destinations != revocation.destinations:
            msg = (
                f"revocation {revocation.id!r} transcribes a different destination set from "
                f"the one grant {target.id!r} names; there is no partial revocation "
                f"(ADR-0193 §1, §9)"
            )
            raise InvalidRecipientGrantError(msg)
        if target.expires_at != revocation.expires_at:
            msg = (
                f"revocation {revocation.id!r} transcribes a different expiry from grant "
                f"{target.id!r}'s (ADR-0193 §1)"
            )
            raise InvalidRecipientGrantError(msg)

    # --- the read path ----------------------------------------------------

    async def covering(self, request: ActionRequest) -> RecipientGrant | None:
        """The live grant covering ``request``'s recipients, or ``None``.

        Four of ADR-0193 §3's five comparisons; the fifth,
        ``planned_with_external_content``, is the policy's and is deliberately not
        read here. A request carrying no ``egress_binding`` is answered ``None``
        **without touching the database**, which is the fail-cheap direction and
        keeps a non-egress ruling free of a store read.

        **Containment is membership and nothing looser** — no case folding, no
        domain matching, no treating an account member as covering a recipient
        member or the reverse, no re-canonicalising either side.

        **Precedence is total**: the greatest ``decided_at`` wins, ties broken by
        the least ``id``. That order is :data:`_LIVE`'s own ``ORDER BY``, so the
        **first** matching row is the winner and no second sort is needed — which
        is why the comparison loop below stops at the first match rather than
        collecting and ranking.

        Raises:
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        binding = request.egress_binding
        if binding is None:
            return None
        wanted = binding.canonical_destination_set
        async with self._lock:
            rows = await _run_to_completion(self._live_sync)
        for row in rows:
            grant = _decode(row)
            if (
                grant.tool == request.tool
                and grant.account == binding.account
                and all(member in grant.destinations for member in wanted)
            ):
                return grant
        return None

    async def standing(self) -> list[RecipientGrant]:
        """Return every live grant in the store (ADR-0193 §1).

        :meth:`covering`'s query with its coverage comparisons dropped, so the two
        cannot compute liveness differently: an enumeration free to decide it its
        own way is free to disagree with the gate, and the one that disagreed would
        still pass its own suite.

        **Complete or nothing**, whatever the ceiling now says. A store holding
        records a newly lowered ``max_outstanding`` would not admit is a legal
        state — every record in it was admitted under the ceiling in force at the
        time — and a query that hid them to make the current setting look satisfied
        would be lying to the user about their own standing policy.

        Raises:
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._live_sync)
        return [_decode(row) for row in rows]

    def _live_sync(self) -> Sequence[str]:
        """Read every live row against **one** clock reading (ADR-0193 §9).

        The reading is taken once, here, and bound to both ends of the interval
        predicate, so every record the query considers is measured against the same
        instant. A per-row reading could return one of two grants sharing an
        ``expires_at`` and omit the other — a set true at no real instant — and it
        is the shared helper rather than two copies precisely so ``covering`` and
        ``standing`` cannot acquire different clock disciplines.
        """
        reading = _sort_key(self._clock())
        return self._read(self._conn, _LIVE, (reading, reading))

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:
        """The **granting** record with ``grant_id``, if unrevoked, else ``None``.

        Reads **no clock**: an expired but unrevoked grant is returned rather than
        withheld, because expiry is not this member's question and
        ``AuditTrail.record`` decides it against the decision's own ``decided_at``
        (ADR-0193 §1, §6). A revoking record's own id answers ``None``, as an
        absent one does.

        Raises:
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._outstanding_sync, grant_id)
        return _decode(rows[0]) if rows else None

    def _outstanding_sync(self, grant_id: str) -> Sequence[str]:
        """Read the outstanding granting row with ``grant_id``, if there is one."""
        return self._read(self._conn, _OUTSTANDING_BY_ID, (grant_id,))

    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]:
        """Return up to ``limit`` records, newest first, ties broken by id ascending.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021
        §4): the row count here grows with grant churn rather than with the number
        of recipients. Revoked grants and revoking records alike are returned, and
        no liveness is evaluated, so no clock is read.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Refused rather than
                clamped or passed through: SQLite reads ``LIMIT -1`` as *no limit
                at all*, so the one call offering a bounded read of a Tier 1 store
                would become the unbounded read it exists to avoid.
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        # Clamped *upward* only. A Python int has no width, and binding one wider
        # than SQLite's signed 64-bit parameter raises `OverflowError` — neither
        # `ValueError` nor `RecipientGrantError`, so it would leave this layer's
        # error boundary through a hole. A bound above any possible row count means
        # "all of them", which is what the query then returns. This is not the
        # `limit=-1` case, where clamping would serve something nobody asked for.
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, min(limit, _MAX_SQLITE_INT))
        return [_decode(row) for row in rows]

    async def export(self) -> list[RecipientGrant]:
        """Return **every** record, in the same order as :meth:`recent`.

        ADR-0004 §6's export right. A revoked grant is **still here**, and so is
        the revoking record that revoked it and every expired grant: what this
        store is *for* is saying, completely and in order, what the user made
        standing and what they withdrew, and a portable snapshot that omits records
        is not one (ADR-0193 §1).

        Raises:
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, None)
        return [_decode(row) for row in rows]

    def _ordered_sync(self, limit: int | None) -> Sequence[str]:
        """Read records newest-first, optionally bounded.

        Two static statements rather than one interpolated ``LIMIT``: the bound is
        the whole point of ``recent``, and a query assembled from a variable is how
        it stops being one.
        """
        statement = _ORDERED if limit is None else f"{_ORDERED} LIMIT ?"
        parameters: tuple[object, ...] = () if limit is None else (limit,)
        return self._read(self._conn, statement, parameters)

    @staticmethod
    def _read(
        conn: sqlite3.Connection, statement: str, parameters: tuple[object, ...]
    ) -> Sequence[str]:
        """Run one ``SELECT data`` statement, translating a backend failure.

        One helper rather than a ``try`` per read, so no read acquires its own
        error boundary and every one of them fails the same way — which is what a
        consumer's fail-closed branch is written against.

        Raises:
            RecipientGrantError: If the backend fails.
        """
        try:
            rows = conn.execute(statement, parameters).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to read the recipient-grant store: {exc}"
            raise RecipientGrantError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every record, returning the number removed.

        Wholesale by design (ADR-0193 §9): the user may burn the book, and nobody
        may tear out a page. There is no ``delete(id)``, and its reason here is
        narrower than the trail's and stated on its own — an ``authorised_by`` in
        the trail points into this store, so deleting the record it points at would
        make a recorded ``ALLOW`` unexplainable while leaving it looking complete.

        The count is of **every** record removed — live, expired, revoked and
        revoking alike — rather than of the live ones.

        Raises:
            RecipientGrantError: If the store cannot be cleared.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        """Delete everything in one statement, counting what the delete removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it. A separate count is read before SQLite opens the
        write transaction, so a second store on the same file could append between
        the two and be erased without being counted — and each instance has its own
        ``asyncio.Lock``, which arbitrates nothing across them.

        Only ``recipient_grants`` is emptied: the ``meta`` schema marker describes
        the file's shape rather than the user's history, so burning the book leaves
        a database this code can still open. Nothing else is retained — no id, no
        tombstone, no derived value — so an id held before this may be recorded
        again afterwards (ADR-0193 §1).
        """
        with self._transaction("clear the recipient-grant store") as conn:
            removed = conn.execute("DELETE FROM recipient_grants").rowcount
        return int(removed)

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _revalidated(grant: RecipientGrant) -> RecipientGrant:
    """Rebuild ``grant`` as a validated :class:`RecipientGrant`.

    ADR-0193 §1 asks for a *validated* snapshot, not merely a detached one. A copy
    alone detaches without checking, so a record corrupted past its frozen model's
    guard would be stored and make every later read incoherent — a naive
    ``decided_at`` makes ``recent`` raise on comparing it against the aware values
    beside it, and a destination tuple written back out of canonical order would
    make the duplicate refusal, the trail's subject match and the digest three
    comparisons over a spelling the record's own validator refuses.

    Rebuilt as a ``RecipientGrant`` specifically, not as ``type(grant)``: a
    caller's subclass could carry extra fields, and ``extra="forbid"`` refuses them
    here rather than letting them vanish at serialisation and make the stored
    record differ from the one that reloads.

    **And rebuilt from the instance's field state rather than from
    ``model_dump()``**, which is ``SqliteSourceGrantStore._revalidated``'s
    discipline and matters more on this record than on that one. ``model_dump`` is
    an ordinary overridable method, so a subclass can return a mapping that does
    not describe itself — a one-recipient instance whose dump names two — and the
    store would then append **an authorisation over a recipient the user never
    named**. That is not the caller-falsifies-its-own-record case ADR-0018 §3 puts
    outside a store's reach: the object presented is a valid narrow grant and the
    record kept is a wider one, which is precisely what "stores a detached,
    validated snapshot" denies. ``__dict__`` is where pydantic keeps validated
    field state, and it is read through ``object.__getattribute__`` so that the
    read itself dispatches no user code either.

    **The refusal names the id out of the same mapping**, never through
    ``grant.id``: a record whose ``__dict__`` is missing a field has no ``id``
    attribute at all, so composing the message from one would raise a bare
    ``AttributeError`` out of the handler and replace the refusal this layer owes
    with a builtin escaping its error boundary.

    Raises:
        InvalidRecipientGrantError: If the record does not satisfy its own model.
            The subclass rather than the ``RecipientGrantError`` base: here the
            base is the *store fault* and only the subclass says "your record was
            refused", which is the distinction a consumer's fail-closed branch
            keeps alive.
    """
    fields = dict(object.__getattribute__(grant, "__dict__"))
    try:
        return RecipientGrant.model_validate(fields)
    except ValidationError as exc:
        msg = f"recipient grant {fields.get('id')!r} is not a valid record: {exc}"
        raise InvalidRecipientGrantError(msg) from exc


def _decode(data: str) -> RecipientGrant:
    """Rebuild a stored grant from its JSON.

    Raises:
        RecipientGrantError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to
            hand on. The **base** class here, not
            ``InvalidRecipientGrantError``: nothing the caller handed in was
            refused, the store itself is unreadable, and a consumer's fail-closed
            branch is exactly the right response.
    """
    try:
        return RecipientGrant.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the recipient-grant store holds a record that no longer validates: {exc}"
        raise RecipientGrantError(msg) from exc


__all__ = ["SqliteRecipientGrantStore"]
