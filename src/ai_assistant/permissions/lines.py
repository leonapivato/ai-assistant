"""A persistent :class:`~ai_assistant.core.protocols.PermissionLineStore` on SQLite.

ADR-0367 §3:5, §3:6 and ADR-0376 §4:8: the lines people make, grants and limits, each under
an identifier never reused, with who made it and when, and each removal, by whom and when,
keeping the removed line, on a file of its own in the hub's data directory.

**It stores; it does not decide.** Nothing here says whether a line covers a call or which
of several decides (the check's, ADR-0367 §4), nor whether a line's action or connections
exist, nor whether the person acting may make or remove it (the acts', ADR-0376 §4:5, §6).
It holds one rule of its own, because only the step that writes can decide it against
every other writer: a making that repeats a standing line of the same kind with exactly the
same parts writes nothing and answers with that line (ADR-0376 §4:5).

**It starts empty** (ADR-0376 §3:3): creating the file seeds no line. A tool's default line
is its declaration's and is never written here.

**Not ADR-0097's source grants.** :mod:`ai_assistant.permissions.grants` keeps those on a
file of its own; ADR-0367 §14 keeps the two apart, and nothing here reads, cites or
checks one as the other.

**The house style** of the stores beside this one: one owned connection, an
:class:`asyncio.Lock` around SQL run in a worker thread that the lock outlives (ADR-0054),
every member that writes one ``BEGIN IMMEDIATE`` transaction — which is how the contract's
one step holds across processes as well as coroutines — and an owner-only database file,
restricted before the first write (ADR-0004 §4). Every id and value is held verbatim and
compared as given, since SQLite's text comparison is exact.

**What binds a new file under the data directory, and how each is met.**

* *Mode* (ADR-0004 §4): the file and any sidecar beside it are ``0600``.
* *Backup* (ADR-0123): the artifact carries every file in the data directory but the
  exclusions ADR-0123 §3 lists; nothing excludes this one, so it is backed up with the
  rest, and nothing is registered.
* *Purge* (ADR-0126 §1): the unit is the directory, with no per-store list, so deleting
  the owner's data destroys this file with everything else, and nothing is registered.
* *Upgrades* (ADR-0326): the schema is version 1, written as ``PRAGMA user_version`` when
  the table is created. A file carrying tables under any other version is refused before
  anything is written: a later version is one this code does not understand (§5:3), and
  no release wrote an earlier one. Every later schema change ships its upgrade from the
  version it replaces (§4:1). The upgrade check covers it (§7:3,
  ``scripts/upgrade_stores.py``).

Where the file goes is the composition root's.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import (
    LineMaking,
    LineMakingKind,
    LineParts,
    LineRemoval,
    LineRemovalKind,
    PermissionLine,
    describe_untrusted,
    encodable_text,
)
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

__all__ = ["PERMISSION_LINES_SCHEMA_VERSION", "SqlitePermissionLineStore"]

_log = structlog.get_logger(__name__)

_OWNER_ONLY: Final = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same pages the
#: database does, so ADR-0004 §4 reaches them too (#490).
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The schema this code writes and the only one it opens (ADR-0326 §5:3). No release
#: wrote an earlier version, so there is none to upgrade from yet.
PERMISSION_LINES_SCHEMA_VERSION: Final = 1

#: How many times a making re-mints an identifier that a held line already carries before
#: it fails as a store fault.
_MINT_BUDGET: Final = 8

_SCHEMA: Final = (
    # One row per line ever made, in the order made, kept when removed. `seq` orders;
    # `id` is the line's identifier, unique among every row, removed ones included, so it
    # is never reused. The parts a grant alone has are NULL on a limit, and a thing or a
    # condition a line does not name is NULL.
    "CREATE TABLE lines(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE, "
    "kind TEXT NOT NULL, who TEXT NOT NULL, action TEXT NOT NULL, thing TEXT, how TEXT, "
    "bar TEXT, condition TEXT, made_by TEXT NOT NULL, made_at TEXT NOT NULL, "
    "removed_by TEXT, removed_at TEXT)",
    # The standing lines, which the check reads on every call (ADR-0367 §4:1), in the
    # order made, without walking the removed ones.
    "CREATE INDEX lines_standing ON lines(seq) WHERE removed_at IS NULL",
)

_COLUMNS: Final = (
    "id, kind, who, action, thing, how, bar, condition, made_by, made_at, removed_by, removed_at"
)
_FIELDS: Final = tuple(name.strip() for name in _COLUMNS.split(","))


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    Duplicated from :mod:`ai_assistant.permissions.grants`, whose docstring carries the
    whole argument, rather than imported: each SQLite store carries its own, and #506 and
    #563 track consolidating the family. In short: a cancelled caller keeps the lock until
    the thread using the connection has returned, every failure the worker sees is
    relayed, and the completion wait is submitted at most once (#697).
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _random_id() -> str:
    """A fresh line identifier: ``line:``, then 128 random bits as lowercase hex."""
    return f"line:{uuid4().hex}"


def _checked(value: object, *, name: str) -> str:
    """A non-blank ``str`` with a UTF-8 encoding, or a ``ValueError`` before any I/O."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return encodable_text(value)
    except ValueError as exc:
        msg = f"{name} must be text with a UTF-8 encoding"
        raise ValueError(msg) from exc


def _parts(value: object) -> LineParts:
    """``value`` as ``LineParts`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, and a line the store committed from one would
    fail to read back. So the instance's contents are validated again before any I/O.
    """
    if not isinstance(value, LineParts):
        msg = f"parts must be a LineParts, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return LineParts.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = "parts is not a valid LineParts"
        raise ValueError(msg) from exc


def _instant(value: datetime) -> str:
    """An instant as the file holds it: ISO 8601 text, in UTC."""
    return value.astimezone(UTC).isoformat()


def _line_from(row: Sequence[Any]) -> PermissionLine:
    """A line from its row.

    Raises:
        PermissionLineStoreError: If the row does not make a line.
    """
    try:
        return PermissionLine.model_validate(dict(zip(_FIELDS, row, strict=True)))
    except (ValidationError, ValueError) as exc:
        msg = "a stored line row is corrupt"
        raise PermissionLineStoreError(msg) from exc


class SqlitePermissionLineStore:
    """The lines people make, on SQLite (ADR-0367 §3:5, §3:6; ADR-0376 §4:8)."""

    def __init__(
        self,
        *,
        path: Path | str,
        now: Callable[[], datetime] = _utcnow,
        new_id: Callable[[], str] = _random_id,
    ) -> None:
        """Open the store at ``path``, creating it, empty, where it is new.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: The clock every instant the store records is read from.
            new_id: Mints a line's identifier. An identifier a held line already carries,
                a removed one's included, is minted again.

        Raises:
            PermissionLineStoreError: If the database cannot be opened or prepared, or it
                carries tables under another schema version.
        """
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="SqlitePermissionLineStore")
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection, and create the schema where the file is new.

        Raises:
            PermissionLineStoreError: If the database cannot be opened or prepared, or it
                carries tables under another schema version.
        """
        try:
            # Autocommit, so every transaction is an explicit BEGIN this module
            # controls: the driver's implicit ones are deferred, which would open a
            # read-decide-write member to interleaving.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` for a path carrying a NUL, which the driver raises rather
            # than a ``sqlite3.Error`` (#1933).
            msg = f"failed to open the line store at {self._path!r}: {exc}"
            raise PermissionLineStoreError(msg) from exc
        try:
            try:
                # Restricted before the first write: SQLite copies the file's mode onto
                # every journal it creates (ADR-0004 §4).
                self._restrict_permissions()
            except OSError as exc:
                msg = f"failed to open the line store at {self._path!r}: {exc}"
                raise PermissionLineStoreError(msg) from exc
            with self._transaction("prepare the line store", conn=conn) as held:
                self._prepare(held)
        except BaseException:
            conn.close()  # never leak the connection when opening fails
            raise
        return conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        """Check the file's version, and create the table where the file is new.

        Raises:
            PermissionLineStoreError: If the file carries tables under another version.
        """
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        # A file is created only where it holds no table and no label. Every other label
        # is refused before anything is written, a table-free file's included: a newer
        # one is a label this code does not understand (ADR-0326 §5:3), and a file that
        # holds tables under any other version, or a label with no tables, is not one
        # any release wrote.
        if tables[0] or version != 0:
            if not tables[0] or version != PERMISSION_LINES_SCHEMA_VERSION:
                msg = (
                    f"the line store at {self._path!r} has schema version {version}; "
                    f"this build opens only version {PERMISSION_LINES_SCHEMA_VERSION}"
                )
                raise PermissionLineStoreError(msg)
            return
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {PERMISSION_LINES_SCHEMA_VERSION}")
        _log.info("permission_line_store_created")

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case, and a *symlink* under a sidecar's name is
        skipped rather than followed, since ``chmod`` follows links.
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

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # --- internals -----------------------------------------------------------------

    def _transaction(
        self, what: str, *, immediate: bool = True, conn: sqlite3.Connection | None = None
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so the read each write decides on
        cannot be interleaved by another writer, in this process or another: that is the
        contract's one step, and what keeps a repeated making from making a second line.

        Raises:
            PermissionLineStoreError: If the backend fails at any point.
        """
        return transaction(
            conn or self._conn, what, error=PermissionLineStoreError, immediate=immediate
        )

    async def _run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        """Run one member's SQL under the lock, in a worker thread the lock outlives."""
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            PermissionLineStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the line store cannot record its clock's reading: {exc}"
            raise PermissionLineStoreError(msg) from exc

    def _mint(self, conn: sqlite3.Connection) -> str:
        """A new line's identifier that no line carries, removed ones included.

        Raises:
            PermissionLineStoreError: If the factory kept minting a held identifier, or
                minted something that is not a non-blank encodable identifier.
        """
        for _ in range(_MINT_BUDGET):
            try:
                minted = _checked(self._new_id(), name="a minted identifier")
            except ValueError as exc:
                msg = "the line store minted an identifier that is not one"
                raise PermissionLineStoreError(msg) from exc
            held = conn.execute("SELECT 1 FROM lines WHERE id = ?", (minted,)).fetchone()
            if held is None:
                return minted
        msg = f"the line store minted a held identifier {_MINT_BUDGET} times running"
        raise PermissionLineStoreError(msg)

    @staticmethod
    def _row(conn: sqlite3.Connection, line_id: str) -> Sequence[Any] | None:
        row: Sequence[Any] | None = conn.execute(
            f"SELECT {_COLUMNS} FROM lines WHERE id = ?",  # noqa: S608 — only constants are interpolated
            (line_id,),
        ).fetchone()
        return row

    # --- reads ---------------------------------------------------------------------

    async def standing(self) -> tuple[PermissionLine, ...]:
        """Every standing line, in the order made.

        Raises:
            PermissionLineStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._run(self._standing_sync)

    def _standing_sync(self) -> tuple[PermissionLine, ...]:
        with self._transaction("list the standing lines", immediate=False) as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM lines WHERE removed_at IS NULL ORDER BY seq"  # noqa: S608 — only constants are interpolated
            ).fetchall()
        return tuple(_line_from(row) for row in rows)

    async def line(self, line_id: str) -> PermissionLine | None:
        """Read one line by its identifier, standing or removed.

        Raises:
            ValueError: If ``line_id`` is not a non-blank ``str``.
            PermissionLineStoreError: If the store cannot be read, or the row is corrupt.
        """
        held = _checked(line_id, name="line_id")
        return await self._run(self._line_sync, held)

    def _line_sync(self, line_id: str) -> PermissionLine | None:
        with self._transaction("read a line", immediate=False) as conn:
            row = self._row(conn, line_id)
        return None if row is None else _line_from(row)

    # --- writes --------------------------------------------------------------------

    async def record_making(self, parts: LineParts, *, by: str) -> LineMaking:
        """Record a line with ``parts`` by ``by``'s act, or find the standing one it repeats.

        Raises:
            ValueError: If an argument is malformed.
            PermissionLineStoreError: If the store cannot be read or written.
        """
        made = _parts(parts)
        maker = _checked(by, name="by")
        return await self._run(self._make_sync, made, maker)

    def _make_sync(self, parts: LineParts, by: str) -> LineMaking:
        with self._transaction("record a line's making") as conn:
            # `IS` rather than `=`, so a part a line does not name, held as NULL, matches
            # the same absence; every other value compares exactly, as given.
            same = conn.execute(
                f"SELECT {_COLUMNS} FROM lines WHERE removed_at IS NULL "  # noqa: S608 — only constants are interpolated
                "AND kind = ? AND who = ? AND action = ? AND thing IS ? AND how IS ? "
                "AND bar IS ? AND condition IS ? ORDER BY seq LIMIT 1",
                (
                    parts.kind.value,
                    parts.who,
                    parts.action,
                    parts.thing,
                    None if parts.how is None else parts.how.value,
                    None if parts.bar is None else parts.bar.value,
                    parts.condition,
                ),
            ).fetchone()
            if same is not None:
                return LineMaking(kind=LineMakingKind.UNCHANGED, line=_line_from(same))
            line_id = self._mint(conn)
            line = PermissionLine(id=line_id, **parts.model_dump(), made_by=by, made_at=self._now())
            conn.execute(
                "INSERT INTO lines(id, kind, who, action, thing, how, bar, condition, "
                "made_by, made_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    line.id,
                    line.kind.value,
                    line.who,
                    line.action,
                    line.thing,
                    None if line.how is None else line.how.value,
                    None if line.bar is None else line.bar.value,
                    line.condition,
                    line.made_by,
                    _instant(line.made_at),
                ),
            )
        _log.info("permission_line_made", kind=line.kind.value)
        return LineMaking(kind=LineMakingKind.MADE, line=line)

    async def record_removal(self, line_id: str, *, by: str) -> LineRemoval:
        """Record the removal of a standing line by ``by``'s act, keeping it, in one step.

        Raises:
            ValueError: If an argument is malformed.
            PermissionLineStoreError: If the store cannot be read or written.
        """
        held = _checked(line_id, name="line_id")
        remover = _checked(by, name="by")
        return await self._run(self._remove_sync, held, remover)

    def _remove_sync(self, line_id: str, by: str) -> LineRemoval:
        with self._transaction("record a line's removal") as conn:
            row = self._row(conn, line_id)
            if row is None:
                return LineRemoval(kind=LineRemovalKind.NOT_STANDING)
            line = _line_from(row)
            if not line.standing:
                return LineRemoval(kind=LineRemovalKind.NOT_STANDING)
            at = self._now()
            removed = PermissionLine.model_validate(
                {**line.model_dump(), "removed_by": by, "removed_at": at}
            )
            conn.execute(
                "UPDATE lines SET removed_by = ?, removed_at = ? WHERE id = ?",
                (by, _instant(at), line_id),
            )
        _log.info("permission_line_removed", kind=removed.kind.value)
        return LineRemoval(kind=LineRemovalKind.REMOVED, line=removed)
