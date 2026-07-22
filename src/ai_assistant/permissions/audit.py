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
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ai_assistant.core.errors import (
    AuditError,
    DuplicateDecisionError,
    InvalidResolutionError,
)
from ai_assistant.core.types import PermissionDecision, PermissionOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

_OWNER_ONLY = 0o600

#: The epoch the sort key counts from. Any fixed instant would do; this one is
#: conventional.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS decisions("
    "id TEXT PRIMARY KEY, decided_at_us INTEGER NOT NULL, "
    "resolves TEXT, data TEXT NOT NULL)",
    # A *unique* index, so the single-resolution rule survives even a bug in the
    # check below. SQLite treats NULLs as distinct, so it constrains resolving
    # rows only and leaves ordinary decisions unaffected.
    "CREATE UNIQUE INDEX IF NOT EXISTS decisions_resolves ON decisions(resolves)",
    "CREATE INDEX IF NOT EXISTS decisions_order ON decisions(decided_at_us DESC, id ASC)",
)

_ORDERED = "SELECT data FROM decisions ORDER BY decided_at_us DESC, id ASC"


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

    def __init__(self, *, path: Path | str = ":memory:") -> None:
        """Open (or create) the trail at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral trail.
                The default is ephemeral so a test or a throwaway composition
                needs no filesystem; a deployment passes a path, which is what
                makes the trail outlive the process.

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
            for statement in _SCHEMA:
                conn.execute(statement)
            conn.commit()
            if self._path != ":memory:":
                Path(self._path).chmod(_OWNER_ONLY)
        except (sqlite3.Error, OSError) as exc:
            conn.close()
            msg = f"failed to initialise the audit trail at {self._path!r}: {exc}"
            raise AuditError(msg) from exc
        return conn

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
            await asyncio.to_thread(self._record_sync, snapshot)
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
                    "INSERT INTO decisions(id, decided_at_us, resolves, data) VALUES (?, ?, ?, ?)",
                    (
                        snapshot.id,
                        _sort_key(snapshot.decided_at),
                        snapshot.resolves,
                        snapshot.model_dump_json(),
                    ),
                )
        except sqlite3.Error as exc:
            msg = f"failed to record decision {snapshot.id!r}: {exc}"
            raise AuditError(msg) from exc

    def _check_resolution(self, decision: PermissionDecision) -> None:
        """Enforce ADR-0021 §1's invariant on a resolving decision.

        Raises:
            InvalidResolutionError: If the referenced decision is absent, was not
                a ``CONFIRM``, is already resolved, describes a different
                subject, postdates the answer, or if the authorisation pointer
                does not match.
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
        ):
            msg = (
                f"decision {decision.id!r} resolves {confirmed.id!r} but rules on a "
                f"different action; a confirmation must answer the question that was asked"
            )
            raise InvalidResolutionError(msg)
        if decision.decided_at < confirmed.decided_at:
            msg = (
                f"decision {decision.id!r} is timestamped before the confirmation "
                f"{confirmed.id!r} it answers"
            )
            raise InvalidResolutionError(msg)
        _check_authorisation(decision)

    # --- the read path ----------------------------------------------------

    async def get(self, decision_id: str) -> PermissionDecision | None:
        """Return the decision with ``decision_id``, or ``None`` if absent.

        Raises:
            AuditError: If the trail cannot be read, or holds a record that no
                longer validates.
        """
        async with self._lock:
            row = await asyncio.to_thread(self._get_sync, decision_id)
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
        async with self._lock:
            rows = await asyncio.to_thread(self._ordered_sync, limit)
        return [_decode(row) for row in rows]

    async def export(self) -> list[PermissionDecision]:
        """Return every recorded decision, in the same order as :meth:`recent`.

        Raises:
            AuditError: If the trail cannot be read.
        """
        async with self._lock:
            rows = await asyncio.to_thread(self._ordered_sync, None)
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
            return await asyncio.to_thread(self._clear_sync)

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
