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
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from pydantic import ValidationError

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import (
    DuplicateRecipientGrantError,
    InvalidRecipientGrantError,
    RecipientGrantCeilingError,
    RecipientGrantError,
)
from ai_assistant.core.types import (
    BoundAccount,
    CanonicalDestination,
    RecipientGrant,
    ToolDefinition,
    describe_untrusted,
)
from ai_assistant.permissions._detachment import field_state
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

# **The blob is the record, and every column that decides anything is derived
# from it** (ADR-0193 §1). ``id`` and ``revokes`` are ``GENERATED ALWAYS`` from the
# JSON, which is ``SqliteAuditTrail``'s shape for the ``invocations`` table one
# module over and is taken for its reason: a stored column that merely *agreed*
# with the blob when it was written is a second copy of a value, and a store whose
# anti-join reads the copy while its answer decodes the blob can be made to say
# that a revoked grant is outstanding. Derived, they cannot disagree.
#
# **``decided_at_us`` is a plain column and orders nothing that authorises.** It
# exists because ``recent`` and ``export`` sort by decision time and SQLite cannot
# sort an ISO-8601 instant correctly — ``"…:00.000001Z"`` sorts *before*
# ``"…:00Z"`` by code point, so a generated column over ``json_extract`` would put
# a later record first. Liveness is therefore **not** decided in SQL at all: the
# interval is evaluated over the decoded record, against one clock reading, so both
# instants that decide coverage come from the blob. What is left on this column is
# an ordering, and the append-only trigger below is what holds it.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS recipient_grants("
    "decided_at_us INTEGER NOT NULL, data TEXT NOT NULL, "
    "id TEXT GENERATED ALWAYS AS (json_extract(data, '$.id')) VIRTUAL, "
    "revokes TEXT GENERATED ALWAYS AS (json_extract(data, '$.revokes')) VIRTUAL)"
)

#: Keyed by name, because :data:`_OBJECTS` holds each one to its own definition and
#: a positional tuple would make that mapping a place to get wrong.
_INDEXES = {
    # The primary key `id` cannot be, because SQLite refuses a generated column in
    # one. Same constraint, same enforcement, and the derivation is kept.
    "recipient_grants_id": (
        "CREATE UNIQUE INDEX IF NOT EXISTS recipient_grants_id ON recipient_grants(id)"
    ),
    # A *unique* index, so one-revocation-per-grant survives even a bug in
    # `_check_revocation`. SQLite treats NULLs as distinct, so it constrains
    # revoking rows only and leaves granting records unaffected. The mechanical
    # sibling of `grants_revokes` on the source-grant store.
    "recipient_grants_revokes": (
        "CREATE UNIQUE INDEX IF NOT EXISTS recipient_grants_revokes ON recipient_grants(revokes)"
    ),
    "recipient_grants_order": (
        "CREATE INDEX IF NOT EXISTS recipient_grants_order "
        "ON recipient_grants(decided_at_us DESC, id ASC)"
    ),
}

#: **The table is append-only, said to SQLite rather than only to the reader.**
#: ADR-0193 §1's guarantee is that nothing recorded is edited, narrowed, re-scoped
#: or extended in place, and this store never issues an ``UPDATE`` — ``clear()``
#: deletes, and every other write appends. Stating it as a trigger closes the one
#: column a comparison cannot reach: ``decided_at_us`` orders a **bounded**
#: listing, and a bounded listing applies its ``LIMIT`` in the same statement that
#: orders, so a row whose key was altered to sort late falls beyond the cut and is
#: never decoded and never compared — the caller is handed a wrong page with every
#: row on it valid. Validating rows the bound excludes would mean reading the whole
#: table to serve a page, which is the bound defeated rather than enforced.
#:
#: Rewriting ``data`` is refused here too, which is what makes the derived columns
#: whole: they cannot disagree with the blob, so the remaining move against them
#: was to move the blob.
#:
#: **What it is and is not.** It is this store's invariant enforced by the store,
#: the way a ``UNIQUE`` index enforces write-once; it is not a boundary against an
#: actor who can already run arbitrary SQL against the file, who could drop it as
#: easily as run the ``UPDATE``. ADR-0004 §4's owner-only mode is where that
#: question is answered, and ADR-0099 §1's single-user model is what scopes it.
_APPEND_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS recipient_grants_append_only "
    "BEFORE UPDATE ON recipient_grants "
    "BEGIN SELECT RAISE(ABORT, 'the recipient-grant store is append-only; a grant is "
    "never edited, narrowed or re-scoped in place'); END"
)

#: **Every object this store defines, held to its own definition.** ``CREATE TABLE
#: IF NOT EXISTS`` is a no-op against a table already there under that name
#: *whatever shape it has*, so a file arriving with a ``recipient_grants`` table of
#: ordinary columns keeps it — and both generated projections then read as ``NULL``,
#: because ``_record_sync`` writes only ``decided_at_us`` and ``data``. The
#: outstanding anti-join would then find no revocation at all and every revoked
#: grant would answer as live: the exact failure the generated columns exist to
#: make impossible, walked around rather than through. The indexes and the trigger
#: are held the same way and for the same reason — a pre-existing non-unique
#: ``recipient_grants_revokes`` lets one grant be revoked twice, and a pre-existing
#: trigger that does nothing lets the ordering key be rewritten.
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds
#: is compared against these very statements rather than against a second copy of
#: them written out by hand.
_OBJECTS: Final = {
    "recipient_grants": _CREATE_TABLE,
    **_INDEXES,
    "recipient_grants_append_only": _APPEND_ONLY,
}

_ORDERED = "SELECT data FROM recipient_grants ORDER BY decided_at_us DESC, id ASC"

#: Every **outstanding** granting record: rows whose derived ``revokes`` is NULL
#: that no recorded revocation names. Liveness's clock-free half, and the whole of
#: what ``record`` and ``outstanding`` decide over — no instant appears in this
#: statement at all, which is what keeps the write path free of a clock and lets an
#: expired-but-unrevoked grant still be revoked (ADR-0193 §1, §9).
#:
#: It is also what ``covering`` and ``standing`` read: the interval they add is
#: applied over the **decoded** records rather than in SQL, so no instant that
#: decides coverage is ever read from a column.
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

#: Whether one id is already held, over the derived column so a hand-written
#: ``id`` cannot hide a row from the duplicate check.
_ID_IS_HELD = "SELECT 1 FROM recipient_grants WHERE id = ?"


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


def _is_live(grant: RecipientGrant, reading: datetime) -> bool:
    """Whether ``grant`` is live at ``reading`` (ADR-0193 §1, §9).

    The interval is **closed below and open above** — at or after ``decided_at``
    and strictly before ``expires_at`` — and both ends are read off the **record**
    rather than off a column, so no instant that decides coverage comes from a
    projection. Bounded below as well as above, because without that half a
    future-dated grant would be handed to the policy and ``AuditTrail.record``
    would then refuse the ``ALLOW`` it sourced.

    ``reading`` is passed in rather than taken here, which is §9's single-read
    clause: one instant measures every record a query considers, and a per-row
    reading could return one of two grants sharing an ``expires_at`` and omit the
    other — a set true at no real instant.

    A ``revokes``-bearing record is never live, and it never reaches this function:
    the callers read :data:`_OUTSTANDING`, which returns granting records alone.
    """
    return grant.decided_at <= reading < grant.expires_at


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
            ValueError: If ``max_outstanding`` is not a non-negative ``int``. A
                negative ceiling names no bound and would refuse every granting
                write for a reason no message explains, which is why zero is
                admitted and this is not. **And the type is checked, which a
                comparison alone does not do**: this is a cap, and a value that is
                not an integer can *disable* it rather than merely mis-size it —
                ``len(outstanding) >= float("nan")`` is false for every count, so a
                store built with one admits granting records without limit while
                every message still names a ceiling. ``type(...) is not int`` and
                not ``isinstance``, so a ``bool`` — which is an ``int`` and is
                nobody's ceiling — is refused with the rest.
        """
        if type(max_outstanding) is not int or max_outstanding < 0:
            msg = (
                f"max_outstanding must be a non-negative int, got "
                f"{describe_untrusted(max_outstanding)}; zero is meaningful (it declines "
                f"route (b)) and a negative names no ceiling"
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
                # The table is held to its definition **before** the indexes and
                # the trigger are created over it. A file arriving with a
                # ``recipient_grants`` table of ordinary columns would otherwise
                # fail on an index naming a column it does not have, and the open
                # would report a raw SQLite complaint instead of the fact — that
                # this is not this store's table and its rows cannot be trusted to
                # say what the user authorised.
                self._check_objects(conn, ("recipient_grants",))
                for statement in _INDEXES.values():
                    conn.execute(statement)
                conn.execute(_APPEND_ONLY)
                self._check_objects(conn, tuple(_OBJECTS))
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

    def _check_objects(self, conn: sqlite3.Connection, names: tuple[str, ...]) -> None:
        """Refuse a file whose ``names`` are not the objects this store defines.

        Run after the creates and **before** the marker is written, inside the same
        transaction, so a refusal leaves the file exactly as it arrived —
        unopened, unlabelled, and not carrying this store's marker over a shape
        that is not this store's.

        Every object is compared to the statement that defines it
        (:data:`_OBJECTS` says why each one matters). An object this open created
        matches by construction; one that was already there matches only if it is
        the same object, which is the whole question.

        Args:
            conn: The connection the setup transaction is running on.
            names: Which of :data:`_OBJECTS` to check. The table alone runs first,
                so a file that is not this store's is reported as that rather than
                as an index failing on a column it does not have.

        Raises:
            RecipientGrantError: If an object is missing or is not the one this
                store defines.
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
                    f"the recipient-grant store at {self._path!r} holds an object named "
                    f"{name!r} that is not the one this store defines; its rows cannot be "
                    f"trusted to say what the user authorised, so it is not opened"
                )
                raise RecipientGrantError(msg)

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
            if conn.execute(_ID_IS_HELD, (snapshot.id,)).fetchone():
                msg = (
                    f"recipient grant {snapshot.id!r} is already recorded; the store is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise InvalidRecipientGrantError(msg)
            if snapshot.revokes is None:
                self._check_granting(conn, snapshot)
            else:
                self._check_revocation(conn, snapshot)
            # Only the two stored columns: `id` and `revokes` are derived from the
            # blob by the table's own definition, so there is nothing to write and
            # nothing that could be written disagreeing with it.
            conn.execute(
                "INSERT INTO recipient_grants(decided_at_us, data) VALUES (?, ?)",
                (_sort_key(snapshot.decided_at), snapshot.model_dump_json()),
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
            # **The discriminator ADR-0235 §4 adds**, and it is a subclass rather
            # than a reason member: the base class still catches this ground, so
            # ADR-0193 §1's one-handler benefit is preserved rather than traded. A
            # user whose subject already stands needs **no** act at all, which is
            # what makes this recourse different from every ground that keeps the
            # base class.
            raise DuplicateRecipientGrantError(msg)
        if len(outstanding) >= self._max_outstanding:
            msg = (
                f"the recipient-grant store holds {len(outstanding)} outstanding grants and "
                f"admits {self._max_outstanding}, so grant {grant.id!r} is refused; nothing "
                f"is evicted, narrowed or expired to make room, and the recourse is to "
                f"revoke a grant you hold (ADR-0193 §1)"
            )
            # **The second discriminator** (ADR-0235 §4). ADR-0193 §1's ceiling
            # clause obliges a surface offering the establishing act to name *that*
            # the ceiling was reached, and a surface names a reason it was told —
            # so the ground is read from the refusal's own type and never from this
            # message, a count the caller took, or a listing read afterwards.
            raise RecipientGrantCeilingError(msg)

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
        the least ``id``. That order is :data:`_OUTSTANDING`'s own ``ORDER BY``, so
        the **first** matching row is the winner and no second sort is needed —
        which is why the loop below stops at the first match rather than collecting
        and ranking.

        **Liveness is decided over the decoded record**, not in SQL, so both ends
        of the interval come from the blob rather than from a column (see
        :data:`_CREATE_TABLE`). The clock is read **once**, and every record the
        loop considers is measured against that one instant.

        **Every value the comparison is decided over is read before the first
        await** (:func:`_coverage_subject`), and the lookup consults the request no
        further. This method suspends twice before it compares anything — for the
        lock, and for the read behind it — and a lookup that captured the
        destination set on the way in and re-read the declaration on the way out
        would answer about neither request: ADR-0065's rule, on the argument this
        seam rules over.

        Raises:
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        subject = _coverage_subject(request)
        if subject is None:
            return None
        async with self._lock:
            rows = await _run_to_completion(self._outstanding_sync)
        reading = self._clock()
        for row in rows:
            grant = _decode(row)
            if _is_live(grant, reading) and subject.covered_by(grant):
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
            rows = await _run_to_completion(self._outstanding_sync)
        reading = self._clock()
        return [grant for row in rows if _is_live(grant := _decode(row), reading)]

    def _outstanding_sync(self) -> Sequence[str]:
        """Read every outstanding granting row — the clock-free half of liveness."""
        return self._read(self._conn, _OUTSTANDING, ())

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
            rows = await _run_to_completion(self._one_outstanding_sync, grant_id)
        return _decode(rows[0]) if rows else None

    def _one_outstanding_sync(self, grant_id: str) -> Sequence[str]:
        """Read the outstanding granting row with ``grant_id``, if there is one."""
        return self._read(self._conn, _OUTSTANDING_BY_ID, (grant_id,))

    async def recent(self, *, limit: int = 50) -> list[RecipientGrant]:
        """Return up to ``limit`` records, newest first, ties broken by id ascending.

        Bounded because every read of a Tier 1 store in this corpus is (ADR-0021
        §4): the row count here grows with grant churn rather than with the number
        of recipients. Revoked grants and revoking records alike are returned, and
        no liveness is evaluated, so no clock is read.

        Raises:
            ValueError: If ``limit`` is not a strictly positive **exact** ``int``.
                Non-positive is refused rather than clamped or passed through:
                SQLite reads ``LIMIT -1`` as *no limit at all*, so the one call
                offering a bounded read of a Tier 1 store would become the
                unbounded read it exists to avoid. **The type is checked as an
                allowlist of the exact ``int``**, which a comparison alone does
                not do and a denylist naming ``bool`` cannot close: ``True`` is an
                ``int``, passes ``<= 0``, and is silently taken as a bound of one,
                so a caller asking for the newest fifty would be handed one record
                and told nothing; a ``float`` is bound to ``LIMIT ?`` as a float or
                truncates somewhere below this layer; and an ``int`` subclass
                overriding its comparisons passes the positivity check while
                meaning something other than its integer value. ``None`` is the
                case this closes at the surface rather than in the driver — the
                comparison itself raised a bare ``TypeError``, which is neither
                class this member documents, so it left this layer's error
                boundary through a hole (#1598).
            RecipientGrantError: If the store cannot be read, or holds a record
                that no longer validates.
        """
        # **This is not a narrowing of ADR-0193's "the contract admits every strictly
        # positive integer".** That sentence's subject is *magnitude*: it is stated of
        # `recent(limit=2**63)`, against a store that would raise `OverflowError` on it,
        # and the conformance case pinning it passes here unchanged. What is refused
        # below is a *class*, not a value — and refusing it is the rule this corpus
        # already states where it states it most fully, `core.config`'s own integer
        # setting validator (issue #471): an allowlist of the exact ``int``, because
        # "every value this refuses — ``bool``, and any other ``int`` subclass whose
        # instances mean something other than their integer value — is precisely an
        # ``isinstance`` match". Nothing that reaches this member through the wire is
        # such a class; the surface decodes plain ints, which is why that validator
        # calls its own guard reachable only from untyped code. Settling the reading in
        # `core/protocols.py`'s own text is #1597's, which asks the question of the
        # whole grant-shaped family at once.
        #
        # ``ValueError`` for the type as well as for the sign, and not the
        # ``TypeError``/``ValueError`` split some constructors in this corpus use:
        # ``RecipientGrantStore.recent`` in ``core/protocols.py`` documents exactly
        # ``ValueError`` and ``RecipientGrantError``, and an implementation raising
        # a third class would be one the contract does not describe. It is also the
        # shape this file's own ``max_outstanding`` guard already takes.
        if type(limit) is not int or limit <= 0:
            msg = (
                f"limit must be a strictly positive int, got "
                f"{describe_untrusted(limit)}; the type is checked because a bool "
                f"passes the comparison while meaning a bound of one"
            )
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


class _CoverageSubject(NamedTuple):
    """The three values ADR-0193 §3's store-side comparisons are decided over.

    Built by :func:`_coverage_subject` before the first ``await`` and consulted
    afterwards in its place, so that one lookup answers about one request.
    """

    tool: ToolDefinition
    account: BoundAccount
    wanted: tuple[CanonicalDestination, ...]

    def covered_by(self, grant: RecipientGrant) -> bool:
        """Whether ``grant`` covers this subject — §3's four store-side comparisons.

        Containment is membership and nothing looser: no case folding, no domain
        matching, no treating an account member as covering a recipient member or
        the reverse, and no re-canonicalising either side. Liveness is the
        caller's, because the clock is read once for the whole lookup.
        """
        return (
            grant.tool == self.tool
            and grant.account == self.account
            and all(member in grant.destinations for member in self.wanted)
        )


def _coverage_subject(request: ActionRequest) -> _CoverageSubject | None:
    """What ``request`` asks this store, as values, or ``None`` if it asks nothing.

    **Read before the first await, and detached** (ADR-0065). A lookup suspends —
    for a lock, for a read, or for whatever a double models — and a frozen model
    is rewritable through ``__dict__``, so a caller can replace ``request.tool``
    while the lookup waits. An implementation that captured the destination set on
    the way in and re-read the declaration on the way out would then return the
    grant established for the *second* tool as covering the *first* tool's
    recipients — an answer describing neither request, from the seam whose answer
    is the gate.

    Detached as well as captured, because capturing the objects leaves the same
    rewrite available one level down. ``ActionRequest`` already takes its own copy
    of both the declaration and the binding at construction
    (``core.types._detached_tool`` and ``_detached_binding``), so this is that
    discipline continued across a suspension rather than a new one, and it is
    spelled the way those are: rebuilt through validation, never deep-copied.

    ``None`` **covers nothing and is not an error.** A request with no binding is
    not an egress call and this store has no question to answer about it; a
    request that cannot be read as one at all is answered the same way, which is
    the fail-closed direction — no grant, so the disclosure floor stands and the
    user is asked (ADR-0193 §1's fail-closed clause, §7's floors).

    **Which is why the binding read is inside the guard with everything else.**
    ``request.__dict__.pop("egress_binding")`` leaves a frozen model with no such
    attribute at all, and a read of one before the ``try`` would leave this seam as
    an ``AttributeError`` — a builtin out of the lookup whose documented answer to
    an unreadable request is "covered by nothing".
    """
    try:
        binding = request.egress_binding
        if binding is None:
            return None
        return _CoverageSubject(
            tool=ToolDefinition.model_validate(field_state(ToolDefinition, request.tool)),
            account=BoundAccount.model_validate(field_state(BoundAccount, binding.account)),
            wanted=tuple(
                CanonicalDestination.model_validate(field_state(CanonicalDestination, member))
                for member in binding.canonical_destination_set
            ),
        )
    except Exception:  # a request this store cannot read coherently is covered by nothing
        return None


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
    caller's subclass could carry extra fields, and they are refused here rather
    than allowed to vanish at serialisation and make the stored record differ from
    the one that reloads.

    **And rebuilt from the instance's field state rather than from
    ``model_dump()``**, which is ``SqliteSourceGrantStore._revalidated``'s
    discipline and matters more on this record than on that one. ``model_dump`` is
    an ordinary overridable method, so a subclass can return a mapping that does
    not describe itself — a one-recipient instance whose dump names two — and the
    store would then append **an authorisation over a recipient the user never
    named**. That is not the caller-falsifies-its-own-record case ADR-0018 §3 puts
    outside a store's reach: the object presented is a valid narrow grant and the
    record kept is a wider one, which is precisely what "stores a detached,
    validated snapshot" denies. ``field_state`` is that read — the class's own
    serializer, resolved on the class, consulting no instance attribute — and it
    is the trail's, shared rather than spelled a second way.

    **And detached *recursively*, which is what ``field_state`` buys over a copy
    of ``__dict__``.** ADR-0193 §1 asks for a snapshot "recursively over reachable
    state", and a mapping of the instance's own field values still holds the
    caller's ``tool``, ``account`` and ``CanonicalDestination`` objects: pydantic's
    default ``revalidate_instances="never"`` keeps whatever instance was passed, so
    the snapshot and the caller share every model beneath the root. ``frozen=True``
    refuses ``destination.canonical = …`` and does not refuse
    ``destination.__dict__["canonical"] = …``, so a caller could rewrite a
    recipient **after** ``record`` accepted the grant and before the write inside
    the lock serialises it — storing an authorisation over Bob from a grant that
    named Alice. ``field_state`` returns plain mappings all the way down, so the
    rebuild below constructs every nested model afresh and the store shares no
    object with the caller at any depth.

    **Nothing of the caller's is read outside the guard**, the diagnostic id
    included (:func:`_named`). ``record`` is typed to take a ``RecipientGrant`` and
    the caller is not obliged by anything at runtime to pass one: a ``None``, or a
    record whose ``__dict__`` is missing a field, has no ``id`` attribute at all,
    and a read of one outside the ``try`` would replace the refusal this layer owes
    with a builtin escaping its error boundary. ``field_state`` hands a value that
    is not a ``RecipientGrant`` straight to ``model_validate`` untouched, which
    refuses it as the invalid record it is.

    Raises:
        InvalidRecipientGrantError: If the record does not satisfy its own model,
            carries state ``RecipientGrant`` declares no field for, or holds
            beneath it a model of any type other than exactly the declared one.
            ``ValueError`` and not ``ValidationError``: those are the classes
            ``field_state`` refuses in, and pydantic's own is one of them. The
            subclass rather than the ``RecipientGrantError`` base: here the base is
            the *store fault* and only the subclass says "your record was refused",
            which is the distinction a consumer's fail-closed branch keeps alive.
    """
    try:
        return RecipientGrant.model_validate(field_state(RecipientGrant, grant))
    except ValueError as exc:
        # `describe_untrusted` on the cause as well as on the id: `field_state`
        # re-raises a `ValueError` the caller's own code raised, and a hostile
        # `__str__` on it would replace this refusal with whatever it threw — from
        # inside the `except` block that exists to report it.
        msg = f"recipient grant {_named(grant)} is not a valid record: {describe_untrusted(exc)}"
        raise InvalidRecipientGrantError(msg) from exc


def _named(given: object) -> str:
    """Name ``given`` for a refusal message, without reading an attribute of it.

    ``given.id`` is not available: the value reaching :func:`_revalidated` is
    whatever the caller passed, and a record whose ``__dict__`` is missing a field
    — or a value that is not a record at all — has no ``id`` attribute, so
    composing the message from one would replace the refusal this layer owes with
    a builtin escaping its error boundary. ``isinstance`` is inside the guard with
    everything else, because asking what something is consults ``__class__``,
    which can be a property that raises.

    Nothing here hashes a key the caller controls: a model's ``__dict__`` is
    annotated ``dict[str, Any]`` and nothing enforces it at runtime, so a key can
    be an object whose ``__hash__`` collides with a field name and whose ``__eq__``
    raises on the comparison that collision provokes. Iterating hashes nothing, and
    only a real ``str`` — whose hash and equality are the interpreter's — is asked
    whether it names the id.
    """
    try:
        if isinstance(given, RecipientGrant):
            for key, value in object.__getattribute__(given, "__dict__").items():
                if type(key) is str and key == "id":
                    return describe_untrusted(value)
    except Exception:  # the value cannot even be named; say so and carry on
        return "the given value"
    return "the given value"


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
