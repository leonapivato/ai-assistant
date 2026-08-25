"""A durable :class:`~ai_assistant.core.protocols.AuditTrail` on SQLite (ADR-0036 §2).

ADR-0004 §7 makes the permission trail a Tier 1 store whose job is to make the
assistant's behaviour "transparent and reviewable", and ADR-0021 §1 embeds the
whole ``ToolDefinition`` in every record precisely so the trail still says what
was approved after a restart has rebuilt the registry (issue #54). Both of those
are claims about a record that outlives the process, so the trail persists —
ADR-0036 §2 records why an in-process one would have satisfied the Protocol and
not the decisions behind it.

The on-disk schema carries a ``meta("schema_version")`` marker, the same shape
:mod:`ai_assistant.planning.sqlite_store` writes (ADR-0049 §1). The *marker* is
shared; the *mechanism* is not — evolution here stays the additive,
column-presence ``ALTER`` of :meth:`SqliteAuditTrail._migrate`, which is what an
append-only trail with existing rows can afford. A database predating the marker
is stamped once this code has migrated it, and a version-1 one is restamped, never
refused; see :meth:`SqliteAuditTrail._check_schema_version`.

Local-first (ADR-0002), and **locally only**: ADR-0021 §4 applies ADR-0004 §2's
residency clause to this store by name, so nothing here may reach a remote
service. The database file is created owner-only (ADR-0004), following the
precedent :mod:`ai_assistant.memory.sqlite_store` set.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    DuplicateDecisionError,
    InvalidCompletionError,
    InvalidResolutionError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    DurableIdentifier,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    RecordedInvocation,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
)
from ai_assistant.permissions._transactions import transaction
from ai_assistant.permissions.identifiers import IdentifierFactory, ProcessIdentifiers

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

_log = structlog.get_logger(__name__)

#: The named condition a park is refused under when the row it would be rebuilt
#: from predates ADR-0181's ``planned_with_external_content``. In the corpus's
#: condition style — ``hub-unreachable``, ``no-live-session`` — and a module
#: constant rather than a literal so a test asserts the *name* a reader will meet
#: in the log rather than a spelling of it.
ORIGIN_UNRECORDED = "origin-unrecorded"

_OWNER_ONLY = 0o600

#: The sidecars SQLite may keep beside a database file. Each holds the same pages
#: the database does, so ADR-0004 §4 reaches them too. SQLite copies the database
#: file's mode onto a sidecar **it creates**, which is what makes restricting the
#: file before the first statement sufficient for those — but that inheritance does
#: not reach one that is *already there*: a ``-journal`` left behind by a crash, or
#: a ``-wal``/``-shm`` from a process that put this file into WAL mode, keeps its
#: own mode across a reopen and then takes Tier 1 pages (#490).
_SIDECARS = ("-journal", "-wal", "-shm")


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The trail serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    The worker records its own outcome and sets a :class:`threading.Event` when it
    physically returns. This coroutine waits on *that* signal — not on the
    cancellable state of any task — so the lock is held for the whole life of the
    worker even if the awaiting task, or a blanket :func:`asyncio.all_tasks`
    cancellation, is cancelled. Nothing here is an :class:`asyncio.Task`: the work
    runs on an executor future and the fallback wait is another, so a task sweep
    finds nothing to cancel out from under the running thread. An absorbed
    cancellation takes precedence over the worker's own result or failure and is
    re-raised once the thread has finished: the caller's task still cancels; what
    is prevented is connection reuse, not the cancellation itself.

    Every failure the worker sees is relayed, ``BaseException`` included. A
    narrower ``except Exception`` catches nothing when ``fn`` raises outside it, so
    both lists stay empty while ``finally: done.set()`` still fires — and the
    caller is then answered out of an empty ``outcome``, an ``IndexError`` standing
    in for the cause rather than chained to it (#680). Which of the two waits below
    runs decides whether the caller sees that or the real failure, which is why it
    presented as an intermittent fault rather than a reproducible one.
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
    cancellation: asyncio.CancelledError | None = None
    while not done.is_set():
        try:
            await asyncio.shield(pending)
        except asyncio.CancelledError as exc:
            # Absorb the cancellation and keep waiting on the worker's physical
            # completion signal, so the lock outlives the still-running thread.
            cancellation = exc
            pending = loop.run_in_executor(None, done.wait)
    if cancellation is not None:
        raise cancellation
    if failure:
        raise failure[0]
    return outcome[0]


#: The widest value SQLite will bind to an INTEGER parameter. A Python int is
#: unbounded, so ``recent`` clamps to this before binding ``LIMIT``.
_MAX_SQLITE_INT = 2**63 - 1

#: The on-disk schema this code writes and maintains, recorded in ``meta`` so a
#: reader has a marker to judge the file by — the seam ADR-0049 §1 describes and
#: the ``SqlitePlanStore`` pattern this follows.
#:
#: **Version 2 is the invocation shape** (ADR-0192 §2): the ``invocations`` table
#: beside ``decisions``, one identifier space over both, and a ``clear()`` that
#: erases both. Version 1 is the decisions-only shape, and the bump is not
#: bookkeeping. Version-1 code opening a version-1 file it has since grown
#: invocation rows in **cannot maintain either invariant**: its ``clear()`` deletes
#: decisions and leaves the invocation rows behind — an erasure ADR-0192 §6
#: requires to be total, silently partial — and its uniqueness check sees only
#: ``decisions``, so it can record a decision under an id an invocation already
#: holds, which the joined reads then resolve to two rows under one identifier.
#: ADR-0049 §1 already rules that "a downgrade is a fault to report"; leaving the
#: marker at 1 is what would make it unreportable.
_SCHEMA_VERSION = 2

#: The versions this code can *open*. Anything else is refused, newer or older
#: (ADR-0049 §1). A version-1 file is opened and brought to :data:`_SCHEMA_VERSION`
#: by the same additive create-and-migrate every open runs, then restamped — so no
#: trail already on disk becomes unopenable, which is the failure
#: :meth:`SqliteAuditTrail._check_schema_version` exists to avoid.
_OPENABLE_VERSIONS: Final[frozenset[int]] = frozenset({1, _SCHEMA_VERSION})

#: Created first and on its own, so a database labelled with a schema this code
#: cannot read is refused *before* the ``decisions`` table is created, migrated or
#: read — creating a table is a write, and the refusal precedes any write
#: (ADR-0049 §1's ordering, applied here).
_META_SCHEMA = "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"

_READ_SCHEMA_VERSION = "SELECT value FROM meta WHERE key = 'schema_version'"

_WRITE_SCHEMA_VERSION = "INSERT INTO meta(key, value) VALUES ('schema_version', ?)"

#: Move an openable older marker up to :data:`_SCHEMA_VERSION`, in the same
#: transaction as the create-and-migrate that earned it.
_RESTAMP_SCHEMA_VERSION = "UPDATE meta SET value = ? WHERE key = 'schema_version'"

#: The epoch the sort key counts from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The columns beside the ``data`` blob exist only so SQLite can order and
# constrain; the blob is the record. ``execution_id``, ``step_id`` and
# ``outcome`` (ADR-0044) are what the per-binding rule and the recovery query
# read; ``expires_at_us`` (ADR-0059 §1) is the durable confirmation deadline as
# whole microseconds since the epoch (the ``decided_at_us`` shape), a queryable
# projection of the value the blob already carries. All are kept nullable so an
# existing older table can grow them by ``ALTER`` (:meth:`_migrate`), identical
# to a table created fresh here.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS decisions("
    "id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
    "resolves TEXT, execution_id TEXT, step_id TEXT, outcome TEXT, "
    "expires_at_us INTEGER, "
    "data TEXT NOT NULL)"
)

_INDEXES = (
    # A *unique* index, so the per-*confirmation* single-resolution rule (ADR-0036
    # §2) survives even a bug in the check below. SQLite treats NULLs as distinct,
    # so it constrains resolving rows only and leaves ordinary decisions
    # unaffected.
    "CREATE UNIQUE INDEX IF NOT EXISTS decisions_resolves ON decisions(resolves)",
    "CREATE INDEX IF NOT EXISTS decisions_order ON decisions(decided_at_us DESC, id ASC)",
    # ADR-0044 §2b: a *concrete* ``(execution_id, step_id)`` binding carries at
    # most one resolution — the per-*binding* rule layered on top of the
    # per-confirmation one. Partial, over resolving rows with a concrete binding
    # only; NULLs being distinct leaves non-concrete (direct) bindings
    # unconstrained. This is the safety net beneath the checked read in
    # :meth:`_check_binding_undecided`.
    "CREATE UNIQUE INDEX IF NOT EXISTS decisions_binding_resolution "
    "ON decisions(execution_id, step_id) "
    "WHERE resolves IS NOT NULL AND execution_id IS NOT NULL AND step_id IS NOT NULL",
    # ADR-0044 §3: ``pending_confirmation`` finds a binding's CONFIRMs by this.
    "CREATE INDEX IF NOT EXISTS decisions_binding ON decisions(execution_id, step_id, outcome)",
)

_ORDERED = "SELECT data FROM decisions ORDER BY decided_at_us DESC, id ASC"

# --- the invocation rows (ADR-0192 §2) ---------------------------------------
# The trail's second row kind, in the same store and under the same ``clear()``.
# As with ``decisions``, the columns beside ``data`` exist only so SQLite can
# order and constrain; the blob is the record.
#
# ``seq`` is the **durable append order** every admission rule in ADR-0192 §1 is
# decided on. It is deliberately not ``recorded_at_us``: a stored instant is what a
# reader is shown, and a wall clock that steps backwards must not be able to make a
# completed act stop being the most recent one. Allocated inside the same
# transaction as the insert, from the table's own maximum.
#
# **This table is what version 2 is** (:data:`_SCHEMA_VERSION`). ``CREATE TABLE IF
# NOT EXISTS`` is additive and idempotent exactly as
# :meth:`SqliteAuditTrail._migrate`'s ``ALTER``s are, so a version-1 file opens and
# gains it — and is then *restamped* 2 rather than left at 1. Leaving the marker
# alone would cost nothing here and everything to the next reader: version-1 code
# accepts a version-1 marker, and its ``clear()`` and its id-uniqueness check both
# know only ``decisions``, so it erases half of what ADR-0192 §6 says is one record
# and can mint a decision over an invocation's id. The restamp is what makes that
# downgrade the reported fault ADR-0049 §1 already calls for.
# **Four of the six columns are `GENERATED ALWAYS ... VIRTUAL` over the blob, and
# that is the whole of their integrity.** A stored projection is a second copy of a
# value the record already carries, and a filter narrowing by one decides on a value
# nothing revalidates: alter an open claim's `decision_id` and the claims-under read
# ADR-0192 §1's consume is decided over no longer sees it, so a spent authorisation
# admits a second act — and no read narrowed by a column can see what the narrowing
# removed, so validating what a filter *returns* cannot close it. Deriving the column
# from `data` closes it by construction instead: the two cannot disagree, because
# there is only one of them, and SQLite refuses an `UPDATE` of a generated column
# outright. Indexed exactly as a stored column is, at no cost to any read.
#
# `id` is generated too and carries a UNIQUE index rather than being the primary key,
# because SQLite forbids a generated column in one — the constraint is identical and
# the derivation is what matters here.
#
# The two that remain stored, and why they must be. `seq` is the durable append
# order, allocated inside the insert from the table's own maximum; it is not in the
# record and cannot be, since `ToolInvocation`'s fields are ADR-0192 §2's and adding
# one is a contract change. `recorded_at_us` is `_sort_key`'s integer microseconds,
# and `json_extract` yields the stored ISO-8601 *text*, which does not sort as an
# instant (a whole second serialises without a fraction and sorts after the same
# second with one). Both are checked against the record wherever a read returns the
# row (:func:`_as_projected`), and neither decides an admission: `seq` orders the set
# and `recorded_at_us` orders a listing.
#
# `seq` is deliberately **not** the ordering ADR-0192 §1's "first" and "last" are
# read by way of `recorded_at`: a stored instant is what a reader is shown, and a
# wall clock that steps backwards must not make a completed act stop being the most
# recent one.
_CREATE_INVOCATIONS = (
    "CREATE TABLE IF NOT EXISTS invocations("
    "seq INTEGER NOT NULL, recorded_at_us INTEGER NOT NULL, data TEXT NOT NULL, "
    "id TEXT GENERATED ALWAYS AS (json_extract(data, '$.id')) VIRTUAL, "
    "decision_id TEXT GENERATED ALWAYS AS (json_extract(data, '$.decision_id')) VIRTUAL, "
    "completes TEXT GENERATED ALWAYS AS (json_extract(data, '$.completes')) VIRTUAL, "
    "outcome TEXT GENERATED ALWAYS AS (json_extract(data, '$.outcome')) VIRTUAL)"
)

_INVOCATION_INDEXES = (
    # The primary key `id` cannot be, because SQLite refuses a generated column in
    # one. Same constraint, same enforcement, and the derivation is kept.
    "CREATE UNIQUE INDEX IF NOT EXISTS invocations_id ON invocations(id)",
    # A *unique* index, so "a claim is completed once" survives even a bug in the
    # checked read. SQLite treats NULLs as distinct, so it constrains completions
    # only and leaves claims unaffected.
    "CREATE UNIQUE INDEX IF NOT EXISTS invocations_completes ON invocations(completes)",
    # The append order, and the per-decision scan every admission rule reads.
    "CREATE UNIQUE INDEX IF NOT EXISTS invocations_seq ON invocations(seq)",
    "CREATE INDEX IF NOT EXISTS invocations_decision ON invocations(decision_id, seq)",
    "CREATE INDEX IF NOT EXISTS invocations_order ON invocations(recorded_at_us DESC, id ASC)",
)

#: **Every column the blob also carries**, selected beside it on every read so
#: :func:`_as_projected` can hold one to the other. The columns are a filter and an
#: order, never the record: an admission decided on ``decision_id`` or ``completes``
#: alone would be decided on a value nothing revalidates, and a claim whose
#: ``decision_id`` column was altered would then drop out of the set §1's consume is
#: read over and let a second act be authorised by a spent authorisation. The
#: decision rows are already handled this way where the read is *acted* on
#: (:meth:`SqliteAuditTrail.resolution_of`); every read below acts.
#:
#: Spelled out in each statement below rather than interpolated from one constant:
#: an f-string here is a linted SQL-injection shape (``S608``), and four literals a
#: reader can check against :func:`_as_projected`'s tuple beat one suppression.

#: The two joined listings, in ``recent``'s own total order. A **LEFT** join, so an
#: invocation row whose decision is missing comes back with a NULL rather than
#: silently vanishing: ADR-0192 §2 requires that no implementation return a row it
#: could not pair, and an inner join would meet that by dropping the evidence.
_JOINED_INVOCATIONS = (
    "SELECT i.data, i.id, i.decision_id, i.recorded_at_us, i.completes, i.outcome, d.data "
    "FROM invocations i "
    "LEFT JOIN decisions d ON d.id = i.decision_id "
    "ORDER BY i.recorded_at_us DESC, i.id ASC"
)

#: Every claim under one decision, in append order — the set ADR-0192 §1's
#: conjunction is decided over.
_CLAIMS_UNDER = (
    "SELECT data, id, decision_id, recorded_at_us, completes, outcome "
    "FROM invocations "
    "WHERE decision_id = ? AND completes IS NULL ORDER BY seq ASC"
)

#: Every completion under one decision. Read whole rather than by claim, because
#: the conjunction asks three questions of the set at once.
_COMPLETIONS_UNDER = (
    "SELECT data, id, decision_id, recorded_at_us, completes, outcome "
    "FROM invocations "
    "WHERE decision_id = ? AND completes IS NOT NULL"
)

#: The claims under one decision that no completion names, in append order — the
#: exact set ADR-0192 §3's recovery rule is written against.
_OPEN_UNDER = (
    "SELECT data, id, decision_id, recorded_at_us, completes, outcome "
    "FROM invocations "
    "WHERE decision_id = ? AND completes IS NULL "
    "AND id NOT IN (SELECT completes FROM invocations WHERE completes IS NOT NULL) "
    "ORDER BY seq ASC"
)

#: One claim by id, for the completion path to check and read its decision from.
_OPEN_CLAIM = (
    "SELECT data, id, decision_id, recorded_at_us, completes, outcome "
    "FROM invocations WHERE id = ? AND completes IS NULL"
)

#: Whether an identifier is already taken, over **one id space and it is every row
#: the store holds** — decisions and invocations alike (ADR-0192 §2). A narrower
#: space would let an invocation be appended under a decision's id, which the
#: joined reads then resolve to two different rows under one identifier.
_ID_IS_HELD = (
    "SELECT 1 FROM decisions WHERE id = ? UNION ALL SELECT 1 FROM invocations WHERE id = ? LIMIT 1"
)

#: The redraw bound: as many draws as the store holds rows, plus one. A bound the
#: store's own *current* contents fix, so any draw sequence that can clear does
#: clear within it — and so it consults no generation, epoch or high-water mark and
#: holds nothing across an erasure (ADR-0192 §6).
_ROWS_HELD = "SELECT (SELECT COUNT(*) FROM decisions) + (SELECT COUNT(*) FROM invocations)"

#: A validator for whatever the injected factory returned. A factory that *returns*
#: a value no row can be built from is a non-conforming collaborator's **output**
#: and not an exception of its own, so it is the guard-rejection arm (ADR-0026 §2).
_IDENTIFIER: Final[TypeAdapter[str]] = TypeAdapter(DurableIdentifier)


def _utc_now() -> datetime:
    """The default clock: the real one, read in UTC."""
    return datetime.now(UTC)


#: A binding's CONFIRMs, newest first — the candidates ``pending_confirmation``
#: chooses from once it knows the binding is undecided.
_BINDING_CONFIRMS = (
    "SELECT data FROM decisions "
    "WHERE outcome = ? AND execution_id = ? AND step_id = ? "
    "ORDER BY decided_at_us DESC, id ASC"
)

#: Whether a concrete binding already carries a resolution. A resolution's own
#: ``(execution_id, step_id)`` equals its confirmation's (ADR-0044 §2a and the
#: ``step_id`` check enforce it at record time), so a resolving row with this
#: binding *is* a resolution of one of its CONFIRMs. Answers both step 1 of
#: ``pending_confirmation`` and §2b's checked refusal, and matches exactly what
#: the ``decisions_binding_resolution`` partial unique index constrains.
_BINDING_HAS_RESOLUTION = (
    "SELECT 1 FROM decisions "
    "WHERE resolves IS NOT NULL AND execution_id = ? AND step_id = ? LIMIT 1"
)

#: The resolution recorded for a concrete binding — the ALLOW or DENY
#: ``resolution_of`` (ADR-0059 §2) hands back. Same predicate as
#: ``_BINDING_HAS_RESOLUTION`` but selecting the row: a resolving decision's own
#: ``(execution_id, step_id)`` equals its confirmation's (ADR-0044 §2a), so a
#: resolving row with this binding *is* a resolution of one of its CONFIRMs. By
#: §2b at most one exists per concrete binding (the
#: ``decisions_binding_resolution`` unique index); the ordering makes the read
#: deterministic even if that net were somehow bypassed. Never a CONFIRM: a
#: resolving decision whose ruling is CONFIRM is unconstructable
#: (``_a_resolution_is_not_itself_a_question``).
_BINDING_RESOLUTION = (
    "SELECT data FROM decisions "
    "WHERE resolves IS NOT NULL AND execution_id = ? AND step_id = ? "
    "ORDER BY decided_at_us DESC, id ASC LIMIT 1"
)


def _sort_key(instant: datetime) -> int:
    """Return ``instant`` as whole microseconds since the epoch.

    An **integer**, computed from a ``timedelta``'s integer components rather
    than from ``timestamp()``. Ordering is the trail's contract (ADR-0021 §4),
    and a float epoch second carrying microsecond precision needs sixteen
    significant digits at present-day values — right at the edge of a double, so
    two decisions a microsecond apart could compare equal or invert. The
    subtraction below is exact.

    ``decided_at`` is a ``UtcInstant``, already normalised to UTC by ``core``, so
    this is a key over *instants* — which is what makes the DST repeated hour
    sort correctly rather than by wall clock.
    """
    elapsed = instant - _EPOCH
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


class SqliteAuditTrail:
    """A persistent, append-only, validating ``AuditTrail``.

    Structurally implements :class:`~ai_assistant.core.protocols.AuditTrail`,
    including the parts that make the trail an *active* participant: write-once
    ids, the resolution invariant, and detachment on both the write and the read
    path.

    **Records are stored as their JSON dump and rebuilt on every read**, which is
    how ADR-0021 §4's "detached, validated snapshot" is obtained here without a
    copy step to forget: serialising rebuilds every reachable value, so there is
    no object graph shared with the caller in either direction, and the store
    cannot hand back a caller-supplied subclass. The columns beside the blob
    exist only so SQLite can order and constrain; the blob is the record.

    **Atomicity** (ADR-0021 §4) comes from an :class:`asyncio.Lock` around the
    whole of :meth:`record`, with the duplicate check, the resolution validation
    and the insert running in one ``to_thread`` call inside a single SQLite
    transaction. Two concurrent resolutions of one ``CONFIRM`` therefore cannot
    both observe an unresolved question, which is the guarantee the atomicity
    clause exists for.
    """

    def __init__(
        self,
        *,
        path: Path | str,
        now: Callable[[], datetime] = _utc_now,
        identifiers: IdentifierFactory | None = None,
    ) -> None:
        """Open (or create) the trail at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral trail.
                **Required, with no default.** Durability is the whole reason
                this implementation exists (ADR-0036 §2), so a default would let
                the ordinary construction produce a trail that forgets
                everything on restart — the failure the ADR argues against,
                reachable by omitting an argument. An ephemeral trail is
                available and has to be asked for.
            now: The clock the ledger stamps ``recorded_at`` from, wrapped by
                ``checked_clock`` (ADR-0026). Injected so a suite pins the window
                boundary rather than racing it, which is ``CONTRIBUTING.md``'s
                determinism rule satisfied the way the rest of the tree satisfies
                it. **No caller supplies an instant** (ADR-0192 §1): a store that
                enforced a window against a number the party being bounded chose
                would enforce nothing.
            identifiers: The factory each row's ``id`` is minted from. Defaults to
                the process's own, so two stores in one process never mint from
                independent sequences (ADR-0192 §2). Injected so a suite can force
                a collision or pin a sequence.

        Raises:
            AuditError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqliteAuditTrail")
        self._identifiers: IdentifierFactory = (
            identifiers if identifiers is not None else ProcessIdentifiers()
        )
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    def _setup(self) -> sqlite3.Connection:
        """Connect and create the schema, never leaking a half-open connection."""
        try:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        except (sqlite3.Error, OSError) as exc:
            # e.g. the parent directory does not exist — no connection to close.
            msg = f"failed to open the audit trail at {self._path!r}: {exc}"
            raise AuditError(msg) from exc
        try:
            # Restricted *before* the first statement, not after the schema is
            # built and migrated. SQLite copies the database file's mode onto every
            # rollback journal it creates for it, so a journal opened while the
            # file still carried the process umask is world-readable too — and an
            # interrupted write leaves it on disk holding Tier 1 pages (ADR-0004
            # §1, §4). The `BEGIN IMMEDIATE` below is exactly such a write, and
            # `_migrate` inside it can rewrite the whole table. `connect` creates
            # the file, so there is something to restrict by the time this runs
            # (#489; the four other SQLite stores have the same ordering).
            self._restrict_permissions()
            # `BEGIN IMMEDIATE` takes the write lock before the schema is
            # inspected, so the whole of create/migrate/index is **serialised
            # against another process opening the same file** — the same guard
            # `_record_sync` uses, applied to setup. Without it, two processes
            # upgrading a pre-ADR-0044 database could both read the old columns,
            # and the second's `ALTER TABLE ... ADD COLUMN` would then fail with a
            # duplicate-column error; the lock makes the loser wait and re-read
            # the migrated schema instead (its `missing` set comes back empty).
            with conn:  # commits on success, rolls back on any exception
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(_META_SCHEMA)
                stored = self._check_schema_version(conn)
                conn.execute(_CREATE_TABLE)
                self._migrate(conn)
                conn.execute(_CREATE_INVOCATIONS)
                for statement in (*_INDEXES, *_INVOCATION_INDEXES):
                    conn.execute(statement)
                if stored is None:
                    # Stamped *after* the create/migrate above, so the marker is
                    # only written for a file this open has actually brought to
                    # `_SCHEMA_VERSION`. Both are in the one transaction, so a
                    # migration that raises rolls the marker — and the `meta` table
                    # itself — back with it, leaving an untouched legacy database
                    # rather than one falsely labelled current.
                    conn.execute(_WRITE_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
                elif stored != _SCHEMA_VERSION:
                    # An openable older marker, moved up by the same rule and in
                    # the same transaction: the file now *has* the invocation
                    # shape, so it says so. Restamping before the create would
                    # label a file this open had not yet brought up.
                    conn.execute(_RESTAMP_SCHEMA_VERSION, (str(_SCHEMA_VERSION),))
        except AuditError:
            # A migration reporting a corrupt legacy row is already this layer's
            # error; it still leaves a connection to close before it propagates.
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the audit trail at {self._path!r}: {exc}"
            raise AuditError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case rather than a fault — :data:`_SIDECARS`
        names every file SQLite *may* keep, and a cleanly closed database has none of
        them — so absence is tolerated one name at a time. Nothing else is: a sidecar
        this process cannot restrict is a Tier 1 file it is about to write through, so
        that failure propagates and the open fails.

        A *symlink* under a sidecar's name is skipped rather than followed. ``chmod``
        follows links, and ``os.chmod(follow_symlinks=False)`` is unsupported on
        Linux, so restricting one would silently narrow a file that holds none of
        this store's data and that this store has no business modifying.

        Skipping it strands no page anywhere this method could not reach, because
        SQLite does not follow such a link either (verified against 3.53.1, and
        asserted in the conversation store's tests): a symlinked ``-journal`` is not
        a hot journal, so SQLite unlinks *the link* at the first statement and writes
        a real file in its place — which inherits the ``0600`` set just above — and a
        symlinked ``-wal`` on a WAL-mode database is refused outright rather than
        written through. What is left is a check-then-chmod race, and winning it
        needs write access to the database's own directory, which is already past
        ADR-0004 §4 by routes this method could never close.

        A no-op in memory, where there is no file to restrict.
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

    def _check_schema_version(self, conn: sqlite3.Connection) -> int | None:
        """Refuse a labelled schema this code cannot open; say which one is labelled.

        Runs inside the setup transaction, after ``meta`` exists and **before** the
        ``decisions`` table is created, migrated or read.

        Returns:
            The stored ``schema_version``, or ``None`` where the database carries
            none. :meth:`_setup` stamps an unmarked file and restamps an openable
            older one, in both cases *after* the create-and-migrate has brought it
            to :data:`_SCHEMA_VERSION`.

        **An unmarked database is backfilled, not refused.** The marker arrives
        after this store already had users, so the oldest audit trails on disk
        carry none — refusing them would make a Tier 1 record the user is
        entitled to keep (ADR-0004 §7) unopenable by the code that wrote it, which
        is a far worse failure than the one a marker exists to prevent. It is also
        sound rather than merely lenient: :meth:`_migrate` is additive and
        idempotent, keyed on column presence, so it brings *any* pre-marker file to
        exactly the shape this code maintains. The stamp records what this open has
        just established, not an assumption about what was there before.

        **A version-1 database is opened and restamped, for the same reason.** The
        step from 1 to 2 is the ``invocations`` table, which
        ``CREATE TABLE IF NOT EXISTS`` adds to any file at all, so the migration is
        the open — and refusing here would strand every trail written before
        ADR-0192 landed. The restamp is not decoration: it is what stops the
        *previous* version of this code from opening the file afterwards and
        maintaining neither ADR-0192 §6's total erasure nor §2's single identifier
        space over both row kinds.

        **Any other stored version is refused**, newer or older, matching
        ``SqlitePlanStore`` (ADR-0049 §1). A stored value outside
        :data:`_OPENABLE_VERSIONS` is either a database written by code that knows a
        schema this one does not, or a corrupt/tampered marker. Reading it blindly
        would let a downgrade construct successfully and fail later with a raw
        SQLite error — a fault to report at open, matching how the trail treats a
        row that no longer validates.

        Raises:
            AuditError: If the stored version is not one this code can open, is
                not an integer at all, or is not a single unambiguous value.
        """
        rows = conn.execute(_READ_SCHEMA_VERSION).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            # `meta`'s primary key makes this unreachable for a table *this* code
            # created — but `CREATE TABLE IF NOT EXISTS` accepts a pre-existing
            # `meta` declared without one, so a corrupt or hand-built file can hold
            # conflicting markers. Reading the first row would then let an
            # unsupported version through the refusal below on the strength of a
            # sibling row that agrees. A store that cannot say which version it is
            # is a store this code cannot read.
            found = sorted({str(row[0]) for row in rows})
            msg = (
                f"the audit trail at {self._path!r} holds {len(rows)} schema_version rows "
                f"({', '.join(repr(value) for value in found)}); the store is corrupt"
            )
            raise AuditError(msg)
        raw = rows[0][0]
        msg = f"the audit trail at {self._path!r} holds a non-numeric schema_version {raw!r}"
        # The marker this code writes is always TEXT, but `meta` may predate it
        # with a column of no declared type, in which case SQLite hands back
        # whatever was stored — a REAL, a BLOB, a NULL. Only a string or an
        # integer is parsed; `int(float("inf"))` raises `OverflowError`, which is
        # neither `ValueError` nor an `AssistantError` and would leave this
        # layer's boundary through a hole. `bool` is an `int` in Python, so it is
        # named rather than left to read as version 1.
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise AuditError(msg)
        try:
            stored = int(raw)
        except ValueError as exc:
            # A non-numeric marker is a corrupt or tampered store, not a bare
            # `ValueError` to leak past this layer's initialisation boundary.
            raise AuditError(msg) from exc
        if stored not in _OPENABLE_VERSIONS:
            supported = ", ".join(str(version) for version in sorted(_OPENABLE_VERSIONS))
            msg = (
                f"the audit trail at {self._path!r} has schema_version={stored}, but this "
                f"code can open only version {supported}; refusing to open it rather "
                f"than read it blindly"
            )
            raise AuditError(msg)
        return stored

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add and backfill the ADR-0044 binding columns, and the ADR-0059 deadline.

        Rows written before ADR-0044 carry their ``step_id`` and ``outcome`` only
        inside the JSON blob and no ``execution_id`` at all — that field did not
        exist, so a pre-ADR-0044 decision belongs to no execution and its column
        is correctly left ``NULL`` (a non-concrete binding, which §2b never
        constrains). ``step_id`` and ``outcome`` are backfilled from each row's
        stored value so the recovery query and the per-binding index see them.
        Read straight from the JSON rather than through a full model validation
        (the MemoryStore precedent, ADR-0045 §9): a migration must not fail on a
        record an unrelated future field made momentarily unvalidatable. Runs
        inside the setup transaction, before the indexes that depend on the
        columns are created; the partial unique index is safe to build over old
        data because every legacy resolution has ``execution_id`` ``NULL`` and is
        excluded by its ``WHERE``.

        ``expires_at_us`` (ADR-0059 §1) is added the same way ``execution_id``
        was — ``ALTER TABLE ... ADD COLUMN`` defaulting ``NULL`` — and, like
        ``execution_id``, is **not** backfilled: no pre-ADR-0059 record carries a
        deadline (the field did not exist), so every legacy row is correctly left
        ``NULL`` = "no lifetime". New rows populate it in :meth:`_record_sync`.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
        if "expires_at_us" not in columns:
            conn.execute("ALTER TABLE decisions ADD COLUMN expires_at_us INTEGER")
        missing = {"execution_id", "step_id", "outcome"} - columns
        if not missing:
            return
        if "execution_id" in missing:
            conn.execute("ALTER TABLE decisions ADD COLUMN execution_id TEXT")
        if "step_id" in missing:
            conn.execute("ALTER TABLE decisions ADD COLUMN step_id TEXT")
        if "outcome" in missing:
            conn.execute("ALTER TABLE decisions ADD COLUMN outcome TEXT")
        for decision_id, data in conn.execute("SELECT id, data FROM decisions").fetchall():
            try:
                payload = json.loads(data)
                execution_id = payload.get("execution_id")
                step_id = payload.get("step_id")
                outcome = (payload.get("ruling") or {}).get("outcome")
            except (ValueError, TypeError, AttributeError) as exc:
                # A blob that is not JSON, or not the object shape a decision
                # serialises to, is a corrupt row. Reported as this layer's error
                # rather than left to escape as a bare ``JSONDecodeError`` past
                # ``_setup``'s ``sqlite3``/``OSError`` boundary — the same
                # "reported, not returned" rule ``_decode`` applies at read time.
                msg = f"a legacy audit record {decision_id!r} could not be migrated: {exc}"
                raise AuditError(msg) from exc
            conn.execute(
                "UPDATE decisions SET execution_id = ?, step_id = ?, outcome = ? WHERE id = ?",
                (execution_id, step_id, outcome, decision_id),
            )

    def _transaction(
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front rather than at the first
        write, which is what puts :meth:`_record_sync`'s *reads* under it: the
        free-id check and the resolution check both decide whether the append may
        happen, so a deferred begin would let a second process observe the same
        free id or the same unresolved ``CONFIRM`` between them and the append.
        The ``asyncio`` lock closes that within one process; this closes it
        against the file. ``immediate=False`` is the read form, a deferred
        transaction for several ``SELECT``s that must see one snapshot.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`record` refuses a
        duplicate id as ``DuplicateDecisionError`` without leaving a row behind.

        Raises:
            AuditError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=AuditError, immediate=immediate)

    # --- the write path ---------------------------------------------------

    async def record(self, decision: PermissionDecision) -> str:
        """Append ``decision`` and return its id.

        **A decision carrying an ``OriginUnrecordedBinding`` is refused**
        (ADR-0184 §4, :func:`_revalidated`): that shape is only ever read out of a
        row written before ADR-0181 and never minted into one.

        Raises:
            AuditError: If the decision does not satisfy its own model, carries an
                ``OriginUnrecordedBinding``, or the
                database refuses the write. Pydantic's ``ValidationError`` is
                deliberately not allowed to escape: CONTRIBUTING has this layer
                raise only from the ``AssistantError`` hierarchy, and a caller
                handling "the trail would not accept this" should not need a
                second handler for the shape of the refusal.
            DuplicateDecisionError: If the id is already recorded.
            InvalidResolutionError: If ``resolves`` fails the ADR-0021 §1
                invariant.
        """
        snapshot = _revalidated(decision)
        async with self._lock:
            await _run_to_completion(self._record_sync, snapshot)
        return snapshot.id

    def _record_sync(self, snapshot: PermissionDecision) -> None:
        """Validate against what is stored and insert, as one transaction."""
        with self._transaction(f"record decision {snapshot.id!r}") as conn:
            if conn.execute("SELECT 1 FROM decisions WHERE id = ?", (snapshot.id,)).fetchone():
                msg = (
                    f"decision {snapshot.id!r} is already recorded; the trail is "
                    f"append-only, so history cannot be rewritten by replaying a write"
                )
                raise DuplicateDecisionError(msg)
            if conn.execute(
                "SELECT 1 FROM invocations WHERE id = ? LIMIT 1", (snapshot.id,)
            ).fetchone():
                # ADR-0192 §2: the write-once invariant binds the store from both
                # sides, over one id space and every row in it. Refused inside this
                # same atomic act, and as an ``AuditError`` rather than a
                # ``DuplicateDecisionError``: what is already present is not a
                # decision, so "re-recording a decision" is not what happened.
                msg = (
                    f"decision {snapshot.id!r} names a row the trail already holds as an "
                    f"invocation; one identifier names one record, of either kind"
                )
                raise AuditError(msg)
            if snapshot.resolves is not None:
                self._check_resolution(snapshot)
            conn.execute(
                "INSERT INTO decisions("
                "id, decided_at_us, resolves, execution_id, step_id, outcome, "
                "expires_at_us, data"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.id,
                    _sort_key(snapshot.decided_at),
                    snapshot.resolves,
                    snapshot.execution_id,
                    snapshot.step_id,
                    snapshot.ruling.outcome.value,
                    None if snapshot.expires_at is None else _sort_key(snapshot.expires_at),
                    snapshot.model_dump_json(),
                ),
            )

    def _check_resolution(self, decision: PermissionDecision) -> None:
        """Enforce ADR-0021 §1 and ADR-0044 §2's invariant on a resolving decision.

        **The referenced ``CONFIRM`` is read through :func:`_decode`, so since
        ADR-0184 a pre-ADR-0181 one is legible here rather than raising.** No clause
        is added for it and none is owed: ADR-0184 §4 states ``record``'s refusal
        over the **incoming** decision, and a resolution *of* such a row is closed
        one seam out rather than here. Nothing can build one — ``StepRunner.resume``
        narrows the recovered decision's binding and refuses before any ruling is
        sought (ADR-0184 §8's fourth clause), ``pending_confirmation`` never offers
        such a park at all, and ``ActionPolicy.resolve`` returns no ``ALLOW`` on one
        whatever the user answered (§7). What reaching this check would take is a
        caller hand-authoring a resolving decision, which is the boundary ADR-0018
        §3 drew for detachment: a caller falsifying its own trail, not a producer
        this store can catch.

        Raises:
            InvalidResolutionError: If the referenced decision is absent, was not
                a ``CONFIRM``, is already resolved, describes a different subject
                (including a different ``execution_id``, ADR-0044 §2a), postdates
                the answer, resolves a concrete binding a sibling already settled
                (ADR-0044 §2b), or if the authorisation pointer does not match.
        """
        row = self._conn.execute(
            "SELECT data FROM decisions WHERE id = ?", (str(decision.resolves),)
        ).fetchone()
        if row is None:
            msg = f"decision {decision.resolves!r} is not recorded, so nothing resolves it"
            raise InvalidResolutionError(msg)
        confirmed = _decode(row[0])
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {confirmed.id!r} ruled {confirmed.ruling.outcome}, not CONFIRM: "
                f"only a question the user was asked can be answered"
            )
            raise InvalidResolutionError(msg)
        if self._conn.execute(
            "SELECT 1 FROM decisions WHERE resolves = ?", (decision.resolves,)
        ).fetchone():
            msg = (
                f"decision {confirmed.id!r} is already resolved; a confirmation answered "
                f"repeatedly is one where a 'no' can be followed by a 'yes' until one sticks"
            )
            raise InvalidResolutionError(msg)
        if (
            confirmed.tool != decision.tool
            or confirmed.parameters_digest != decision.parameters_digest
            or confirmed.step_id != decision.step_id
            or confirmed.execution_id != decision.execution_id
        ):
            msg = (
                f"decision {decision.id!r} resolves {confirmed.id!r} but rules on a "
                f"different action; a confirmation must answer the question that was asked"
            )
            raise InvalidResolutionError(msg)
        self._check_binding_undecided(decision)
        if decision.decided_at < confirmed.decided_at:
            msg = (
                f"decision {decision.id!r} is timestamped before the confirmation "
                f"{confirmed.id!r} it answers"
            )
            raise InvalidResolutionError(msg)
        _check_authorisation(decision)

    def _check_binding_undecided(self, decision: PermissionDecision) -> None:
        """Refuse a resolution of a concrete binding a sibling already settled (§2b).

        Fires **only** when the resolving decision's ``execution_id`` and
        ``step_id`` are both present — a concrete ``(execution_id, step_id)``
        binding. ADR-0037 §2 accepts several unresolved ``CONFIRM``s under one
        binding (a compare-and-swap loser's ``CONFIRM`` stays recorded), and they
        are the same action, so they must share one fate: once *any* of them is
        resolved the binding is decided, and no second resolution — of that
        confirmation *or a sibling* — may be recorded. Layered on top of the
        per-confirmation ``resolves`` rule above, which alone would let a
        ``DENY``'d step keep an ``ALLOW``'d sibling orphan (the #257 window). The
        ``decisions_binding_resolution`` partial unique index is the durable
        safety net beneath this read; the read exists to give the friendlier
        error before the index raises a bare ``IntegrityError``.

        Raises:
            InvalidResolutionError: If a resolution for this concrete binding is
                already recorded.
        """
        if decision.execution_id is None or decision.step_id is None:
            return
        if self._conn.execute(
            _BINDING_HAS_RESOLUTION, (decision.execution_id, decision.step_id)
        ).fetchone():
            msg = (
                f"decision {decision.id!r} resolves the binding "
                f"({decision.execution_id!r}, {decision.step_id!r}), which is already "
                f"settled; one step of one execution has one answer"
            )
            raise InvalidResolutionError(msg)

    # --- the read path ----------------------------------------------------

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Return the decision with ``decision_id``, or ``None`` if absent.

        Raises:
            AuditError: If the trail cannot be read, or holds a record that no
                longer validates.
        """
        async with self._lock:
            row = await _run_to_completion(self._get_sync, decision_id)
        return None if row is None else _decode(row)

    def _get_sync(self, decision_id: str) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT data FROM decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        except sqlite3.Error as exc:
            msg = f"failed to read decision {decision_id!r}: {exc}"
            raise AuditError(msg) from exc
        return None if row is None else str(row[0])

    async def pending_confirmation(
        self, *, execution_id: str, step_id: str
    ) -> PermissionDecision | None:
        """The confirmation this binding still awaits, or ``None`` (ADR-0044 §3).

        Two steps in order: if the binding already carries a resolution it is
        decided, so return ``None`` (never a still-unresolved sibling orphan — the
        #257 hazard §2b closes); otherwise return the newest unresolved ``CONFIRM``
        by ``decided_at`` descending, ``id`` ascending, or ``None`` if the binding
        carries none. Query-only, returning a detached snapshot rebuilt from JSON.

        **A third way to answer ``None``: the ``CONFIRM`` is there and its origin
        was never recorded** (:data:`ORIGIN_UNRECORDED`). A row written before
        ADR-0181 §3 added ``planned_with_external_content`` decodes carrying an
        :class:`~ai_assistant.core.types.OriginUnrecordedBinding` (ADR-0184 §2), and
        such a call's origin cannot be established at all: §3 forbids a default and
        §4's second clause forbids a seam inventing one, which rules out ``False``
        and ``True`` alike. ADR-0181 §5's second clause then leaves no route by which
        any authorisation covers it — so there is no answerable question here to hand
        back, and this returns ``None`` rather than a decision.

        **What ADR-0184 changed here is only the detection.** The case is recognised
        on the decoded value's **type** rather than on the shape of a
        ``ValidationError``, which is strictly the stronger form of the same rule:
        the narrowness ``_is_origin_unrecorded`` maintained by hand — "a row with a
        second fault, a fault anywhere else, or a fault of any other type is a
        corrupted or downgraded database exactly as before" — is now carried by the
        type system, so no lane can widen the tolerance by loosening a predicate
        (ADR-0184 §1, §3, §5). The condition name a reader meets in the log is
        unchanged.

        **This is the one reader whose answer a caller rebuilds a park from** — the
        engine's recovery enumeration and the runner's restart path both reach a
        durably parked step through it — which is why the case is answered here and
        not in :func:`_decode`. Two things follow, and they are the whole reason the
        branch is worth having. One legacy row no longer takes **every** park down
        with it: the enumeration walks past it exactly as it walks past a decided
        binding, so every other pending confirmation is still offered. And no
        *false* card is composed, which is what handing back a decision would have
        cost: ADR-0150 §1 rules that ``None`` on a decision "means the request is not
        an egress call", so a decision projected without its binding would state that
        a call with an account and a recipient had neither.

        **Refused, not resolved, and never authorised.** Nothing is written, so the
        step stays durably ``AWAITING_APPROVAL`` with its ``CONFIRM`` unresolved and
        its row intact. The two callers refuse by their own existing names — the
        enumeration skips the step, and ``StepRunner._confirmation_for`` raises
        ``PermissionDeniedError`` — so under no route does such a park reach
        ``resolve``, an ``ALLOW`` or a transmission. The park is unanswerable, not
        erased; reclaiming one is the same open question a permanently unanswerable
        park already poses.

        **A reader that only reads answers differently, and the asymmetry is the
        distinction the design turns on** (ADR-0184 §5). :meth:`get`,
        :meth:`recent`, :meth:`export` and :meth:`resolution_of` now return such a
        row **as history**, carrying the account, the recipients and the payload
        description it actually holds. A park is a question put to the user and
        answering it composes a card they act on; a history read states what was
        recorded. There is no answerable question in an unanswerable park, so this
        hands back nothing — and there is a perfectly legible record behind it, so
        the readers hand it back.

        Raises:
            AuditError: If the trail cannot be read, or holds a row that no longer
                validates for any reason but the one above.
        """
        async with self._lock:
            data = await _run_to_completion(self._pending_confirmation_sync, execution_id, step_id)
        if data is None:
            return None
        park = _decode(data)
        if not isinstance(park.egress_binding, OriginUnrecordedBinding):
            return park
        _log.info(
            ORIGIN_UNRECORDED,
            execution_id=execution_id,
            step_id=step_id,
            refused="park",
        )
        return None

    def _pending_confirmation_sync(self, execution_id: str, step_id: str) -> str | None:
        conn = self._conn
        try:
            if conn.execute(_BINDING_HAS_RESOLUTION, (execution_id, step_id)).fetchone():
                return None
            row = conn.execute(
                _BINDING_CONFIRMS, (PermissionOutcome.CONFIRM.value, execution_id, step_id)
            ).fetchone()
        except sqlite3.Error as exc:
            msg = (
                f"failed to read the pending confirmation for "
                f"({execution_id!r}, {step_id!r}): {exc}"
            )
            raise AuditError(msg) from exc
        return None if row is None else str(row[0])

    async def resolution_of(self, *, execution_id: str, step_id: str) -> PermissionDecision | None:
        """The resolution recorded for this binding, or ``None`` (ADR-0059 §2).

        The complement of :meth:`pending_confirmation`: it returns the ALLOW or
        DENY whose ``resolves`` names a CONFIRM of the ``(execution_id, step_id)``
        binding, so a step stranded ``AWAITING_APPROVAL`` with its ruling durable
        but its transition uncommitted (#257) can be driven to the disposition
        already decided. ``None`` means the binding carries no resolution — never a
        read failure, which is raised. Query-only, returning a detached snapshot
        rebuilt from JSON; always an ALLOW or DENY, since a resolving CONFIRM is
        unconstructable.

        **The decoded blob is authoritative, not the projection columns.** The
        ``resolves``, ``execution_id`` and ``step_id`` columns are only the fast
        filter :meth:`_record_sync` maintains; the SQL narrows by all three, but
        the returned decision's *own* fields are then re-checked against them. A
        row whose ``resolves`` projection was tampered non-``NULL`` (a pending
        ``CONFIRM`` or a direct decision masquerading as a resolution), or whose
        binding projection names a binding its blob does not, is a corrupt store —
        reported rather than mis-routed as this binding's ruling. Load-bearing
        here because the recovery this feeds *acts* on the ruling, and because the
        ALLOW-or-DENY guarantee rests on the blob's ``resolves`` (by
        ``_a_resolution_is_not_itself_a_question`` a decision that resolves is
        never a ``CONFIRM``), not on the column the SQL selected by.

        Raises:
            AuditError: If the trail cannot be read, holds a resolution that no
                longer validates, or holds a row whose stored ``resolves`` or
                binding disagrees with the projection it was found by.
        """
        async with self._lock:
            data = await _run_to_completion(self._resolution_of_sync, execution_id, step_id)
        if data is None:
            return None
        resolution = _decode(data)
        if resolution.resolves is None:
            msg = (
                f"the audit trail holds a row found as the resolution of "
                f"({execution_id!r}, {step_id!r}) whose record resolves nothing; its "
                f"resolves projection was tampered"
            )
            raise AuditError(msg)
        if resolution.execution_id != execution_id or resolution.step_id != step_id:
            msg = (
                f"the audit trail holds a resolution whose stored binding "
                f"({resolution.execution_id!r}, {resolution.step_id!r}) disagrees with the "
                f"projection it was found by ({execution_id!r}, {step_id!r})"
            )
            raise AuditError(msg)
        return resolution

    def _resolution_of_sync(self, execution_id: str, step_id: str) -> str | None:
        try:
            row = self._conn.execute(_BINDING_RESOLUTION, (execution_id, step_id)).fetchone()
        except sqlite3.Error as exc:
            msg = f"failed to read the resolution for ({execution_id!r}, {step_id!r}): {exc}"
            raise AuditError(msg) from exc
        return None if row is None else str(row[0])

    async def recent(self, *, limit: int = 50) -> list[PermissionDecision]:
        """Return up to ``limit`` decisions, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive. Refused rather
                than clamped or passed through: SQLite reads ``LIMIT -1`` as *no
                limit at all*, so the one call offering a bounded read of a
                Tier 1 store would become the unbounded read it exists to avoid.
            AuditError: If the trail cannot be read.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        # Clamped *upward* only. A Python int has no width, and binding one
        # wider than SQLite's signed 64-bit parameter raises `OverflowError` —
        # neither `ValueError` nor `AuditError`, so it would leave this layer's
        # error boundary through a hole. Clamping serves what was asked for: a
        # bound above any possible row count means "all of them", which is what
        # the query then returns. This is not the `limit=-1` case, where
        # clamping would have served something the caller did not ask for.
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, min(limit, _MAX_SQLITE_INT))
        return [_decode(row) for row in rows]

    async def export(self) -> list[PermissionDecision]:
        """Return every recorded decision, in the same order as :meth:`recent`.

        Raises:
            AuditError: If the trail cannot be read.
        """
        async with self._lock:
            rows = await _run_to_completion(self._ordered_sync, None)
        return [_decode(row) for row in rows]

    def _ordered_sync(self, limit: int | None) -> Sequence[str]:
        """Read decisions newest-first, optionally bounded.

        Two static statements rather than one interpolated ``LIMIT``: the bound
        is the whole point of ``recent``, and a query assembled from a variable
        is how it stops being one.
        """
        try:
            rows = (
                self._conn.execute(_ORDERED).fetchall()
                if limit is None
                else self._conn.execute(f"{_ORDERED} LIMIT ?", (limit,)).fetchall()
            )
        except sqlite3.Error as exc:
            msg = f"failed to read the audit trail: {exc}"
            raise AuditError(msg) from exc
        return [str(row[0]) for row in rows]

    # --- the ledger: the consume, and the two appends (ADR-0192 §§1-2) ----

    async def claim_invocation(self, *, decision: PermissionDecision) -> ToolInvocation:
        """Append a claim under ``decision`` and return the stored row.

        The revalidation runs **before the lock**, so the decision is observed
        once, before this call's first suspension point (ADR-0065): an
        implementation that validated, suspended and then re-read the caller's
        object could admit a claim under a decision that was spent when it looked.

        Raises:
            AuditError: If the decision is not a valid record, the guard rejects
                the clock's reading, the redraw bound is spent, or the store
                cannot be read or written.
            UnrecordedAuthorisationError: If the trail holds no decision under
                that id, holds one that is not equal to it, or holds one whose
                ruling is not ``ALLOW``.
            AuthorisationSpentError: If ADR-0192 §1's consume refuses.
        """
        snapshot = _revalidated(decision)
        async with self._lock:
            data = await _run_to_completion(self._claim_sync, snapshot)
        return _decode_invocation(data)

    def _claim_sync(self, snapshot: PermissionDecision) -> str:
        """Decide every refusal and append, as one transaction.

        The order is ADR-0192 §2's and no other: the argument fault is already
        past (:func:`_revalidated`), then the unrecorded authorisation, then the
        spend. The clock is read **after** the authority is established and
        **once** — that one reading is both what the admission is decided on and
        what the row stores, so a retry cannot be admitted inside the window and
        stamped outside it.

        **And it is read only where the answer needs it.** Every arm of §1's
        conjunction but the window is decided over the store's own history, so
        reading the clock in front of them lets a clock that raises stand in for a
        refusal that was already settled: §1 says a claim refused because the
        authorisation is spent raises ``AuthorisationSpentError``, and a collaborator
        the ledger did not have to consult must not turn that into some other class
        — one that, by ADR-0026 §2, is not even the ledger's to translate and leaves
        unwrapped. :func:`_once` reads on first ask and never again, so "exactly one
        guarded reading per append" is unchanged and so is the rule that the instant
        decided on is the instant stored.
        """
        with self._transaction(f"claim an invocation under decision {snapshot.id!r}") as conn:
            row = conn.execute("SELECT data FROM decisions WHERE id = ?", (snapshot.id,)).fetchone()
            if row is None or _decode(row[0]) != snapshot:
                # One class for both grounds, and for the ruling below: they are
                # all "the authority this call claims is not one this store
                # recorded", and separating them would tell a caller which half of
                # a forgery was detected (ADR-0192 §2).
                msg = (
                    f"the trail records no decision equal to {snapshot.id!r}; an "
                    f"authorisation it did not record authorises nothing"
                )
                raise UnrecordedAuthorisationError(msg)
            if snapshot.ruling.outcome is not PermissionOutcome.ALLOW:
                msg = (
                    f"the trail records no decision equal to {snapshot.id!r}; an "
                    f"authorisation it did not record authorises nothing"
                )
                raise UnrecordedAuthorisationError(msg)
            reading = _once(self._reading)
            self._refuse_if_spent(conn, snapshot, reading)
            claim = ToolInvocation(
                id=self._mint(conn),
                decision_id=snapshot.id,
                recorded_at=reading(),
            )
            self._append(conn, claim)
            return claim.model_dump_json()

    async def complete_invocation(
        self,
        *,
        claim_id: DurableIdentifier,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None = None,
    ) -> ToolInvocation:
        """Append the completion of ``claim_id`` and return the stored row.

        Every argument is validated and detached **before the lock**, for
        ADR-0065's reason and for ADR-0021 §4's: ``incurred_cost`` is the live
        object at the end of the chain that clause names, so a store retaining it
        would let ``cost.__dict__["amount"] = ...`` rewrite an appended row.

        Raises:
            AuditError: If an argument is not valid — a ``failure_kind`` with a
                ``SUCCEEDED`` outcome among them — the guard rejects the clock's
                reading, the redraw bound is spent, or the store cannot be read or
                written.
            InvalidCompletionError: If ``claim_id`` names no recorded claim or
                names one a completion already names.
        """
        named = _checked_argument("claim_id", lambda: _IDENTIFIER.validate_python(claim_id))
        settled = _checked_argument("outcome", lambda: ToolOutcome(outcome))
        cost = _checked_argument("incurred_cost", lambda: _detached_cost(incurred_cost))
        kind = (
            None
            if failure_kind is None
            else _checked_argument("failure_kind", lambda: ToolFailureKind(failure_kind))
        )
        if kind is not None and settled is ToolOutcome.SUCCEEDED:
            msg = "a SUCCEEDED completion carries no failure_kind"
            raise AuditError(msg)
        async with self._lock:
            data = await _run_to_completion(self._complete_sync, named, settled, cost, kind)
        return _decode_invocation(data)

    def _complete_sync(
        self,
        claim_id: str,
        outcome: ToolOutcome,
        incurred_cost: ToolCost,
        failure_kind: ToolFailureKind | None,
    ) -> str:
        """Check the claim and append the completion, as one transaction."""
        with self._transaction(f"complete the invocation claimed as {claim_id!r}") as conn:
            row = conn.execute(_OPEN_CLAIM, (claim_id,)).fetchone()
            if row is None:
                msg = f"the trail holds no open claim {claim_id!r} to complete"
                raise InvalidCompletionError(msg)
            claim = _as_projected(row)
            if conn.execute(
                "SELECT 1 FROM invocations WHERE completes = ? LIMIT 1", (claim_id,)
            ).fetchone():
                msg = (
                    f"claim {claim_id!r} is already completed; the trail is append-only, "
                    f"so an outcome cannot be written twice"
                )
                raise InvalidCompletionError(msg)
            completion = ToolInvocation(
                id=self._mint(conn),
                # Set from the claim and never accepted from a caller, so the two
                # cannot disagree (ADR-0192 §2).
                decision_id=claim.decision_id,
                recorded_at=self._reading(),
                completes=claim.id,
                outcome=outcome,
                incurred_cost=incurred_cost,
                failure_kind=failure_kind,
            )
            self._append(conn, completion)
            return completion.model_dump_json()

    def _reading(self) -> datetime:
        """Take the append's one guarded clock reading.

        ADR-0026 §2's split is drawn here and nowhere else: the guard's **own**
        rejection is a ``ClockReadingError``, a ``ValueError`` and not an
        ``AssistantError``, so it is translated — a caller never meets a
        non-``AssistantError`` this store produced. An exception the clock
        **callable itself** raises propagates unwrapped, its type and cause
        intact, because relabelling it would destroy exactly what that rule
        preserves.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the audit trail's clock returned a reading it cannot record: {exc}"
            raise AuditError(msg) from exc

    def _mint(self, conn: sqlite3.Connection) -> str:
        """Draw an identifier no row currently holds, or refuse (ADR-0192 §2).

        **A collision is drawn away from rather than refused.** The store holds
        each id once, so a colliding id cannot be appended — but a collision is not
        by itself evidence of a broken collaborator, and the append that meets one
        is not thereby doomed. What that buys is the case a refusing implementation
        deadlocks on: after a restart the store holds claims a *new*, conforming,
        process-scoped factory may legally mint over, and a store refusing the
        first collision would fail there and on every subsequent restart.

        Only an **exhausted** bound is a refusal, and it is an ``AuditError`` and
        never one of §1's three named classes: those are statements about the
        authorisation and say nothing about the store.
        """
        held = int(conn.execute(_ROWS_HELD).fetchone()[0])
        for _ in range(held + 1):
            # Outside the guard below: an exception the factory callable raises on
            # its own account is its own failure and propagates unwrapped
            # (ADR-0026 §2), exactly as the clock callable's does.
            drawn = self._identifiers()
            candidate: str = _checked_argument(
                "identifier", functools.partial(_IDENTIFIER.validate_python, drawn)
            )
            if not conn.execute(_ID_IS_HELD, (candidate, candidate)).fetchone():
                return candidate
        msg = (
            f"the audit trail's identifier factory returned an identifier the store "
            f"already holds on every one of {held + 1} draws; no row was appended"
        )
        raise AuditError(msg)

    @staticmethod
    def _append(conn: sqlite3.Connection, row: ToolInvocation) -> None:
        """Insert ``row``, allocating the next durable append ordinal for it."""
        next_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM invocations").fetchone()
        ordinal = int(next_seq[0])
        # Only the three columns that are not derived from the blob are supplied;
        # SQLite computes the other four from `data` and refuses to be told them.
        conn.execute(
            "INSERT INTO invocations(seq, recorded_at_us, data) VALUES (?, ?, ?)",
            (ordinal, _sort_key(row.recorded_at), row.model_dump_json()),
        )

    @staticmethod
    def _refuse_if_spent(
        conn: sqlite3.Connection, decision: PermissionDecision, now: Callable[[], datetime]
    ) -> None:
        """Apply ADR-0192 §1's conjunction to the claims already under ``decision``.

        **Spendability is ADR-0029 §5's own discriminator**: side-effecting and not
        ``NATURAL``. On anything else no claim is ever refused on this ground — a
        read gated by ADR-0016 §3 is invoked under one ``ALLOW`` as often as the
        pipeline needs it, and refusing the second read would break working
        behaviour to protect nothing.

        ``now`` is a **callable** and is invoked in the window arm alone, which is
        the only arm an instant decides. Every arm above it is a statement about the
        store's history, and taking a reading to answer them would let a clock that
        raises replace a refusal §1 names with an exception it does not.

        Raises:
            AuthorisationSpentError: If a further claim is not admitted.
        """
        spendable = decision.tool.side_effecting and decision.tool.idempotency is not (
            Idempotency.NATURAL
        )
        if not spendable:
            return
        claims = [_as_projected(row) for row in conn.execute(_CLAIMS_UNDER, (decision.id,))]
        if not claims:
            return
        completions = {
            completion.completes: completion
            for completion in (
                _as_projected(row) for row in conn.execute(_COMPLETIONS_UNDER, (decision.id,))
            )
        }
        _refuse = _spend_refusal(decision.id)
        if any(claim.id not in completions for claim in claims):
            # Stated positively rather than composed out of the conjunction: an
            # open claim is an act that may have run at an outcome nobody
            # observed, and admitting a second act under the same authorisation is
            # the one thing this rule exists to prevent. It is why completion
            # durability is a third prerequisite for ADR-0029 §5's retry.
            raise _refuse("a claim under it is open")
        settled = {completions[claim.id].outcome for claim in claims}
        if settled & {ToolOutcome.SUCCEEDED, ToolOutcome.INDETERMINATE}:
            raise _refuse("an act under it has already succeeded or may have")
        last = completions[claims[-1].id]
        if last.outcome is not ToolOutcome.FAILED:
            raise _refuse("its last act did not fail")
        if last.failure_kind is None or not last.failure_kind.retryable:
            # A kindless FAILED admits nothing: a cancelled act is not
            # auto-retried, which falls out of the rule rather than needing a
            # clause of its own (ADR-0192 §2).
            raise _refuse("its last failure reported no retryable kind")
        if decision.tool.idempotency is not Idempotency.KEYED:
            # ADR-0029 §5's "an ``Idempotency.NONE`` side-effecting tool is
            # therefore **never** auto-retried, whatever the failure kind", made a
            # property of the store.
            raise _refuse("the tool offers no keyed idempotency")
        window = decision.tool.idempotency_window
        elapsed = now() - claims[0].recorded_at
        if window is None or elapsed <= timedelta(0) or elapsed >= window:
            # Measured from the **first** claim in the append order and never from
            # the last: measuring from the most recent one would renew the window
            # indefinitely, one retryable failure at a time. Any reading that is
            # not a positive duration is treated as the window having lapsed —
            # ADR-0029 §5's fail-closed rule for the same measurement.
            raise _refuse("its idempotency window has lapsed")

    # --- reading what ran (ADR-0192 §2) -----------------------------------

    async def recent_invocations(self, *, limit: int = 50) -> list[RecordedInvocation]:
        """Return up to ``limit`` invocation rows, newest first, ties broken by id.

        Raises:
            ValueError: If ``limit`` is not strictly positive — ``recent``'s own
                refusal, for ``recent``'s own reason.
            AuditError: If the trail cannot be read, or holds an invocation row it
                could not pair with a decision.
        """
        if limit <= 0:
            msg = f"limit must be strictly positive, got {limit}"
            raise ValueError(msg)
        async with self._lock:
            rows = await _run_to_completion(self._joined_sync, min(limit, _MAX_SQLITE_INT))
        return [_join(invocation, decision) for invocation, decision in rows]

    async def export_invocations(self) -> list[RecordedInvocation]:
        """Return every invocation row, in the same order as :meth:`recent_invocations`.

        Raises:
            AuditError: If the trail cannot be read, or holds an invocation row it
                could not pair with a decision.
        """
        async with self._lock:
            rows = await _run_to_completion(self._joined_sync, None)
        return [_join(invocation, decision) for invocation, decision in rows]

    def _joined_sync(self, limit: int | None) -> Sequence[tuple[ToolInvocation, str | None]]:
        """Read rows and their decisions in **one** statement, optionally bounded.

        One operation is what makes the join safe: an implementation reading rows
        and then reading decisions has an ``await`` between them, and a
        :meth:`clear` landing in that gap leaves it holding rows whose decisions
        are gone — with nothing to do but drop them, fabricate the identifiers, or
        fail, all three of which contradict a total projection.
        """
        try:
            rows = (
                self._conn.execute(_JOINED_INVOCATIONS).fetchall()
                if limit is None
                else self._conn.execute(f"{_JOINED_INVOCATIONS} LIMIT ?", (limit,)).fetchall()
            )
        except sqlite3.Error as exc:
            msg = f"failed to read the audit trail's invocations: {exc}"
            raise AuditError(msg) from exc
        # Decoded and held to its projection here, inside the connection's turn:
        # the check belongs to the read, and a row is never handed out of this
        # method unvalidated.
        return [
            (_as_projected(row[:-1]), None if row[-1] is None else str(row[-1])) for row in rows
        ]

    async def open_invocations(self, *, decision_id: DurableIdentifier) -> list[ToolInvocation]:
        """Every claim under ``decision_id`` that no completion names, in append order.

        Raises:
            AuditError: If the trail cannot be read.
        """
        async with self._lock:
            return list(await _run_to_completion(self._open_invocations_sync, decision_id))

    def _open_invocations_sync(self, decision_id: str) -> Sequence[ToolInvocation]:
        """Read the open claims and reserve their ids, as **one** operation.

        The transaction is ``IMMEDIATE`` although this reads: the reservation joins
        the read on the same serialisation boundary ``clear()`` and every append
        take, never following it. An implementation that read the set, released the
        boundary and reserved afterwards satisfies "reserves every claim id it
        returns" as a sentence and loses the race the rule exists to close — an
        erasure and a fresh claim can land in the gap, and the id it then reserves
        names the **new** claim (ADR-0192 §2).
        """
        with self._transaction(f"read the open invocations under {decision_id!r}") as conn:
            # Reserved by the id the *record* carries, never by the column it was
            # found by: reserving a projected id a blob does not name would leave
            # the row's real id free for the factory to mint over.
            claims = [_as_projected(row) for row in conn.execute(_OPEN_UNDER, (decision_id,))]
            self._identifiers.reserve([claim.id for claim in claims])
            return claims

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every row of either kind, returning the number removed.

        Wholesale by design (ADR-0021 §4): the user may burn the book, and
        nobody may tear out a page. **Both kinds, and the count is over both**
        (ADR-0192 §6) — two erasure acts over one store would let a user destroy
        the executions and keep the rulings, which is selective erasure with an
        extra step.

        **It erases the consume with everything else.** No generation, epoch,
        tombstone or high-water mark is minted to narrow that: any value that let a
        post-erasure claim be judged against a pre-erasure one would be a second,
        undeletable record of an act the user asked to have erased.

        Raises:
            AuditError: If the trail cannot be cleared.
        """
        async with self._lock:
            return await _run_to_completion(self._clear_sync)

    def _clear_sync(self) -> int:
        """Delete everything in one statement, counting what the delete removed.

        The count comes from the ``DELETE`` itself rather than from a ``SELECT
        COUNT(*)`` in front of it. A separate count is read before SQLite opens
        the write transaction, so a second trail on the same file could append
        between the two and be erased without being counted — and each instance
        has its own ``asyncio.Lock``, which arbitrates nothing across them. One
        statement makes the number exact by construction rather than by
        transaction discipline.

        Only ``decisions`` is emptied: the ``meta`` schema marker describes the
        file's shape rather than the user's history, so burning the book leaves a
        database this code can still open (and would still count as version 1).
        """
        with self._transaction("clear the audit trail") as conn:
            # Invocations first: a decision whose invocation rows outlived it
            # would be an unjoinable row for however long the two statements are
            # apart, and one transaction makes the order invisible either way.
            removed = conn.execute("DELETE FROM invocations").rowcount
            removed += conn.execute("DELETE FROM decisions").rowcount
        return int(removed)

    def close(self) -> None:
        """Close the underlying database connection."""
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()


def _revalidated(decision: PermissionDecision) -> PermissionDecision:
    """Rebuild ``decision`` as a validated :class:`PermissionDecision`.

    ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one. A
    copy alone detaches without checking, so a decision corrupted past its frozen
    model's guard — a ``decided_at`` written back as naive is the sharp case —
    would be stored and then make every later ordered read incoherent.

    Rebuilt as a ``PermissionDecision`` specifically, not as ``type(decision)``:
    a caller's subclass could carry extra fields, and ``extra="forbid"`` refuses
    them here rather than letting them vanish at serialisation and make the
    stored record differ from the one that reloads.

    **An ``OriginUnrecordedBinding`` is refused here** (ADR-0184 §4), and it is the
    one refusal the model cannot make for itself: that shape is a *valid*
    ``PermissionDecision``, because it has to be for a stored row to decode into
    one. It represents a row from an epoch that has ended, so it is only ever read
    out of a store and never minted into one — a caller bypassing ``from_request``
    could otherwise construct such a decision and append it, fabricating history
    rather than a value. ``record`` is where the trail already enforces what a model
    cannot see for itself (ADR-0021 §4), and this is one more clause of that kind.

    **The refusal is judged on the rebuilt snapshot, not on what the caller handed
    over, and the order is load-bearing.** ``model_copy(update=...)`` does **not**
    validate, so a caller can put a bare mapping into ``egress_binding``; an
    ``isinstance`` check in front of the rebuild sees a ``dict``, answers ``False``,
    and the rebuild then turns that mapping into exactly the shape the check was
    meant to stop — appended as a genuine-looking row from an epoch that has ended.
    Checking what will actually be stored closes every route into the shape at once
    rather than the one a caller took, which is the same reason ADR-0021 §4 asks for
    a *validated* snapshot rather than a copied one.

    **A raw, non-model value is handed to ``model_validate`` rather than
    dereferenced**, which is ``FakeToolInvoker._revalidated``'s ordering (ADR-0152
    §1, "before reading any field of it") applied to this argument.
    ``model_dump()`` is a field read, so calling it first would let such a value
    escape as an ``AttributeError``. ADR-0192 §2's refusal order puts
    ``AuditError`` first "where an argument is not valid" and is exhaustive over
    the classes a refusal arrives in, so the ``AttributeError`` would leave through
    a hole in it. ``record`` reaches this helper too and gains the same guard.

    Raises:
        AuditError: If the value is not a valid record at all, does not satisfy the
            model, or rebuilds carrying an ``OriginUnrecordedBinding``.
    """
    given: object = decision
    try:
        raw = given.model_dump() if isinstance(given, PermissionDecision) else given
        snapshot = PermissionDecision.model_validate(raw)
    except ValidationError as exc:
        named = repr(given.id) if isinstance(given, PermissionDecision) else "the given value"
        msg = f"decision {named} is not a valid record: {exc}"
        raise AuditError(msg) from exc
    if isinstance(snapshot.egress_binding, OriginUnrecordedBinding):
        msg = (
            f"decision {decision.id!r} is not a valid record: its egress binding "
            f"records no origin, which is a shape only a row written before "
            f"ADR-0181 can have; the trail reads such rows and never writes one"
        )
        raise AuditError(msg)
    return snapshot


def _detached_cost(value: ToolCost) -> ToolCost:
    """Rebuild ``value`` as a validated, detached :class:`ToolCost`.

    A raw, non-model value is validated rather than dereferenced, on
    :func:`_revalidated`'s ordering and for its reason: ``value.model_dump_json()``
    on something that is not a cost raises ``AttributeError``, which is neither
    ``AuditError`` nor any class ADR-0192 §2's refusal order admits.

    The round trip through JSON is then the detachment ADR-0021 §4 asks for —
    ``incurred_cost`` is the live object at the end of the chain that clause names,
    so a store retaining it would let ``cost.__dict__["amount"] = ...`` rewrite an
    appended row.

    Raises:
        ValidationError: If it is not a cost this store can record.
    """
    given: object = value
    checked = ToolCost.model_validate(given.model_dump() if isinstance(given, ToolCost) else given)
    return ToolCost.model_validate_json(checked.model_dump_json())


def _decode(data: str) -> PermissionDecision:
    """Rebuild a stored decision from its JSON.

    **A row recorded before ADR-0181 §3's ``planned_with_external_content`` decodes
    rather than raising** (ADR-0184 §2, §5), carrying an
    :class:`~ai_assistant.core.types.OriginUnrecordedBinding` in place of an
    ``EgressBinding``. Nothing here recognises it: the discrimination is structural,
    done by the union on :attr:`PermissionDecision.egress_binding` and by
    ``extra="forbid"`` on both models, so there is no predicate to widen and no
    branch to take. The tolerance is exactly one shape wide — a row that is *also*
    faulty elsewhere satisfies neither arm of the union and still raises below,
    which is what the retired ``_is_origin_unrecorded`` bought with a hand-written
    check over ``exc.errors()``.

    Nothing is written back for such a row and nothing is fabricated on the way out:
    the model carries no ``planned_with_external_content`` member, so a
    ``model_dump`` of what this returns emits no key for it and an ``export`` is a
    faithful copy of what the row says (ADR-0184 §4).

    Raises:
        AuditError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record to
            hand on. Every unreadable row but the one shape above is reported here
            exactly as it was before.
    """
    try:
        return PermissionDecision.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the audit trail holds a record that no longer validates: {exc}"
        raise AuditError(msg) from exc


def _decode_invocation(data: str) -> ToolInvocation:
    """Rebuild a stored invocation row from its JSON.

    Serialising and rebuilding is how ADR-0021 §4's "detached, validated snapshot"
    is obtained here without a copy step to forget, on this row kind as on the
    other: every reachable value is rebuilt, so no object graph is shared with the
    caller in either direction — the ``ToolCost`` a completion carries included.

    Raises:
        AuditError: If the stored row no longer validates.
    """
    try:
        return ToolInvocation.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the audit trail holds an invocation row that no longer validates: {exc}"
        raise AuditError(msg) from exc


def _as_projected(row: Sequence[Any]) -> ToolInvocation:
    """Decode an invocation row and refuse one its own columns misdescribe.

    ``row`` is ``(data, id, decision_id, recorded_at_us, completes, outcome)`` —
    the blob followed by the projection columns, which every invocation read
    selects in that order.

    **The decoded blob is authoritative, not the columns**, exactly as it is for a
    decision found by its binding (:meth:`SqliteAuditTrail.resolution_of`). Four of
    the five are `GENERATED ALWAYS` over ``data`` (:data:`_CREATE_INVOCATIONS`), so
    for those the comparison is structurally true rather than a check — it is kept
    because it costs a tuple compare and because a future edit that un-derives one
    would otherwise pass silently, and it is not what makes them trustworthy.

    ``recorded_at_us`` is the one that is genuinely a second copy: it is
    `_sort_key`'s integer microseconds and cannot be derived from the ISO-8601 text
    the blob holds, which does not sort as an instant. It decides no admission — it
    decides the order a listing is served in — and serving a row in the order some
    other instant would put it in is the trail misreporting, which is what this
    refuses.

    **What no comparison closes.** ``seq`` is the durable append order, allocated at
    insert and absent from the record, so nothing here can hold it to anything; and
    an edit that rewrites ``data`` itself moves the derived columns with it, which
    is a rewritten record rather than a disagreeing copy. Both are issue #1574.

    Raises:
        AuditError: If the stored row no longer validates, or if any projected
            column disagrees with the record it is supposed to describe.
    """
    invocation = _decode_invocation(str(row[0]))
    recorded = (
        invocation.id,
        invocation.decision_id,
        _sort_key(invocation.recorded_at),
        invocation.completes,
        None if invocation.outcome is None else invocation.outcome.value,
    )
    projected = tuple(row[1:])
    if recorded != projected:
        msg = (
            f"the audit trail holds an invocation whose record {recorded!r} disagrees "
            f"with the projection it was found by {projected!r}; the store is corrupt"
        )
        raise AuditError(msg)
    return invocation


def _join(invocation: ToolInvocation, decision: str | None) -> RecordedInvocation:
    """Pair a stored row with the decision it names (ADR-0192 §2).

    Raises:
        AuditError: If the decision is absent, or is not the one the row names —
            a row the store could not pair, which is a corrupt trail and reported
            rather than silently dropped.
    """
    if decision is None:
        msg = (
            f"the audit trail holds invocation {invocation.id!r} naming decision "
            f"{invocation.decision_id!r}, which it does not hold; the store is corrupt"
        )
        raise AuditError(msg)
    named = _decode(decision)
    if named.id != invocation.decision_id:
        # The join matched `d.id` against `i.decision_id`, both columns; this holds
        # the pairing to the two *records*. Without it a tampered `decisions.id`
        # column attributes an act to an authorisation that never covered it, which
        # is precisely the misreport ADR-0021 §5's disclosure floor is about.
        msg = (
            f"the audit trail paired invocation {invocation.id!r}, which names decision "
            f"{invocation.decision_id!r}, with a record of decision {named.id!r}; "
            f"the store is corrupt"
        )
        raise AuditError(msg)
    return RecordedInvocation(
        invocation=invocation,
        tool=named.tool.id,
        capability=named.tool.capability,
        egress_call=named.egress_binding is not None,
    )


def _once[T](read: Callable[[], T]) -> Callable[[], T]:
    """Wrap ``read`` so it runs on the first ask and hands back that value after.

    The clock's "exactly one guarded reading per append" (ADR-0192 §1) written as a
    property of the reading rather than of the call graph, so the reading can be
    deferred past every refusal that does not need it and still be one reading.
    """
    taken: list[T] = []

    def _read() -> T:
        if not taken:
            taken.append(read())
        return taken[0]

    return _read


def _checked_argument[T](name: str, build: Callable[[], T]) -> T:
    """Run ``build``, reporting a rejected value as this layer's own error.

    The guard-rejection arm of ADR-0026 §2, applied to every value a ledger member
    is handed or a collaborator returns: a non-conforming *output* is translated,
    while an exception a collaborator's callable raises on its own account is not
    routed through here at all.

    Raises:
        AuditError: If ``build`` rejects the value.
    """
    try:
        return build()
    except (ValidationError, ValueError) as exc:
        msg = f"the audit trail was given a {name} it cannot record: {exc}"
        raise AuditError(msg) from exc


def _spend_refusal(decision_id: str) -> Callable[[str], AuthorisationSpentError]:
    """Build this decision's refusal, so every arm reads the same but for its cause."""

    def _refuse(because: str) -> AuthorisationSpentError:
        return AuthorisationSpentError(
            f"the authorisation recorded as {decision_id!r} is spent: {because}"
        )

    return _refuse


def _check_authorisation(decision: PermissionDecision) -> None:
    """Require a resolving ALLOW to cite its own ``resolves``, and a DENY none.

    Without this the pointer is a string a policy could invent, and ADR-0021
    §5's disclosure floor would be satisfiable by fabrication.

    Raises:
        InvalidResolutionError: If the pointer does not match the outcome.
    """
    authorised_by = decision.ruling.authorised_by
    if decision.ruling.outcome is PermissionOutcome.ALLOW:
        if authorised_by != decision.resolves:
            msg = (
                f"a resolving ALLOW must rest on the confirmation it answers: "
                f"authorised_by={authorised_by!r}, resolves={decision.resolves!r}"
            )
            raise InvalidResolutionError(msg)
    elif authorised_by is not None:
        # Not reachable through `record`, which revalidates first and so meets
        # `PermissionRuling`'s own rule that the field is settable only on an
        # ALLOW. Kept because the trail must not depend on another type's
        # invariant to hold a safety rule of its own.
        msg = f"a resolving {decision.ruling.outcome} rests on no authorisation"
        raise InvalidResolutionError(msg)


__all__ = ["SqliteAuditTrail"]
