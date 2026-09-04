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
from typing import TYPE_CHECKING, Any, Final, final
from uuid import uuid4

import structlog
from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    DuplicateDecisionError,
    InvalidAuthorisationError,
    InvalidCompletionError,
    InvalidResolutionError,
    RecipientGrantError,
    SpendCeilingError,
    SpendUndeterminedError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    CoverageUnrecordedBinding,
    DurableIdentifier,
    EgressBinding,
    Idempotency,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    RecordedInvocation,
    SpendAdmissionHandle,
    SpendPeriod,
    SpendTotal,
    ToolCost,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
    describe_untrusted,
)
from ai_assistant.permissions._detachment import field_state
from ai_assistant.permissions._transactions import transaction
from ai_assistant.permissions.identifiers import IdentifierFactory, ProcessIdentifiers
from ai_assistant.permissions.spend import (
    DeclaredFault,
    PeriodBounds,
    Reservations,
    SpendArithmeticError,
    SpendConfiguration,
    declared_contribution,
    exact_projection,
    exact_sum,
    period_bounds,
    reported_contribution,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from contextlib import AbstractContextManager
    from decimal import Decimal

    from ai_assistant.core.protocols import RecipientGrantResolution
    from ai_assistant.core.types import RecipientGrant

_log = structlog.get_logger(__name__)

#: The named condition a park is refused under when the row it would be rebuilt
#: from predates ADR-0181's ``planned_with_external_content``. In the corpus's
#: condition style — ``hub-unreachable``, ``no-live-session`` — and a module
#: constant rather than a literal so a test asserts the *name* a reader will meet
#: in the log rather than a spelling of it.
ORIGIN_UNRECORDED = "origin-unrecorded"

#: The named condition a park is refused under when the row it would be rebuilt from
#: predates ADR-0233's ``coverage``. Its **own** name rather than a reuse of the one
#: above (ADR-0233 §14), for that constant's reason: a reader meeting it in the log
#: learns which fact the row is missing, and the two epochs are different epochs.
COVERAGE_UNRECORDED = "coverage-unrecorded"

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

    **The completion wait is submitted at most once** (#697). Absorbing a
    cancellation hands the loop a blocking ``done.wait`` job on the default
    executor; a copy that submits a fresh one per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it. Repeated cancellation of one blocked call then
    occupies the whole pool, which turns one stalled store operation into a process
    that cannot run any thread work at all. Reusing the future costs a local and
    bounds the helper at two executor jobs however many cancellations arrive.
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


#: The widest value SQLite will bind to an INTEGER parameter. A Python int is
#: unbounded, so ``recent`` clamps to this before binding ``LIMIT``.
_MAX_SQLITE_INT = 2**63 - 1

#: The other end of the same range. Only the append ordinal can reach it — nothing
#: this store computes goes negative, but that ordinal is derived from a column a
#: writer of the *file* can put anything in, and the bound is a property of what
#: SQLite will bind rather than of which direction a value drifted.
_MIN_SQLITE_INT = -(2**63)

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

#: **Every index this store defines over ``decisions``, held to its own definition**
#: at open (:meth:`SqliteAuditTrail._check_decisions_schema`), exactly as
#: :data:`_INVOCATION_OBJECTS` holds the invocation objects and for the same reason:
#: ``CREATE ... IF NOT EXISTS`` is a no-op against an object already there under
#: that name *whatever it is*. A file arriving with a non-unique
#: ``decisions_resolves`` keeps it, and one confirmation can then carry two
#: resolutions (ADR-0036 §2); one arriving with a ``decisions_binding_resolution``
#: whose ``WHERE`` matches nothing keeps that, and the per-binding net beneath the
#: checked read in :meth:`SqliteAuditTrail._check_binding_undecided` is gone
#: (ADR-0044 §2b).
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds
#: is compared against these very statements rather than a second copy written out
#: by hand — and comparing the text is what reaches a partial index's ``WHERE`` at
#: all, which no ``PRAGMA`` reports.
#:
#: The *table* is deliberately not held this way, and :data:`_DECISION_COLUMNS` is
#: why: :meth:`SqliteAuditTrail._migrate` reshapes it with
#: ``ALTER TABLE ... ADD COLUMN``, which rewrites the text SQLite stores, so it has
#: no single definition to compare against. An index has one — nothing here alters
#: an index, and ``ADD COLUMN`` rewrites only the table's own statement — so the
#: weaker introspection is spent only where it must be (issue #1575).
_INDEXES: Final[dict[str, str]] = {
    # A *unique* index, so the per-*confirmation* single-resolution rule (ADR-0036
    # §2) survives even a bug in the check below. SQLite treats NULLs as distinct,
    # so it constrains resolving rows only and leaves ordinary decisions
    # unaffected.
    "decisions_resolves": (
        "CREATE UNIQUE INDEX IF NOT EXISTS decisions_resolves ON decisions(resolves)"
    ),
    "decisions_order": (
        "CREATE INDEX IF NOT EXISTS decisions_order ON decisions(decided_at_us DESC, id ASC)"
    ),
    # ADR-0044 §2b: a *concrete* ``(execution_id, step_id)`` binding carries at
    # most one resolution — the per-*binding* rule layered on top of the
    # per-confirmation one. Partial, over resolving rows with a concrete binding
    # only; NULLs being distinct leaves non-concrete (direct) bindings
    # unconstrained. This is the safety net beneath the checked read in
    # :meth:`_check_binding_undecided`.
    "decisions_binding_resolution": (
        "CREATE UNIQUE INDEX IF NOT EXISTS decisions_binding_resolution "
        "ON decisions(execution_id, step_id) "
        "WHERE resolves IS NOT NULL AND execution_id IS NOT NULL AND step_id IS NOT NULL"
    ),
    # ADR-0044 §3: ``pending_confirmation`` finds a binding's CONFIRMs by this.
    "decisions_binding": (
        "CREATE INDEX IF NOT EXISTS decisions_binding ON decisions(execution_id, step_id, outcome)"
    ),
}

#: **What the ``decisions`` table must be**: declared type, ``NOT NULL``, and
#: position in the primary key, per column — the shape :data:`_CREATE_TABLE` and
#: :meth:`SqliteAuditTrail._migrate` between them arrive at, whichever of the two
#: got there. Checked by introspection at open, because the table has no single
#: stored definition to compare against (:data:`_INDEXES` says why). Extra columns
#: are tolerated: a future ``_migrate`` adds one exactly as the ADR-0044 and
#: ADR-0059 columns were added, and a file already carrying it is this store's own
#: newer shape rather than a foreign one.
#:
#: ``id`` carries ``pk`` 1 and every other column 0: SQLite reports the *position*
#: in the key, so a composite ``PRIMARY KEY (id, decided_at_us)`` would leave ``id``
#: at 1 and put a second column at 2 — a key under which one id can appear twice,
#: which the joined reads then resolve to two rows under one identifier
#: (ADR-0192 §2). Its ``NOT NULL`` is ``False`` because SQLite's rowid tables do
#: not imply one from a non-INTEGER primary key; that is what this store creates,
#: so that is what is required.
_DECISION_COLUMNS: Final[dict[str, tuple[str, bool, int]]] = {
    "id": ("TEXT", False, 1),
    "decided_at_us": ("INTEGER", True, 0),
    "resolves": ("TEXT", False, 0),
    "execution_id": ("TEXT", False, 0),
    "step_id": ("TEXT", False, 0),
    "outcome": ("TEXT", False, 0),
    "expires_at_us": ("INTEGER", False, 0),
    "data": ("TEXT", True, 0),
}

#: **Every column whose *text* is compared, and which must therefore collate byte
#: for byte.** The third part of the shape, and the one neither the columns nor the
#: index definitions can see: ``TEXT COLLATE NOCASE`` reports plain ``TEXT`` to
#: ``PRAGMA table_info``, and an index over such a column *inherits* the collation
#: rather than restating it, so every definition above still matches verbatim — and
#: yet ``WHERE id = ?`` has become case-insensitive. ``get("A")`` then answers with
#: the record written as ``"a"``, which is ADR-0192 §2's single id space broken from
#: the other side; a resolution naming ``"A"`` likewise passes
#: :meth:`SqliteAuditTrail._check_resolution` by reading the confirmation ``"a"``
#: (ADR-0036 §2).
#:
#: ``data`` is not here: it is decoded, never compared. Nor are the two integer
#: columns, which do not collate at all.
_DECISION_COMPARED: Final[tuple[str, ...]] = (
    "id",
    "resolves",
    "execution_id",
    "step_id",
    "outcome",
)

#: **Every trigger this store defines, by the table it is attached to.** Holding the
#: objects this store *names* to their definitions leaves one move open, because a
#: trigger nothing names is attached to a table rather than replacing anything on
#: it — and a trigger is the one object that decides what a write actually does. A
#: file arriving with ``CREATE TRIGGER discard BEFORE INSERT ON decisions BEGIN
#: SELECT RAISE(IGNORE); END`` passes every check over the columns, the indexes and
#: the collations, and then discards every row silently: SQLite reports the ignored
#: insert as a success, so :meth:`SqliteAuditTrail.record` returns the identifier of
#: a decision that is not there. A trail that reports a durable write which never
#: happened is the exact opposite of ADR-0004 §7's reviewable record, so a trigger
#: this store did not define is refused wherever it is attached.
#:
#: ``meta`` is here for the same reason ADR-0049 §1's restamp exists: an ignored
#: ``UPDATE`` would leave a version-1 marker standing over a version-2 shape, which
#: is the downgrade the marker is what makes reportable.
#:
#: **Keyed lower-case, and looked up that way**, because SQLite folds an identifier's
#: case while ``sqlite_master`` keeps the spelling it was declared with: a table
#: created as ``Decisions`` is the one every statement here reads, and a trigger on
#: it arrives under a ``tbl_name`` an exact lookup does not know. Only ASCII is
#: folded by SQLite, and ``str.lower`` folds at least that, so a name SQLite calls
#: this store's table is always matched — and the exotic spelling it would not is
#: matched too, which refuses rather than admits.
_TRIGGERS: Final[dict[str, frozenset[str]]] = {
    "meta": frozenset(),
    "decisions": frozenset(),
    "invocations": frozenset({"invocations_append_only"}),
}

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

#: Keyed by name, because :data:`_INVOCATION_OBJECTS` holds each one to its own
#: definition and a positional tuple would make that mapping a place to get wrong.
_INVOCATION_INDEXES = {
    # The primary key `id` cannot be, because SQLite refuses a generated column in
    # one. Same constraint, same enforcement, and the derivation is kept.
    "invocations_id": "CREATE UNIQUE INDEX IF NOT EXISTS invocations_id ON invocations(id)",
    # A *unique* index, so "a claim is completed once" survives even a bug in the
    # checked read. SQLite treats NULLs as distinct, so it constrains completions
    # only and leaves claims unaffected.
    "invocations_completes": (
        "CREATE UNIQUE INDEX IF NOT EXISTS invocations_completes ON invocations(completes)"
    ),
    # The append order, and the per-decision scan every admission rule reads.
    "invocations_seq": "CREATE UNIQUE INDEX IF NOT EXISTS invocations_seq ON invocations(seq)",
    "invocations_decision": (
        "CREATE INDEX IF NOT EXISTS invocations_decision ON invocations(decision_id, seq)"
    ),
    "invocations_order": (
        "CREATE INDEX IF NOT EXISTS invocations_order ON invocations(recorded_at_us DESC, id ASC)"
    ),
}

#: **The table is append-only, said to SQLite rather than only to the reader.**
#: ADR-0021 §4's guarantee is that nothing recorded is rewritten, and this store
#: never issues an ``UPDATE`` against ``invocations`` — ``clear()`` deletes, and
#: every other write appends. Stating that as a trigger closes the two columns a
#: comparison cannot reach, and it closes them in the direction validation cannot:
#:
#: * ``seq`` is the durable append order §1's "first" and "last" are decided on. It
#:   is allocated at insert and is absent from :class:`ToolInvocation`, so no read
#:   can hold it to anything — and swapping two claims' ordinals moves the claim a
#:   retry window is measured from, which is an admission decided on a value nothing
#:   revalidates.
#: * ``recorded_at_us`` orders a listing, and a *bounded* listing applies its
#:   ``LIMIT`` in the same statement that orders. A row whose key was altered to sort
#:   late falls beyond the cut, so it is never decoded and never compared — the
#:   caller is handed a wrong page with every row on it valid. Validating rows the
#:   bound excludes would mean reading the whole table to serve a page, which is the
#:   bound defeated rather than enforced.
#:
#: Rewriting ``data`` is refused here too, which is what makes the derived columns
#: whole: they cannot disagree with the blob, so the remaining move against them was
#: to move the blob.
#:
#: **What it is and is not.** It is this store's invariant enforced by the store,
#: the way a ``UNIQUE`` index enforces write-once; it is not a boundary against an
#: actor who can already run arbitrary SQL against the file, who could drop it as
#: easily as run the ``UPDATE``. Nothing at this layer can be, and ADR-0004 §4's
#: owner-only mode is where that question is answered.
_INVOCATIONS_APPEND_ONLY = (
    "CREATE TRIGGER IF NOT EXISTS invocations_append_only "
    "BEFORE UPDATE ON invocations "
    "BEGIN SELECT RAISE(ABORT, 'the audit trail is append-only; invocation rows are never "
    "updated'); END"
)

#: **Every object this store defines over ``invocations``, held to its own
#: definition.** ``CREATE TABLE IF NOT EXISTS`` is a no-op against a table that is
#: already there under that name *whatever shape it has*, so a file arriving with an
#: ``invocations`` table of ordinary columns keeps it — and every projection above
#: then inserts as ``NULL``, because ``_append`` writes only ``seq``,
#: ``recorded_at_us`` and ``data``. The per-decision scan ADR-0192 §1's consume is
#: decided over finds no claims at all, and a spent authorisation admits a second
#: act: the exact failure the generated columns exist to make impossible, walked
#: around rather than through. The indexes and the append-only trigger are held the
#: same way and for the same reason — a pre-existing non-unique
#: ``invocations_completes`` lets one claim be completed twice, and a pre-existing
#: trigger that does nothing lets ``seq`` be rewritten.
#:
#: SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so what it holds is
#: compared against these very statements rather than against a second copy of them
#: written out by hand.
#:
#: The ``decisions`` table is **not** here, and that is a division of labour rather
#: than a gap: ``_migrate`` reshapes it with ``ALTER TABLE ... ADD COLUMN``, which
#: rewrites the stored text, so it has no single definition to compare against.
#: :data:`_DECISION_COLUMNS` holds it by introspection instead, and its indexes —
#: which no ``ALTER`` touches, so they do have one each — are held the way these
#: are, by :data:`_INDEXES`.
_INVOCATION_OBJECTS: Final = {
    "invocations": _CREATE_INVOCATIONS,
    **_INVOCATION_INDEXES,
    "invocations_append_only": _INVOCATIONS_APPEND_ONLY,
}

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
        spend: SpendConfiguration | None = None,
        recipient_grants: RecipientGrantResolution | None = None,
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
            spend: What ADR-0194 §5 has the composition root read and inject —
                the reporting currency, the two ceilings, the unknown-price
                allowance and the zone the calendar periods are computed in.
                **Explicit values, never a ``Settings`` read** (ADR-0194 §11).

                Defaults to an **unconfigured** ceiling, which refuses nothing and
                states no total — and that is not the substitution §5 forbids. That
                clause is about a *consumer* manufacturing a holder where the
                composition root wired none: "no default is substituted where the
                composition root did not wire one", beside "no subsystem constructs
                one". This default is a holder handed no configuration behaving as
                §1 says an unconfigured mechanism behaves: "no ceiling configured
                means no ceiling", unconditionally. Nothing opens that was closed
                before, because §11 puts the four settings in the **consumer
                group** precisely so that no window exists in which a user can
                configure a ceiling this does not consult — the failure that
                placement is written to prevent is a configured ceiling that does
                not bind, and until those settings exist there is none to
                configure. Requiring the argument instead would oblige this lane to
                edit ``app/composition.py``, which §11 makes the consumer group's.
            identifiers: The factory each row's ``id`` is minted from. Defaults to
                the process's own, so two stores in one process never mint from
                independent sequences (ADR-0192 §2). Injected so a suite can force
                a collision or pin a sequence.
            recipient_grants: The **resolution face** of the standing-grant store,
                against which ``record`` resolves a route-(b) ``authorised_by``
                (ADR-0193 §6). One member wide, so the trail holds a read and
                nothing else: it cannot append a grant, revoke one, enumerate the
                user's recipients or erase the store — a trail that could append a
                grant would be one ``record`` call away from authorising the row it
                is about to validate.

                ``None`` substitutes :class:`_NoRecipientGrants`, so the trail
                always **has** a seam. ADR-0193 §6 is unqualified about that and
                gives the trail no counterpart to §7's no-source mode for a
                policy, and the substituted seam holds nothing: every route-(b)
                pointer resolves to ``None`` and the row is refused. That is the
                fail-closed direction and the only answer a deployment with no
                grant store can give. A deployment wires the real store
                (ADR-0193 §1); the composition root passes **one** object to this
                trail and to the policy, and ``tests/app/test_composition.py``
                pins that over the object's identity.

        Raises:
            AuditError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
        self._clock = checked_clock(now, owner="SqliteAuditTrail")
        self._identifiers: IdentifierFactory = (
            identifiers if identifiers is not None else ProcessIdentifiers()
        )
        self._lock = asyncio.Lock()
        self._spend = spend if spend is not None else SpendConfiguration()
        self._recipient_grants: RecipientGrantResolution = (
            recipient_grants if recipient_grants is not None else _NO_RECIPIENT_GRANTS
        )
        # Its own lock: ADR-0194 §3 serialises admissions against each other and
        # deliberately not against the appends, so a completion can land while an
        # admission reads and an admission never sits in front of a write.
        self._spend_lock = asyncio.Lock()
        self._reservations = Reservations()
        self._handle_nonce = uuid4().hex
        self._handle_ordinal = 0
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
            # escaping past the ``AuditError`` boundary this constructor documents
            # (#238; the same clause on the grant store already names it).
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
                for statement in (*_INDEXES.values(), *_INVOCATION_INDEXES.values()):
                    conn.execute(statement)
                conn.execute(_INVOCATIONS_APPEND_ONLY)
                self._check_decisions_schema(conn)
                self._check_invocation_schema(conn)
                self._check_no_foreign_triggers(conn)
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

    def _check_decisions_schema(self, conn: sqlite3.Connection) -> None:
        """Refuse a file whose ``decisions`` table is not the shape this store writes.

        The sibling of :meth:`_check_invocation_schema`, run beside it under the same
        rule and for the same reason — ``CREATE TABLE IF NOT EXISTS`` is a no-op
        against a table of that name whatever shape it has — and split in two because
        the two halves of that shape are knowable in different ways.

        The **indexes** have a stored definition each and are held to it
        (:data:`_INDEXES`), which is the only thing that reaches a partial index's
        ``WHERE``. The **table** does not, because :meth:`_migrate` rewrites its text
        with ``ALTER TABLE ... ADD COLUMN``, so its columns are introspected against
        :data:`_DECISION_COLUMNS` instead: present, of the declared type this store
        writes, nullable as this store writes them, and with ``id`` as the whole of
        the primary key. Extra columns are tolerated; an extra column *in the key* is
        not, because a composite key does not make an id unique on its own.

        Run after the creates, the migration and the index statements, so a
        version-1 file that this open legitimately brought up is judged on what it
        now is rather than on what it arrived as — and **before** the marker is
        written, inside the same transaction, so a refusal rolls back everything the
        migration touched and leaves the file exactly as it arrived.

        A declared type is compared case-folded: SQLite stores it verbatim, and
        ``text`` and ``TEXT`` are one type spelled two ways rather than two shapes.

        Raises:
            AuditError: If the table or one of its indexes is not what this store
                defines.
        """
        held = {
            str(row[1]): (str(row[2]).upper(), bool(row[3]), int(row[5]))
            for row in conn.execute("PRAGMA table_info(decisions)")
        }
        for name, expected in _DECISION_COLUMNS.items():
            found = held.get(name)
            if found == expected:
                continue
            detail = (
                "is absent" if found is None else f"is declared {found!r} rather than {expected!r}"
            )
            msg = (
                f"the audit trail at {self._path!r} holds a decisions table whose {name!r} "
                f"column {detail}; its decision rows cannot be trusted to carry the "
                f"constraints an admission is decided on, so it is not opened"
            )
            raise AuditError(msg)
        extra_key = sorted(name for name, column in held.items() if column[2] and name != "id")
        if extra_key:
            joined = ", ".join(repr(name) for name in extra_key)
            msg = (
                f"the audit trail at {self._path!r} holds a decisions table whose primary "
                f"key also covers {joined}; a composite key does not make an id unique on "
                f"its own, so it is not opened"
            )
            raise AuditError(msg)
        self._check_objects(
            conn,
            _INDEXES,
            "its decision rows cannot be trusted to carry the uniqueness an admission "
            "is decided on",
        )
        self._check_decision_collations(conn)

    def _check_decision_collations(self, conn: sqlite3.Connection) -> None:
        """Refuse a ``decisions`` table whose identifiers do not compare byte for byte.

        The part of the shape neither half of :meth:`_check_decisions_schema` can
        see, for the reason :data:`_DECISION_COMPARED` gives: a collation is invisible
        to ``PRAGMA table_info`` and is inherited rather than restated by every index
        over the column, so a file arriving with ``id TEXT COLLATE NOCASE PRIMARY KEY``
        satisfies both checks above and is nonetheless a store in which two
        identifiers differing only in case are one record.

        Read off the *indexes*, because SQLite reports a collating sequence only per
        indexed column. That is enough and not a compromise: every column in
        :data:`_DECISION_COMPARED` is a key column of an index in :data:`_INDEXES` or
        of the primary key, and both have just been held to what this store defines,
        so the collation of each one is observed at least once. A column whose
        collation is *not* observed is refused rather than assumed, since an
        unreadable shape is not a checked one.

        Raises:
            AuditError: If a compared column collates as anything but ``BINARY``, or
                if no index over it reports a collating sequence at all.
        """
        wanted = [
            str(name)
            for name, origin in conn.execute(
                "SELECT name, origin FROM pragma_index_list('decisions')"
            )
            if str(name) in _INDEXES or str(origin) == "pk"
        ]
        collations: dict[str, set[str]] = {}
        for index in wanted:
            for column, collation, is_key in conn.execute(
                "SELECT name, coll, key FROM pragma_index_xinfo(?)", (index,)
            ):
                # The trailing entry names no column and is not part of the key; it
                # is the rowid (or the remaining table columns, on a WITHOUT ROWID
                # table), and neither is a comparison this store makes.
                if is_key and column is not None:
                    collations.setdefault(str(column), set()).add(str(collation).upper())
        for column in _DECISION_COMPARED:
            found = collations.get(column, set())
            if found == {"BINARY"}:
                continue
            detail = (
                "no index over it reports a collating sequence"
                if not found
                else f"it collates as {', '.join(sorted(found))}"
            )
            msg = (
                f"the audit trail at {self._path!r} holds a decisions table whose {column!r} "
                f"column does not compare byte for byte ({detail}); two identifiers "
                f"differing only in case would then be one record, so it is not opened"
            )
            raise AuditError(msg)

    def _check_invocation_schema(self, conn: sqlite3.Connection) -> None:
        """Refuse a file whose invocation objects are not the ones this store defines.

        Run after the creates and **before** the marker is written, inside the same
        transaction, so a refusal leaves the file exactly as it arrived — unopened,
        unlabelled, and not carrying a version-2 marker over a version-1 shape.

        Every object is compared to the statement that defines it
        (:data:`_INVOCATION_OBJECTS` says why each one matters). An object this open
        created matches by construction; one that was already there matches only if
        it is the same object, which is the whole question.

        Raises:
            AuditError: If an object is missing or is not the one this store defines.
        """
        self._check_objects(
            conn,
            _INVOCATION_OBJECTS,
            "its invocation rows cannot be trusted to record what was claimed",
        )

    def _check_objects(
        self, conn: sqlite3.Connection, objects: Mapping[str, str], consequence: str
    ) -> None:
        """Refuse a file holding an object under one of these names that is not this one.

        SQLite stores a definition verbatim but for ``IF NOT EXISTS``, so each object
        is compared against the very statement that defines it rather than against a
        second copy written out by hand. An object this open created matches by
        construction; one that was already there matches only if it is the same
        object, which is the whole question.

        Args:
            conn: The open connection, inside the setup transaction.
            objects: Name to defining statement, for every object to hold.
            consequence: What a foreign object among them would cost, for the
                refusal to say.

        Raises:
            AuditError: If an object is missing or is not the one this store defines.
        """
        held = {
            str(name): sql
            for name, sql in conn.execute("SELECT name, sql FROM sqlite_master")
            if name in objects
        }
        for name, statement in objects.items():
            defined = statement.replace(" IF NOT EXISTS", "", 1)
            if held.get(name) != defined:
                msg = (
                    f"the audit trail at {self._path!r} holds an object named {name!r} "
                    f"that is not the one this store defines; {consequence}, "
                    f"so it is not opened"
                )
                raise AuditError(msg)

    def _check_no_foreign_triggers(self, conn: sqlite3.Connection) -> None:
        """Refuse a file carrying a trigger on this store's tables that it did not define.

        The move the checks above cannot reach, for the reason :data:`_TRIGGERS`
        gives: they hold every object this store *names* to its definition, and a
        foreign trigger is named by nothing — it is simply attached, and it then
        decides what every write to that table does.

        Run beside the other two and before the marker is written, inside the same
        transaction, so the refusal leaves the file as it arrived.

        Raises:
            AuditError: If a trigger on one of this store's tables is not one of its
                own.
        """
        for name, table in conn.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger'"
        ):
            # The trigger's own name is matched exactly, unlike the table's: a
            # differently-cased spelling of this store's trigger is not this store's
            # trigger, and `_check_objects` has already refused the file for holding
            # nothing under the name it defines.
            defined = _TRIGGERS.get(str(table).lower())
            if defined is None or str(name) in defined:
                continue
            msg = (
                f"the audit trail at {self._path!r} holds a trigger {str(name)!r} on "
                f"{str(table)!r} that this store did not define; a trigger decides what a "
                f"write does, so a record this store called durable need never have "
                f"landed — it is not opened"
            )
            raise AuditError(msg)

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

        **A decision carrying an ``OriginUnrecordedBinding`` or a
        ``CoverageUnrecordedBinding`` is refused** (ADR-0184 §4, ADR-0233 §14,
        :func:`_refuse_origin_unrecorded`): each shape is only ever read out of a row
        written before the member its name states existed, and never minted into one.

        Raises:
            AuditError: If the decision does not satisfy its own model, carries an
                ``OriginUnrecordedBinding`` or a ``CoverageUnrecordedBinding``, or the
                database refuses the write. Pydantic's ``ValidationError`` is
                deliberately not allowed to escape: CONTRIBUTING has this layer
                raise only from the ``AssistantError`` hierarchy, and a caller
                handling "the trail would not accept this" should not need a
                second handler for the shape of the refusal.
            DuplicateDecisionError: If the id is already recorded.
            InvalidResolutionError: If ``resolves`` fails the ADR-0021 §1
                invariant.
            InvalidAuthorisationError: If a route-(b) egress decision — a
                non-resolving ``ALLOW`` carrying an ``egress_binding`` and an
                ``authorised_by`` — fails any of ADR-0193 §6's eight checks, or if
                a **resolving** ``ALLOW`` carries an ``authorised_subject``. A
                sibling of the two above under ``AuditError`` because a replayed
                write, a substituted resolution subject and an unvalidated standing
                pointer are three facts an operator must be able to tell apart.
        """
        snapshot = _rebuilt(decision)
        _check_standing_shape(snapshot)
        _refuse_origin_unrecorded(snapshot)
        async with self._lock:
            # The resolution read is inside the lock and immediately before the
            # append, which is the narrowest window this contract can offer: the
            # two are still separate awaits and ADR-0193 §6 states the guarantee
            # over the read rather than over the append, but nothing else on *this*
            # trail interleaves between them.
            #
            # Its **verdict is carried into the transaction rather than raised
            # here**, so the duplicate-id checks refuse first. A replayed route-(b)
            # decision whose grant has since been revoked is a *replayed write*,
            # and reporting it as an unvalidated authorisation would blur the two
            # classes ADR-0021 §4 split precisely so an operator can tell them
            # apart. Raising it here instead was the other repair and is refused:
            # a read in front of ``BEGIN IMMEDIATE`` is the window #526 is about,
            # and this store pins the write lock as its *first* statement.
            refusal = await self._resolve_standing_authorisation(snapshot)
            await _run_to_completion(self._record_sync, snapshot, refusal)
        return snapshot.id

    async def _resolve_standing_authorisation(
        self, decision: PermissionDecision
    ) -> InvalidAuthorisationError | None:
        """Resolve a route-(b) pointer against the grant records (ADR-0193 §6).

        The other five of ADR-0193 §6's eight checks — the ones that need the
        store — plus the digest, taken over **the record the store returned**
        rather than over the decision's account of it. ADR-0021 §3 said what the
        standard is and this is it: *nothing is taken on trust*. Before this
        clause a non-resolving ``ALLOW`` carrying an ``authorised_by`` was written
        with no check of any kind, which is exactly the hole ADR-0021 §3 named
        when it called such a field "a pointer this contract does not verify".

        **The resolution read is one ``await`` and the append is another**, and
        this contract builds no linearisation point across the two stores. What is
        guaranteed is stated over the read: *at the instant the pointer was
        resolved, it named an outstanding grant covering this decision.* A
        revocation or a ``clear`` landing before that read refuses the write — the
        fail-closed direction, and what a user who revokes expects. One landing
        between the read and the append does not, and ADR-0193 §9 states that
        window rather than rounding it to zero.

        **Expiry is decided against the decision's own ``decided_at``, never
        against a clock.** ``record`` reads none, exactly as ADR-0021 §4's "a
        resolution may not predate its confirmation" compares two recorded
        instants. The question is whether the grant was live **at the moment the
        ruling was made**, which is the only question about liveness a durable
        record answers identically on every later read: a grant that expires
        between the ruling and the write does not retract an honest ``ALLOW``, and
        an expired grant can never source a new one. The instant compared is one
        the *policy* does not supply — ADR-0021 §3 put ``decided_at`` in the caller
        that records precisely so — and the policy is the component this invariant
        defends against.

        **Revocation, by contrast, is decided at the resolution read**, because
        ``outstanding`` is a fact about two records and needs no clock, and because
        ordering a revocation against the decision's ``decided_at`` would be
        unsound: a revoking record's own instant is caller-supplied and may
        legitimately predate the grant it revokes.

        **The interval is closed below and open above**, and both ends are checked.
        Equality at the lower end is permitted — a coarse clock stamping a grant
        and the decision that spends it alike is an ordinary thing rather than a
        suspicious one. What the lower end refuses is a decision resting on a grant
        established **after** the ruling was made: not a stale authorisation but a
        **backdated** one, because the policy could not have read a record that did
        not exist when it ruled.

        **The digest is never taken on the decision's word.** It is recomputed here
        from the record ``outstanding`` returned and compared; an implementation
        that compared the decision's ``authorised_subject`` against itself, or
        against anything derived from the decision, has not implemented this
        clause.

        **It returns the refusal rather than raising it**, so ``record`` can apply
        it *inside* the transaction and after the duplicate-id checks. Two
        constraints meet here and only this shape satisfies both: the seam is an
        ``await``, so the read cannot happen inside the worker thread's
        transaction; and #526 pins ``BEGIN IMMEDIATE`` as this store's **first**
        statement, so the duplicate-id read cannot be lifted out in front of the
        seam either. Carrying the verdict costs one seam read on a replayed write
        and buys the error class an operator needs.

        Args:
            decision: The validated snapshot about to be appended.

        Returns:
            The refusal this decision has earned, or ``None`` where the pointer
            resolved to a grant covering it — and ``None`` too for every decision
            outside ADR-0193 §6's scope, which is the majority.

        Raises:
            InvalidAuthorisationError: If the seam could not be read. **Raised**
                rather than returned, and the asymmetry is deliberate: a store
                fault is not something a later duplicate-id refusal should be
                allowed to mask, because the two say different things to an
                operator and only one of them is about this decision. It is
                chained from the
                :class:`~ai_assistant.core.errors.RecipientGrantError` it came
                from, so a caller keeps the one ``AuditError`` handler while an
                operator keeps "the pointer named no outstanding grant" and "the
                seam could not be read" apart.
        """
        if not _names_a_standing_authorisation(decision):
            return None
        binding = decision.egress_binding
        # `_check_standing_shape` has already refused every other arm, and ran
        # before this method on both write paths. The narrowing is repeated for
        # `mypy`, which reads the union rather than the ordering.
        assert isinstance(binding, EgressBinding)  # noqa: S101 — narrowing, refused above
        named = str(decision.ruling.authorised_by)
        try:
            grant = await self._recipient_grants.outstanding(named)
        except RecipientGrantError as exc:
            msg = (
                f"decision {decision.id!r} names standing authorisation {named!r} and the "
                f"grant store could not be read, so nothing validated it; a component that "
                f"cannot get an answer from that seam fails closed (ADR-0193 §1, §6)"
            )
            raise InvalidAuthorisationError(msg) from exc
        if grant is None:
            return InvalidAuthorisationError(
                f"decision {decision.id!r} names standing authorisation {named!r}, which is "
                f"not an outstanding grant: it is absent, is a revoking record, or has been "
                f"revoked (ADR-0193 §6)"
            )
        return _grant_covers(decision, grant, binding)

    def _record_sync(
        self, snapshot: PermissionDecision, refusal: InvalidAuthorisationError | None
    ) -> None:
        """Validate against what is stored and insert, as one transaction.

        ``refusal`` is :meth:`_resolve_standing_authorisation`'s verdict, applied
        **after** the two duplicate-id checks so a replayed write is reported as
        one.
        """
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
            if refusal is not None:
                raise refusal
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

        **A third and a fourth way to answer ``None``: the ``CONFIRM`` is there and
        a fact its question rests on was never recorded**
        (:data:`ORIGIN_UNRECORDED`, :data:`COVERAGE_UNRECORDED`). A row written
        before ADR-0181 §3 added ``planned_with_external_content`` decodes carrying
        an :class:`~ai_assistant.core.types.OriginUnrecordedBinding` (ADR-0184 §2);
        one written before ADR-0233 §4 added ``coverage`` decodes carrying a
        :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` (ADR-0233 §14).
        Neither fact can be established at all: each is required with no default and
        each ADR forbids a seam inventing one, which rules out every value alike.
        ADR-0181 §5's second clause then leaves no route by which any authorisation
        covers such a call — so there is no answerable question here to hand back,
        and this returns ``None`` rather than a decision. **Each carries its own
        condition name**, because a reader meeting one in the log learns which fact
        the row is missing, and the second is detected in its own narrowing rather
        than inherited: a coverage-unrecorded row *has*
        ``planned_with_external_content`` and falls straight past the first.

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
        if isinstance(park.egress_binding, OriginUnrecordedBinding):
            _log.info(
                ORIGIN_UNRECORDED,
                execution_id=execution_id,
                step_id=step_id,
                refused="park",
            )
            return None
        # ADR-0233 §14: the same refusal one epoch on, detected on the decoded
        # value's type and carrying **its own** condition name. Written rather than
        # inherited because such a row *has* ``planned_with_external_content`` and
        # so falls straight past the narrowing above. Nothing is written, the step
        # stays durably ``AWAITING_APPROVAL`` with its ``CONFIRM`` unresolved and its
        # row intact, and one such park does not hide another binding's live one —
        # the four history readers go on returning the row as history (ADR-0184 §5).
        if isinstance(park.egress_binding, CoverageUnrecordedBinding):
            _log.info(
                COVERAGE_UNRECORDED,
                execution_id=execution_id,
                step_id=step_id,
                refused="park",
            )
            return None
        return park

    def _pending_confirmation_sync(self, execution_id: str, step_id: str) -> str | None:
        """The open ``CONFIRM`` for this binding, read as **one** observation.

        Two *dependent* reads: the first decides whether the binding is already
        resolved, the second answers "then which ``CONFIRM`` is still open". Run
        bare, they describe two states of the trail either side of a racing
        commit — the first says unresolved, the second returns a ``CONFIRM`` that
        has since been answered, and the caller is handed a park for a binding
        that is already decided. That is the #257 hazard ADR-0044 §2b exists to
        close, reachable here across *processes*: the ``asyncio`` lock arbitrates
        one event loop and ADR-0036 §2 is explicit that a second process on the
        same file is the case this store exists for.

        ``immediate=False`` is the read form — a deferred transaction, so the two
        ``SELECT``s share one snapshot without taking the write lock a reader has
        no use for. It is the shape :meth:`_spend_rows_sync` and the sibling
        stores' paged reads already use (#720).
        """
        with self._transaction(
            f"read the pending confirmation for ({execution_id!r}, {step_id!r})",
            immediate=False,
        ) as conn:
            if conn.execute(_BINDING_HAS_RESOLUTION, (execution_id, step_id)).fetchone():
                return None
            row = conn.execute(
                _BINDING_CONFIRMS, (PermissionOutcome.CONFIRM.value, execution_id, step_id)
            ).fetchone()
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

        §1's equality is against the decision the ledger was **passed**, and that is
        why it is asked in two halves: ``passed == snapshot`` here, before the first
        suspension, and ``snapshot == stored`` inside the operation
        (:func:`_refuse_unless_as_passed`). Comparing the caller's live object inside
        the lock would be the same clause read literally and is the ADR-0065 breach
        above.

        Raises:
            AuditError: If the decision is not a valid record, the guard rejects
                the clock's reading, the redraw bound is spent, the append ordinal
                is exhausted, or the store cannot be read or written.
            UnrecordedAuthorisationError: If the trail holds no decision under
                that id, holds one that is not equal to it, or holds one whose
                ruling is not ``ALLOW``.
            AuthorisationSpentError: If ADR-0192 §1's consume refuses.
        """
        snapshot = _revalidated(decision)
        _refuse_unless_as_passed(snapshot, decision)
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
                reading, the redraw bound is spent, the append ordinal is exhausted,
                or the store cannot be read or written.
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
        """Insert ``row``, allocating the next durable append ordinal for it.

        **An ordinal SQLite cannot store is a refusal, not a leak** (#1576). The
        allocation is ``MAX(seq) + 1`` over a column this store is not the only
        writer of: reaching ``2**63 - 1`` through this store's own appends takes
        9.22e18 of them, but a foreign writer of the file needs one ``INSERT``, and
        SQLite answers that maximum's successor with a REAL rather than wrapping.
        Binding the result then raises ``OverflowError`` — neither a
        ``sqlite3.Error`` for :func:`~ai_assistant.permissions._transactions.transaction`
        to translate nor an ``AssistantError`` — so it left this layer through the
        hole ``recent`` already names for the same value at the same bound.

        Refused **here**, at the ledger's own boundary, and not by widening the
        transaction helper's arms: that helper translates the backend's
        ``sqlite3.Error`` and passes everything else through unchanged, which is how
        a store's own refusal reaches its caller as itself. An exhausted ordinal is
        this store failing to write, so ADR-0192 §2 has it already — "a failure that
        is neither a named refusal nor an argument fault — the guard rejects the
        reading, the store cannot be read, the store cannot be written — is
        translated at this boundary and raised as a plain ``AuditError`` carrying its
        cause", which is ADR-0026 §4's rule for a subsystem boundary. It is the shape
        :meth:`_mint` already takes for its own exhausted bound, and like that one
        it is an ``AuditError`` and never one of §1's three named classes: those are
        statements about the authorisation, and this says nothing about it. The
        out-of-range arm carries no ``__cause__`` because nothing raised — the
        store refuses before it binds, as :meth:`_mint` refuses before it inserts —
        and the conversion arm carries the one it caught.

        The bound is checked rather than the ``OverflowError`` caught, because the
        allocation reaches it by several routes and only some of them raise: an
        ``int`` at the maximum binds ``2**63``, and the REAL that maximum's successor
        is converts back to the same value. One test on the value covers every one of
        them.

        **Both ends, and the range is the whole test.** ``seq`` has INTEGER affinity
        but a foreign REAL survives it wherever the conversion would lose
        information, so ``MAX(seq) + 1`` can be ``-1e300`` as easily as ``+1e300``,
        and ``int`` converts either into a Python integer no ``INSERT`` will bind.
        What is asked is therefore "can SQLite store this", not "did it grow too
        large" and not "did it go negative": an ordinal *inside* the range is
        appendable whatever its sign — a foreign row can leave the store appending
        below zero, and that row is written, ordered and read like any other — and
        one outside it is unwritable in either direction. The conversion itself is
        guarded for the residue arithmetic on a foreign column can still produce — a
        non-finite REAL, which ``int`` answers with ``OverflowError`` or
        ``ValueError``, neither of which is this layer's to emit either.

        Nothing is written on the refusal: the append is the last act of the
        enclosing transaction, and the helper rolls back on the way out of any
        exception.

        Args:
            conn: The open transaction's connection.
            row: The invocation to append.

        Raises:
            AuditError: If the next append ordinal is not a value SQLite can store.
        """
        next_seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM invocations").fetchone()
        try:
            ordinal = int(next_seq[0])
        except (OverflowError, ValueError) as exc:
            msg = (
                f"the audit trail's append ordinal is not a number to append after: "
                f"{describe_untrusted(next_seq[0])}; no row was appended"
            )
            raise AuditError(msg) from exc
        if not _MIN_SQLITE_INT <= ordinal <= _MAX_SQLITE_INT:
            msg = (
                f"the audit trail cannot allocate an append ordinal: the next ordinal "
                f"after the largest row this store holds is {ordinal}, outside the "
                f"[{_MIN_SQLITE_INT}, {_MAX_SQLITE_INT}] SQLite can store; no row was "
                f"appended"
            )
            raise AuditError(msg)
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

        The argument is read as the **type the signature names**, before the lock:
        :data:`~ai_assistant.core.types.Identifier` strips, so ``"  d-1  "`` and
        ``"d-1"`` are one identifier to every row that holds one, and looking the
        raw text up would answer "no open claims" for a decision holding one — with
        the recovery scan then reserving nothing and leaving the claim open for
        good. The same guard ``complete_invocation`` puts on ``claim_id``.

        Raises:
            AuditError: If ``decision_id`` is not a usable identifier, or the trail
                cannot be read.
        """
        named = _checked_argument("decision_id", lambda: _IDENTIFIER.validate_python(decision_id))
        async with self._lock:
            return list(await _run_to_completion(self._open_invocations_sync, named))

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

    # --- the spend ceiling (ADR-0194) --------------------------------------

    async def admit_invocation(self, *, estimate: ToolCost) -> SpendAdmissionHandle:
        """Admit this invocation and reserve its declared contribution, or refuse.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendGate.admit_invocation`.

        **Its critical section is its own**, and deliberately not the lock the
        appends take (ADR-0194 §3). The admission is not atomic with ADR-0192's
        claim and does not pretend to be: what it serialises is *itself*, so the
        Nth concurrent invocation sees the N-1 reservations already taken, while a
        completion appended by a call already in flight can still land while an
        admission is reading. Sharing one lock would make the second impossible and
        would put an admission's store read in front of every write.

        Raises:
            SpendCeilingError: If a configured ceiling would be crossed.
            SpendUndeterminedError: On ADR-0194 §4's six grounds, in that section's
                order. Every backend failure is translated here, so ``tools/``
                never meets an :class:`AuditError` through this seam.
        """
        if not self._spend.bounded:
            # ADR-0194 §3's short-circuit: no clock, no store, no arithmetic, no
            # reservation, and nothing that can refuse.
            return self._mint_handle()
        contribution = declared_contribution(estimate, self._spend)
        if isinstance(contribution, DeclaredFault):
            # Grounds 1 and 2: facts about the call, decided before any I/O.
            raise SpendUndeterminedError(_undetermined(contribution.value))
        async with self._spend_lock:
            self._reservations.apply_pending()
            instant = self._spend_reading()
            periods = self._periods(instant)
            rows = await self._spend_rows(periods)
            measured = {bounds.period: _measurable(bounds, rows, self._spend) for bounds in periods}
            _refuse_unmeasurable(measured, self._spend)
            return self._compare_and_reserve(periods, measured, contribution)

    def release_admission(self, handle: SpendAdmissionHandle) -> None:
        """Drop the reservation ``handle`` names. Never waits, never raises.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendGate.release_admission`. It
        touches no store and takes no lock, so an invocation whose callable has
        already returned never queues in its ``finally`` behind another
        invocation's store I/O. The reservation is resolved **here** and only its
        application is deferred to the next admission's critical section.
        """
        named = getattr(handle, "handle", None)
        if isinstance(named, str):
            self._reservations.release(named)

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Return one total per period, in ``SpendPeriod``'s fixed order.

        Structurally implements
        :meth:`~ai_assistant.core.protocols.SpendLedger.spend_totals`. **One clock
        reading and one row snapshot**: the rows for both periods come back from a
        single statement, so the pair is always one a snapshot could have produced
        and a completion appended mid-read cannot land between two aggregations.

        It takes no **admission** lock. It reads no reservation — those bound what
        may be *admitted* and are not spend — so nothing here needs to exclude an
        admission, and a totals read never queues behind a wedged one. It does take
        the connection's own exclusion for the length of its read, as every method
        of this store does and as one ``sqlite3`` connection requires (ADR-0054);
        that is a different lock, held only while the statement runs, and an
        admission wedged *after* its snapshot is not holding it.

        Raises:
            SpendUndeterminedError: Only where the values cannot be produced at
                all — a store read that failed, or an injected clock that raised.
                A trapped sum leaves its periods indeterminate instead.
        """
        instant = self._spend_reading()
        periods = self._periods(instant)
        rows = await self._spend_rows(periods)
        priced = self._spend.currency is not None
        return tuple(
            _stated(bounds, _measurable(bounds, rows, self._spend) if priced else None, self._spend)
            for bounds in periods
        )

    # --- the spend ceiling's own helpers ------------------------------------

    def _periods(self, instant: datetime) -> tuple[PeriodBounds, ...]:
        """Return both periods containing ``instant``, from that **one** reading.

        One instant and not one per period: a gate taking its day from one read
        and its month from another can project a total no instant permits.
        """
        try:
            return tuple(period_bounds(instant, self._spend, period) for period in SpendPeriod)
        except (SpendArithmeticError, OverflowError, ValueError, OSError) as exc:
            # **Not** the clock ground: the clock already answered, and naming
            # it would send an operator to a collaborator that did nothing wrong.
            # ADR-0194 §1's boundary rule is total for every reading
            # ``checked_clock`` accepts — every case it enumerates is clamped
            # rather than refused — so this handler is unreachable and exists only
            # to keep §5's ``Exception`` set closed against a defect in *this*
            # implementation's own arithmetic, which is what §4's sixth ground is
            # for: "the class is what an implementation raises when its own sizing
            # is wrong".
            raise SpendUndeterminedError(_undetermined(_ARITHMETIC_TRAPPED)) from exc

    def _spend_reading(self) -> datetime:
        """Take the one guarded clock reading a spend decision is made on.

        A clock that raises refuses with ``SpendUndeterminedError`` — ADR-0029
        §5's fail-closed reading of the same measurement — and never propagates
        its own type, because ADR-0194 §5 closes this seam's ``Exception`` set at
        two classes. A ``BaseException`` that is not an ``Exception`` propagates
        unchanged.
        """
        try:
            return self._clock()
        except Exception as exc:
            raise SpendUndeterminedError(_undetermined(_CLOCK_RAISED)) from exc

    async def _spend_rows(self, periods: Sequence[PeriodBounds]) -> Sequence[_SpendRow]:
        """Read every row either period could hold, as one snapshot.

        **Under the connection's own lock**, which is the exclusion every other
        method of this store takes and which one ``sqlite3`` connection requires:
        two workers inside it at once can meet a ``BEGIN`` while a transaction is
        already open, so an admission reading beside a completion append would
        refuse a call the ceiling had nothing to do with — and could disturb the
        append's own transaction boundary (ADR-0054).

        The lock is released **before** the comparison, which is the whole of what
        the separate spend lock buys: ADR-0194 §3 requires a completion appended by
        a call already in flight to be able to land while an admission is between
        its row snapshot and its decision, and holding the connection across that
        window would make it impossible.
        """
        low = min(bounds.start for bounds in periods)
        high = max(bounds.end for bounds in periods)
        try:
            async with self._lock:
                return await _run_to_completion(self._spend_rows_sync, low, high)
        except Exception as exc:
            raise SpendUndeterminedError(_undetermined(_STORE_UNREADABLE)) from exc

    def _spend_rows_sync(self, low: datetime, high: datetime) -> Sequence[_SpendRow]:
        """Return the rows in ``[low, high)`` with whether each claim is completed.

        **One statement**, so the completion flag and the row set are one
        observation. The flag is a correlated ``EXISTS`` over the whole table and
        not over the window, because a claim recorded before midnight can be
        completed after it and is not open.
        """
        with self._transaction("read the spend rows", immediate=False) as conn:
            return [
                (_as_projected(row[:-1]), bool(row[-1]))
                for row in conn.execute(_SPEND_ROWS, (_sort_key(low), _sort_key(high)))
            ]

    def _compare_and_reserve(
        self,
        periods: Sequence[PeriodBounds],
        measured: Mapping[SpendPeriod, Sequence[Decimal] | None],
        contribution: Decimal,
    ) -> SpendAdmissionHandle:
        """Compare against every configured ceiling, then reserve and mint.

        The comparison is against the projection — accounted, plus every
        outstanding reservation whichever period it was taken in, plus this call's
        own declaration — and refuses **strictly above** a ceiling, so a projection
        exactly equal to one is admitted. The mint sits on the far side of it: a
        refusal consults the injected factory not at all, so a raising factory
        cannot turn a refusal into a cancellation.
        """
        outstanding = self._reservations.outstanding()
        crossings: list[str] = []
        for bounds in periods:
            ceiling = self._spend.ceiling_for(bounds.period)
            amounts = measured[bounds.period]
            if ceiling is None or amounts is None:
                continue
            try:
                accounted = exact_sum(amounts)
                projected = exact_projection(accounted, [*outstanding, contribution])
            except SpendArithmeticError as exc:
                raise SpendUndeterminedError(_undetermined(_ARITHMETIC_TRAPPED)) from exc
            if projected > ceiling:
                crossings.append(
                    f"{bounds.period.value}: {projected} projected against a ceiling of "
                    f"{ceiling} {self._spend.currency}, with {accounted} accounted"
                )
        if crossings:
            raise SpendCeilingError(
                "the invocation was refused: it would cross a configured spend "
                f"ceiling — {'; '.join(crossings)}"
            )
        key = self._reservations.reserve(contribution)
        try:
            handle = self._mint_handle()
        except BaseException:
            # No reservation nobody can release: a cancellation delivered between
            # the reserve and the mint propagates unchanged, and does not take the
            # reservation's only key with it (ADR-0194 §3).
            self._reservations.discard(key)
            raise
        self._reservations.bind(key, handle.handle)
        return handle

    def _mint_handle(self) -> SpendAdmissionHandle:
        """Return a handle no value this holder has ever delivered equals.

        The injected factory supplies **opacity** and nothing more: a candidate the
        type refuses, one this holder has already delivered, and a factory raising
        an ``Exception`` are each replaced by a value generated here. None of the
        three reaches the caller and none costs the call. A ``CancelledError`` from
        the factory is a cancellation delivered inside ``admit_invocation`` and
        propagates unchanged, which is why the guard is over ``Exception`` alone.

        Distinctness is over this holder's **lifetime** and over the *validated*
        value: ``Identifier`` strips, so ``"h"`` and ``" h "`` are one handle, and a
        re-minted retired value would let a stale release drop a live reservation.
        """
        delivered = self._reservations.delivered
        candidate: SpendAdmissionHandle | None = None
        try:
            candidate = SpendAdmissionHandle.model_validate({"handle": self._identifiers()})
        except Exception:
            candidate = None
        if candidate is None or candidate.handle in delivered:
            candidate = self._generated_handle()
        delivered.add(candidate.handle)
        return candidate

    def _generated_handle(self) -> SpendAdmissionHandle:
        """Return this holder's own next handle, distinct by construction.

        A per-holder nonce and an ordinal rather than a bare draw: ADR-0045 §4
        already rules that an unlikely collision is not a property to rely on, and
        this value's whole job is to be unlike every other one this holder has
        handed out. The ``delivered`` check is what closes the remaining case, a
        generated value the *factory* had produced earlier.
        """
        while True:
            self._handle_ordinal += 1
            text = f"{self._handle_nonce}-{self._handle_ordinal}"
            if text not in self._reservations.delivered:
                return SpendAdmissionHandle(handle=text)

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


#: One row the spend read returns: the row itself, and whether a completion names
#: it. The flag is meaningless on a completion and is read only for a claim.
type _SpendRow = tuple[ToolInvocation, bool]

#: Every row either spend period could hold, with whether each claim is completed.
#: **One statement**, so the two facts are one observation: a claim recorded before
#: a boundary can be completed after it, so the ``EXISTS`` is over the whole table
#: while the rows are over the window.
_SPEND_ROWS = (
    "SELECT i.data, i.id, i.decision_id, i.recorded_at_us, i.completes, i.outcome, "
    "EXISTS(SELECT 1 FROM invocations c WHERE c.completes = i.id) "
    "FROM invocations i WHERE i.recorded_at_us >= ? AND i.recorded_at_us < ?"
)


#: ADR-0194 §4's six grounds, as **fixed** text.
#:
#: Fixed, and never the caught exception interpolated into a message. A collaborator
#: this seam is written to distrust — an injected clock, a backend — may raise a value
#: whose ``__str__`` raises, and formatting it would leak *that* exception out of a
#: member ADR-0194 §5 closes at two classes, which is the one thing the translation
#: exists to prevent. The original is chained as ``__cause__``, so nothing needed to
#: diagnose it is lost, and §4's payload-free rule is tightened rather than relaxed:
#: the numbers and the ground are the whole explanation.
_CLOCK_RAISED: Final = "the injected clock raised"
_STORE_UNREADABLE: Final = "the store could not be read"
_ARITHMETIC_TRAPPED: Final = "the arithmetic trapped"


def _undetermined(because: str) -> str:
    """Compose ADR-0194 §4's payload-free message for an unmeasurable spend.

    It names which ground applied and nothing about the call: no argument value,
    no recipient, no account, no tool output and no digest of any of them. The
    error travels further than the call did.
    """
    return f"the invocation was refused: the spend could not be reduced to a number — {because}"


def _measurable(
    bounds: PeriodBounds, rows: Iterable[_SpendRow], config: SpendConfiguration
) -> Sequence[Decimal] | None:
    """Return what each row in ``bounds`` contributes, or ``None`` if it cannot be told.

    A period is **indeterminate** where an open claim falls in it — a claim states
    that an act may have happened and does not state what it cost — or where a
    completion reports a cost this mechanism may not add: an ``UNKNOWN`` basis or
    a foreign currency with no allowance configured, or an amount that is not
    countable. It is a state of one period, and it is recomputed from the rows
    every time rather than persisted as a flag.

    Every completion in the period counts, including the one whose reported cost
    carried the total past a ceiling and one whose outcome is ``INDETERMINATE``:
    no row is excluded because a refusal followed it, because the act may not have
    happened, or because the figure is inconvenient.
    """
    amounts: list[Decimal] = []
    for row, completed in rows:
        if not bounds.contains(row.recorded_at):
            continue
        if row.completes is None:
            if not completed:
                return None
            continue
        if row.incurred_cost is None:  # pragma: no cover - ToolInvocation forbids it
            return None
        contribution = reported_contribution(row.incurred_cost, config)
        if contribution is None:
            return None
        amounts.append(contribution)
    return amounts


def _refuse_unmeasurable(
    measured: Mapping[SpendPeriod, Sequence[Decimal] | None], config: SpendConfiguration
) -> None:
    """Refuse where a period carrying its **own** ceiling cannot be measured.

    ADR-0194 §2's per-period narrowing: a period nobody set a ceiling for is a
    reporting figure and enforces nothing, so with only a day ceiling set a month
    that cannot be measured refuses nothing. It does not need to — a period
    contains its days, so an unmeasurable row in the *current* day makes that day
    indeterminate too. What the narrowing excludes is exactly the case where the
    unmeasurable row is in an earlier day of the same month, which is a bound the
    user never stated refusing work they authorised.

    Where both configured periods are indeterminate at once the message names
    both, in ``SpendPeriod``'s fixed order: neither takes precedence, and naming
    only the day would tell a user to wait until tomorrow when the month cannot be
    measured either.
    """
    unmeasured = [
        period.value
        for period in SpendPeriod
        if measured[period] is None and config.ceiling_for(period) is not None
    ]
    if unmeasured:
        raise SpendUndeterminedError(
            _undetermined(f"these periods cannot be measured: {', '.join(unmeasured)}")
        )


def _stated(
    bounds: PeriodBounds, amounts: Sequence[Decimal] | None, config: SpendConfiguration
) -> SpendTotal:
    """Build the ``SpendTotal`` for one period, indeterminacy included.

    ``accounted`` is absent in exactly two states and ``currency`` tells them
    apart: absent currency means none is configured and no sum was attempted;
    present currency means the period is indeterminate. A trapped sum lands in the
    second, because the other period's figure is still computable and ADR-0194 §5
    permits this member exactly one raised class and only where it can produce no
    value at all.
    """
    accounted: Decimal | None = None
    if config.currency is not None and amounts is not None:
        try:
            accounted = exact_sum(amounts)
        except SpendArithmeticError:
            accounted = None
    return SpendTotal(
        period=bounds.period,
        period_start=bounds.start,
        period_end=bounds.end,
        start_offset=bounds.start_offset,
        end_offset=bounds.end_offset,
        ceiling=config.ceiling_for(bounds.period) if config.currency is not None else None,
        currency=config.currency,
        accounted=accounted,
    )


def _revalidated(decision: PermissionDecision) -> PermissionDecision:
    """Rebuild ``decision`` as a validated record and refuse an unrecorded origin.

    :func:`_rebuilt` followed by :func:`_refuse_origin_unrecorded`, which is what
    this function has always been; the two halves are named separately since
    ADR-0193 §6 so that ``record`` can run its store-free route-(b) refusals
    between them. Every caller that wants both in the original order keeps calling
    this.

    Raises:
        AuditError: If the value is not a valid record at all, does not satisfy the
            model, or rebuilds carrying an ``OriginUnrecordedBinding`` or a
            ``CoverageUnrecordedBinding``.
    """
    snapshot = _rebuilt(decision)
    _refuse_origin_unrecorded(snapshot)
    return snapshot


def _rebuilt(decision: PermissionDecision) -> PermissionDecision:
    """Rebuild ``decision`` as a validated :class:`PermissionDecision`.

    ADR-0021 §4 asks for a *validated* snapshot, not merely a detached one. A
    copy alone detaches without checking, so a decision corrupted past its frozen
    model's guard — a ``decided_at`` written back as naive is the sharp case —
    would be stored and then make every later ordered read incoherent.

    Rebuilt as a ``PermissionDecision`` specifically, not as ``type(decision)``:
    a caller's subclass could carry extra fields, and ``extra="forbid"`` refuses
    them here rather than letting them vanish at serialisation and make the
    stored record differ from the one that reloads.

    **An ``OriginUnrecordedBinding`` and a ``CoverageUnrecordedBinding`` are refused
    here** (ADR-0184 §4, ADR-0233 §14), and it is the one refusal the model cannot
    make for itself: each shape is a *valid* ``PermissionDecision``, because each has
    to be for a stored row to decode into one. Each represents a row from an epoch
    that has ended, so each is only ever read out of a store and never minted into
    one — a caller bypassing ``from_request`` could otherwise construct such a
    decision and append it, fabricating history rather than a value. ``record`` is
    where the trail already enforces what a model cannot see for itself (ADR-0021
    §4), and this is one more clause of that kind.

    **The refusal is named from the snapshot too**, because a caller can hand over a
    raw mapping: it validates into a decision — that is the ordering above — and
    ``given.id`` on a ``dict`` is an ``AttributeError`` raised from inside the refusal
    that was about to be made.

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


    **Every ordinary exception the read raises is caught, not only the ones a
    validator means to raise.** A value that is not a model at all reaches
    ``model_validate`` untouched (that is the ordering above), and validating a
    mapping walks it: a ``__getitem__`` that raises leaves as itself through a check
    that was about to refuse the value anyway. The whole read is a function of the
    caller's argument, so whatever it raises is a fault of that argument, and
    ADR-0192 §2's order is exhaustive over the classes a refusal arrives in.
    ``BaseException`` is deliberately not caught: a cancellation is not a fault of
    the argument and is never absorbed (ADR-0060 §1).

    Raises:
        AuditError: If the value is not a valid record at all, or does not satisfy
            the model. The ``OriginUnrecordedBinding`` and
            ``CoverageUnrecordedBinding`` refusals are
            :func:`_refuse_origin_unrecorded`'s, called by :func:`_revalidated`
            immediately after this and by ``record`` a step later.
    """
    given: object = decision
    try:
        snapshot = PermissionDecision.model_validate(field_state(PermissionDecision, given))
    except Exception as exc:
        # `describe_untrusted` and never `repr`: the id is the caller's, and a
        # `__repr__` that raises would replace this `AuditError` with whatever it
        # threw — from inside the `except` block that exists to report it.
        named = _named_decision(given)
        # `describe_untrusted` on the cause as well as on the id. `field_state`
        # re-raises a `ValueError` the caller's own code raised, and a hostile
        # `__str__` on it would replace this `AuditError` with whatever it threw —
        # from inside the `except` block that exists to report it (ADR-0192 §2's
        # order is exhaustive over the classes a refusal arrives in).
        msg = f"decision {named} is not a valid record: {describe_untrusted(exc)}"
        raise AuditError(msg) from exc
    return snapshot


def _refuse_origin_unrecorded(snapshot: PermissionDecision) -> None:
    """Refuse a decision from an ended epoch (ADR-0184 §4, ADR-0233 §14).

    Split out of :func:`_revalidated` so ``record`` can run ADR-0193 §6's
    store-free route-(b) refusals **first** — which is what makes a route-(b) row
    carrying such a shape land as an ``InvalidAuthorisationError`` rather than as a
    bare ``AuditError``. Nothing about the rule changes: every other path still
    reaches it in the same place, and a decision not in route-(b) scope is refused
    here exactly as before.

    **Two shapes rather than one since ADR-0233 §14**, which extends ADR-0184 §4's
    second clause **by cause**: each names a row from an epoch that has ended, each
    is only ever read out of a store and never minted into one, and each is refused
    with the trail's existing ``AuditError`` and no new error class. The second is
    written rather than inherited because a coverage-unrecorded row *has*
    ``planned_with_external_content`` and so falls past the first narrowing, and each
    message names the fact its own epoch was missing.

    Raises:
        AuditError: If the binding records no origin, or no coverage.
    """
    if isinstance(snapshot.egress_binding, OriginUnrecordedBinding):
        msg = (
            f"decision {snapshot.id!r} is not a valid record: its egress binding "
            f"records no origin, which is a shape only a row written before "
            f"ADR-0181 can have; the trail reads such rows and never writes one"
        )
        raise AuditError(msg)
    if isinstance(snapshot.egress_binding, CoverageUnrecordedBinding):
        msg = (
            f"decision {snapshot.id!r} is not a valid record: its egress binding "
            f"records no coverage, which is a shape only a row written before "
            f"ADR-0233 can have; the trail reads such rows and never writes one"
        )
        raise AuditError(msg)


def _named_decision(given: object) -> str:
    """How a refusal names the decision it refuses, and never a way to raise from it.

    The id is the caller's value, on the caller's object, under a key the caller
    chose, and the message reporting the fault has to survive all three.
    ``isinstance`` consults ``__class__``, which can be a property that raises;
    ``__dict__`` can be one too; and ``__dict__.get("id")`` hashes ``"id"`` and then
    compares it against whatever collides with it, which can be a ``str`` subclass
    whose ``__eq__`` raises — reachable exactly where the genuine key has been
    deleted. So the id is found by a scan that hashes nothing and compares only keys
    that are *exactly* ``str`` (``_detachment._refuse_undeclared`` states that discipline in
    full), and the whole of it is guarded: a diagnostic that raises would replace the
    ``AuditError`` it is naming with whatever it threw, from inside the ``except``
    block that exists to report it.
    """
    try:
        if isinstance(given, PermissionDecision):
            for key, value in given.__dict__.items():
                if type(key) is str and key == "id":
                    return describe_untrusted(value)
    except Exception:  # the value cannot even be named; say so and carry on
        return "the given value"
    return "the given value"


def _refuse_unless_as_passed(snapshot: PermissionDecision, given: object) -> None:
    """Refuse unless ``snapshot`` is the decision that was passed (ADR-0192 §1).

    §1 decides the admission on "the decision it was **passed** ... the whole value,
    by the frozen model's own equality", and decides it *inside* the atomic
    operation. Re-reading the caller's object in there is what ADR-0065 forbids — it
    can change across the suspension the lock is — so the equality is composed of two
    halves instead: this call establishes ``passed == snapshot`` before the first
    ``await``, and the operation establishes ``snapshot == stored``. Together they are
    §1's clause, decided inside the operation over a value observed before any
    suspension point.

    This half is the one ``_detachment._refuse_undeclared`` cannot give. That refusal stops
    the rebuild **dropping** state; this one stops it **normalising** the value into a
    different one. A root subclass whose fields are all identical is unequal by the
    frozen model's own equality, and so is a ``list`` where the model declares a
    ``tuple``; either would otherwise be admitted as the decision the store holds.

    Nothing is refused here that the trail would not accept — a value the two clauses
    disagree about does not exist. It is *placed* here rather than in
    :func:`_revalidated` because ``record`` has no equality to keep: its obligation is
    on the declared type, which is why ``AuditTrailContract`` requires it to accept a
    caller's subclass and store a ``PermissionDecision``. §1's equality is an
    admission, and an admission is the ledger's.

    **The type test comes first and is by identity**, because Python gives a
    subclass's ``__eq__`` reflected priority: a caller's subclass would otherwise
    answer the question that decides its own admission. Once ``given`` is exactly a
    ``PermissionDecision`` the comparison is this model's own, over field values whose
    model types ``_detachment._refuse_undeclared`` has already fixed.

    **A comparison that raises is an argument fault rather than an admission.** A
    field can hold a ``str`` subclass whose ``__eq__`` raises, and this refusal must
    not leave as whatever that threw; §2's order is exhaustive over the classes a
    refusal arrives in. Nothing of the caller's is interpolated into the message for
    the same reason.

    Raises:
        AuditError: If the comparison cannot be made at all.
        UnrecordedAuthorisationError: If what was passed is not what the snapshot is,
            so no decision the store holds can be equal to it.
    """
    try:
        as_passed = type(given) is PermissionDecision and snapshot == given
    except Exception as exc:
        msg = (
            f"decision {snapshot.id!r} is not a valid record: it cannot be compared "
            f"with the value it was built from"
        )
        raise AuditError(msg) from exc
    if not as_passed:
        # One class and one message for every ground, as `_claim_sync`'s own two
        # have: they are all "the authority this call claims is not one this store
        # recorded", and separating them would tell a caller which half of a forgery
        # was detected (ADR-0192 §2).
        msg = (
            f"the trail records no decision equal to {snapshot.id!r}; an "
            f"authorisation it did not record authorises nothing"
        )
        raise UnrecordedAuthorisationError(msg)


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
    checked = ToolCost.model_validate(field_state(ToolCost, value))
    return ToolCost.model_validate_json(checked.model_dump_json())


def _decode(data: str) -> PermissionDecision:
    """Rebuild a stored decision from its JSON.

    **A row recorded before ADR-0181 §3's ``planned_with_external_content``, or
    before ADR-0233 §4's ``coverage``, decodes rather than raising** (ADR-0184 §2,
    §5, ADR-0233 §14), carrying an
    :class:`~ai_assistant.core.types.OriginUnrecordedBinding` or a
    :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` in place of an
    ``EgressBinding``. Nothing here recognises either: the discrimination is
    structural, done by the union on :attr:`PermissionDecision.egress_binding` and by
    ``extra="forbid"`` on the shared chain, so there is no predicate to widen and no
    branch to take. The tolerance is exactly as many shapes wide as there are epochs
    — a row that is *also* faulty elsewhere, and one carrying ``coverage`` without
    ``planned_with_external_content``, satisfy no arm of the union and still raise
    below, which is what the retired ``_is_origin_unrecorded`` bought with a
    hand-written check over ``exc.errors()``.

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

    **Every ordinary exception, and not only the ones a validator means to raise.**
    ``build`` never does anything but check a value, and the value is the caller's,
    so whatever it raises is a fault of that value — including where the value is
    what makes the check itself fail: ``ToolOutcome(value)`` looks the member up in a
    mapping, so a ``str`` subclass whose ``__hash__`` raises leaves through a
    validator that never got to say no. ADR-0192 §2's order is exhaustive over the
    classes a refusal arrives in, so none of them may leave as itself.
    ``BaseException`` is deliberately not caught: a cancellation is not a fault of
    the value and is never absorbed (ADR-0060 §1).

    Raises:
        AuditError: If ``build`` rejects the value.
    """
    try:
        return build()
    except Exception as exc:
        # `describe_untrusted` on the cause, for :func:`_revalidated`'s reason: the
        # value is the caller's, and so is any exception reading it raised.
        msg = f"the audit trail was given a {name} it cannot record: {describe_untrusted(exc)}"
        raise AuditError(msg) from exc


def _spend_refusal(decision_id: str) -> Callable[[str], AuthorisationSpentError]:
    """Build this decision's refusal, so every arm reads the same but for its cause."""

    def _refuse(because: str) -> AuthorisationSpentError:
        return AuthorisationSpentError(
            f"the authorisation recorded as {decision_id!r} is spent: {because}"
        )

    return _refuse


@final
class _NoRecipientGrants:
    """A conforming :class:`RecipientGrantResolution` that holds nothing.

    ADR-0193 §6 is unqualified — "``AuditTrail`` implementations **are
    constructed with** a ``RecipientGrantResolution``" — and gives the trail no
    counterpart to §7's explicit no-source mode for a policy. So a trail always
    has a seam, and one wired with nothing gets **this** rather than a special
    case in :meth:`SqliteAuditTrail.record`: a store holding no standing grants is
    an ordinary state a deployment can be in (``recipient_grant_max_outstanding``
    of zero is ADR-0193 §1's own way of declining route (b)), and it is not a
    third mode of the trail.

    Every route-(b) pointer therefore resolves to ``None`` and the row is refused,
    which is the fail-closed direction and the only answer a deployment with no
    grant store can give.

    **What it does not decide is where the seam comes from.** A trail holding this
    one and a policy holding a real store would author ``ALLOW``s the trail
    refuses; so would two real stores over two files. That is a property of the
    composition root — it passes one object to both — and
    ``tests/app/test_composition.py`` pins it there, over the object's identity,
    which is the only place it can be pinned.
    """

    async def outstanding(self, grant_id: str) -> RecipientGrant | None:  # noqa: ARG002
        """Answer ``None``: this seam holds no grant, whatever is asked of it."""
        return None


#: The one instance every trail wired with no grant store shares. Stateless, so
#: sharing it is free and holds nothing between trails.
_NO_RECIPIENT_GRANTS: Final = _NoRecipientGrants()


def _names_a_standing_authorisation(decision: PermissionDecision) -> bool:
    """Whether ADR-0193 §6's invariant is in scope for ``decision``.

    A **route-(b) egress decision**, and nothing else: a non-resolving ``ALLOW``
    whose ``egress_binding`` is not ``None`` and whose ``authorised_by`` is set.
    ``resolves`` is the discriminator the records already carry — a route-(a)
    ``ALLOW`` sets it and equals it to ``authorised_by``, and a route-(b) one
    leaves it unset — so no field was added to say which basis a row rests on
    (ADR-0193 §6).

    **The scope is deliberately narrow, and no lane widens it into a general rule
    about** ``authorised_by``. A decision with no ``egress_binding`` is not an
    egress call, and ADR-0021 §6's standing grants for *other* actions stay
    deferred and unnarrowed: such a decision falls outside this invariant rather
    than needing an exception inside it, so the ADR that opens one states its own
    scope beside this one instead of finding ``PermissionDecision`` already shaped
    against it.
    """
    ruling = decision.ruling
    return (
        ruling.outcome is PermissionOutcome.ALLOW
        and decision.resolves is None
        and decision.egress_binding is not None
        and ruling.authorised_by is not None
    )


def _check_standing_shape(decision: PermissionDecision) -> None:
    """Refuse the route-(b) defects decidable from the decision alone (ADR-0193 §6).

    Three of ADR-0193 §6's eight checks and its pairing clause need no store, so
    they are made here — **before** the ended-epoch refusals ADR-0184 §4 and
    ADR-0233 §14 state over every decision. The order is what makes an
    origin-unrecorded or coverage-unrecorded case land as an
    :class:`~ai_assistant.core.errors.InvalidAuthorisationError` rather than as a
    bare ``AuditError``, which ADR-0193 §14 requires by type; both clauses are
    satisfied either way, since the row is still refused and this class *is* an
    ``AuditError``. A decision carrying either shape and **not** in route-(b) scope
    is untouched here and still refused there, exactly as before.

    **The origin check is stated over the binding's arm, not over a field's
    value.** Only :class:`~ai_assistant.core.types.EgressBinding` carries
    ``planned_with_external_content`` at all, so a validator reading the check as a
    field test would raise ``AttributeError`` on the other arm — or, worse, accept
    it — and ADR-0193 §4's floor would be bypassed by a *missing* field rather than
    by a false one.

    Raises:
        InvalidAuthorisationError: If a **resolving** ``ALLOW`` carries an
            ``authorised_subject``; or if a route-(b) egress decision's binding
            records no origin, records that the call was planned over external
            content, or carries no ``authorised_subject`` to check.
    """
    ruling = decision.ruling
    if decision.resolves is not None:
        if ruling.authorised_subject is not None:
            msg = (
                f"decision {decision.id!r} resolves a confirmation and fingerprints a "
                f"standing authorisation; route (a) rests on a recorded confirmation, "
                f"which is not a grant and has no subject digest (ADR-0193 §6)"
            )
            raise InvalidAuthorisationError(msg)
        return
    if not _names_a_standing_authorisation(decision):
        return
    binding = decision.egress_binding
    if not isinstance(binding, EgressBinding):
        msg = (
            f"decision {decision.id!r} rests on a standing authorisation but records an "
            f"egress call whose origin was never recorded; no standing authorisation "
            f"covers such a call (ADR-0193 §2, §6)"
        )
        raise InvalidAuthorisationError(msg)
    if binding.planned_with_external_content:
        msg = (
            f"decision {decision.id!r} rests on a standing authorisation but records a "
            f"call planned over external content; route (a) — a decision of the user "
            f"about that call — is the only route to an ALLOW on one (ADR-0193 §4, §6)"
        )
        raise InvalidAuthorisationError(msg)
    if ruling.authorised_subject is None:
        msg = (
            f"decision {decision.id!r} names standing authorisation "
            f"{ruling.authorised_by!r} and fingerprints none; a pointer with nothing on "
            f"the row to contradict a rebinding is the record ADR-0193 §6 refuses"
        )
        raise InvalidAuthorisationError(msg)


def _grant_covers(  # noqa: PLR0911 — one return per ADR-0193 §6 comparison, and no fewer
    decision: PermissionDecision, grant: RecipientGrant, binding: EgressBinding
) -> InvalidAuthorisationError | None:
    """Compare the resolved grant against the decision it is claimed to authorise.

    Six of ADR-0193 §6's eight checks — the two ends of the liveness interval and
    §3's declaration, account and destination comparisons, plus the digest. Taken
    over the record ``outstanding`` returned rather than over the decision's
    account of it, which is the whole of what makes the pointer *verified* rather
    than merely present.

    A **module function** rather than a method, so it holds no store and can reach
    none: everything it needs is in its arguments, which is what keeps it a
    comparison of recorded values and stops it acquiring a second read.

    Args:
        decision: The validated snapshot about to be appended.
        grant: The outstanding granting record its ``authorised_by`` resolved to.
        binding: ``decision``'s own binding, already narrowed to the arm that
            records an origin.

    **It returns the refusal rather than raising it**, so ``record`` can apply it
    inside its transaction and after the duplicate-id checks — see
    :meth:`SqliteAuditTrail._resolve_standing_authorisation` for why that ordering
    is the only one both #526's pin and ADR-0021 §4's error split admit.

    Returns:
        The refusal the comparison earned, or ``None`` where the grant covers the
        decision.
    """
    named = grant.id
    if grant.decided_at > decision.decided_at:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"after the ruling was made; the policy could not have read a record that "
            f"did not exist when it ruled (ADR-0193 §6)"
        )
    if grant.expires_at <= decision.decided_at:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was not live when "
            f"the ruling was made; an expired grant never sources a new ALLOW "
            f"(ADR-0193 §6)"
        )
    if grant.tool != decision.tool:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"about a different declaration; coverage compares the ToolDefinition whole "
            f"and by value, so a declaration edit re-prompts (ADR-0193 §1, §3)"
        )
    if grant.account != binding.account:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which was established "
            f"against a different connected account; an account is two facts, identity "
            f"and connection reference, and never one (ADR-0193 §3)"
        )
    if any(member not in grant.destinations for member in binding.canonical_destination_set):
        return InvalidAuthorisationError(
            f"decision {decision.id!r} rests on grant {named!r}, which does not name "
            f"every recipient of this call; coverage is set membership and nothing "
            f"looser (ADR-0193 §3)"
        )
    if decision.ruling.authorised_subject != grant.subject_digest:
        return InvalidAuthorisationError(
            f"decision {decision.id!r} fingerprints a standing authorisation the store's "
            f"grant {named!r} does not match; the digest is recomputed from the record "
            f"the store returned and never taken on the decision's word (ADR-0193 §6)"
        )
    return None


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
