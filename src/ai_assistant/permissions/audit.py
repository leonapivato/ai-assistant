"""A durable :class:`~ai_assistant.core.protocols.AuditTrail` on SQLite (ADR-0036 §2).

ADR-0004 §7 makes the permission trail a Tier 1 store whose job is to make the
assistant's behaviour "transparent and reviewable", and ADR-0021 §1 embeds the
whole ``ToolDefinition`` in every record precisely so the trail still says what
was approved after a restart has rebuilt the registry (issue #54). Both of those
are claims about a record that outlives the process, so the trail persists —
ADR-0036 §2 records why an in-process one would have satisfied the Protocol and
not the decisions behind it.

Local-first (ADR-0002), and **locally only**: ADR-0021 §4 applies ADR-0004 §2's
residency clause to this store by name, so nothing here may reach a remote
service. The database file is created owner-only (ADR-0004), following the
precedent :mod:`ai_assistant.memory.sqlite_store` set.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidResolutionError,
)
from ai_assistant.core.types import PermissionDecision, PermissionOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_OWNER_ONLY = 0o600


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
    """
    done = threading.Event()
    outcome: list[T] = []
    failure: list[Exception] = []

    def worker() -> None:
        try:
            outcome.append(fn(*args))
        except Exception as exc:  # relayed to the caller once the thread has finished
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

#: The epoch the sort key counts from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# The columns beside the ``data`` blob exist only so SQLite can order and
# constrain; the blob is the record. ``execution_id``, ``step_id`` and
# ``outcome`` (ADR-0044) are what the per-binding rule and the recovery query
# read — kept nullable so an existing pre-ADR-0044 table can grow them by
# ``ALTER`` and be backfilled (:meth:`_migrate`), identical to a table created
# fresh here.
_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS decisions("
    "id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
    "resolves TEXT, execution_id TEXT, step_id TEXT, outcome TEXT, "
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

    def __init__(self, *, path: Path | str) -> None:
        """Open (or create) the trail at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral trail.
                **Required, with no default.** Durability is the whole reason
                this implementation exists (ADR-0036 §2), so a default would let
                the ordinary construction produce a trail that forgets
                everything on restart — the failure the ADR argues against,
                reachable by omitting an argument. An ephemeral trail is
                available and has to be asked for.

        Raises:
            AuditError: If the database cannot be opened or initialised.
        """
        self._path = path if path == ":memory:" else str(Path(path))
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
                conn.execute(_CREATE_TABLE)
                self._migrate(conn)
                for statement in _INDEXES:
                    conn.execute(statement)
            if self._path != ":memory:":
                Path(self._path).chmod(_OWNER_ONLY)
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

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Add and backfill the ADR-0044 binding columns on a pre-existing table.

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
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
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

    # --- the write path ---------------------------------------------------

    async def record(self, decision: PermissionDecision) -> str:
        """Append ``decision`` and return its id.

        Raises:
            AuditError: If the decision does not satisfy its own model, or the
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
        conn = self._conn
        try:
            with conn:  # commits on success, rolls back on any exception
                # `BEGIN IMMEDIATE` rather than the deferred transaction sqlite3
                # would open at the INSERT: the checks below are *reads*, so a
                # deferred begin would leave them outside the write lock and let
                # a second process observe the same free id or unresolved
                # CONFIRM between them and the append. The asyncio lock closes
                # that within one process; this closes it against the file.
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT 1 FROM decisions WHERE id = ?", (snapshot.id,)).fetchone():
                    msg = (
                        f"decision {snapshot.id!r} is already recorded; the trail is "
                        f"append-only, so history cannot be rewritten by replaying a write"
                    )
                    raise DuplicateDecisionError(msg)
                if snapshot.resolves is not None:
                    self._check_resolution(snapshot)
                conn.execute(
                    "INSERT INTO decisions("
                    "id, decided_at_us, resolves, execution_id, step_id, outcome, data"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        snapshot.id,
                        _sort_key(snapshot.decided_at),
                        snapshot.resolves,
                        snapshot.execution_id,
                        snapshot.step_id,
                        snapshot.ruling.outcome.value,
                        snapshot.model_dump_json(),
                    ),
                )
        except sqlite3.Error as exc:
            msg = f"failed to record decision {snapshot.id!r}: {exc}"
            raise AuditError(msg) from exc

    def _check_resolution(self, decision: PermissionDecision) -> None:
        """Enforce ADR-0021 §1 and ADR-0044 §2's invariant on a resolving decision.

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

        Raises:
            AuditError: If the trail cannot be read.
        """
        async with self._lock:
            data = await _run_to_completion(self._pending_confirmation_sync, execution_id, step_id)
        return None if data is None else _decode(data)

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

    # --- erasure ----------------------------------------------------------

    async def clear(self) -> int:
        """Delete every decision, returning the number removed.

        Wholesale by design (ADR-0021 §4): the user may burn the book, and
        nobody may tear out a page.

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
        """
        conn = self._conn
        try:
            with conn:
                removed = conn.execute("DELETE FROM decisions").rowcount
        except sqlite3.Error as exc:
            msg = f"failed to clear the audit trail: {exc}"
            raise AuditError(msg) from exc
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

    Raises:
        AuditError: If the decision does not satisfy its own model.
    """
    try:
        return PermissionDecision.model_validate(decision.model_dump())
    except ValidationError as exc:
        msg = f"decision {decision.id!r} is not a valid record: {exc}"
        raise AuditError(msg) from exc


def _decode(data: str) -> PermissionDecision:
    """Rebuild a stored decision from its JSON.

    Raises:
        AuditError: If the stored row no longer validates — a corrupted or
            downgraded database, which is a fault to report rather than a record
            to hand on.
    """
    try:
        return PermissionDecision.model_validate_json(data)
    except ValidationError as exc:
        msg = f"the audit trail holds a record that no longer validates: {exc}"
        raise AuditError(msg) from exc


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
