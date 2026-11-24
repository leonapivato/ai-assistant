"""A persistent :class:`~ai_assistant.core.protocols.ThingRecordStore` on SQLite.

ADR-0381 §3: whose each connection and source is, one record per thing, keyed by the
thing, naming its person and when it was recorded, on a file of its own in the hub's data
directory and nowhere else (§3:1).

**It stores; it does not decide.** Nothing here says which things the hub holds, what a
record means for a call, or whether a thing named exists. It holds one rule of its own,
because only the step that writes can decide it against every other writer: a write
writes only where the thing has no record, so a repeated write writes nothing (§3:4).
Nothing here changes or removes a record (§7:1).

**The start's writes** (§4:1). The composition root hands the store, as it opens, the
things the hub then holds (``held``); in the same step that opens the file, before the
store answers anything, a record naming the owner is written for each that has none, in
the order given, at one reading of the clock. A thing the hub no longer holds keeps its
record (§7:1). An opening handed nothing, such as a tool reading the file, writes nothing.

**The house style** of the stores beside this one: one owned connection, an
:class:`asyncio.Lock` around SQL run in a worker thread that the lock outlives (ADR-0054),
every member that writes one ``BEGIN IMMEDIATE`` transaction — which is how the contract's
one step holds across processes as well as coroutines — and an owner-only database file,
restricted before the first write (ADR-0004 §4). Every key and value is held verbatim and
compared as given, since SQLite's text comparison is exact.

**What binds a new file under the data directory, and how each is met.**

* *Mode* (ADR-0004 §4): the file and any sidecar beside it are ``0600``.
* *Backup* (ADR-0123): the artifact carries every file in the data directory but the
  exclusions ADR-0123 §3 lists; nothing excludes this one, so it is backed up with the
  rest, and nothing is registered.
* *Purge* (ADR-0126 §1): the unit is the directory, with no per-store list, so deleting
  the owner's data destroys this file with everything else (ADR-0381 §7), and nothing is
  registered.
* *Upgrades* (ADR-0326): the schema is version 1, written as ``PRAGMA user_version`` when
  the table is created. A file carrying tables under any other version is refused before
  anything is written: a later version is one this code does not understand (§5:3), and
  no release wrote an earlier one. Every later schema change ships its upgrade from the
  version it replaces (§4:1). The upgrade check covers it (§7:3,
  ``scripts/upgrade_stores.py``).

Where the file goes, and which things the hub holds, are the composition root's.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ThingRecordStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ThingKey,
    ThingRecord,
    ThingRecording,
    ThingRecordingKind,
    describe_untrusted,
)
from ai_assistant.permissions._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from contextlib import AbstractContextManager

__all__ = ["THING_RECORDS_SCHEMA_VERSION", "SqliteThingRecordStore"]

_log = structlog.get_logger(__name__)

_OWNER_ONLY: Final = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same pages the
#: database does, so ADR-0004 §4 reaches them too (#490).
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The schema this code writes and the only one it opens (ADR-0326 §5:3). No release
#: wrote an earlier version, so there is none to upgrade from yet.
THING_RECORDS_SCHEMA_VERSION: Final = 1

_SCHEMA: Final = (
    # One row per thing ever recorded, in the order recorded; the key is unique, so a
    # thing has at most one record (ADR-0381 §3:2), and no statement here updates or
    # deletes a row (§7:1).
    "CREATE TABLE records(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
    "identifier TEXT NOT NULL, person TEXT NOT NULL, recorded_at TEXT NOT NULL, "
    "UNIQUE(kind, identifier))",
)

_INSERT: Final = (
    "INSERT INTO records(kind, identifier, person, recorded_at) VALUES (?, ?, ?, ?) "
    "ON CONFLICT(kind, identifier) DO NOTHING"
)


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


def _key(value: object) -> ThingKey:
    """``value`` as a ``ThingKey`` whose every field passes validation, or a ``ValueError``.

    An instance is not proof of its own validity: ``model_copy(update=…)`` and
    ``model_construct`` skip validation, and a record the store committed from one would
    fail to read back. So the instance's contents are validated again before any I/O.
    """
    if not isinstance(value, ThingKey):
        msg = f"key must be a ThingKey, got {describe_untrusted(value)}"
        raise ValueError(msg)
    try:
        return ThingKey.model_validate(value.model_dump())
    except ValidationError as exc:
        msg = "key is not a valid ThingKey"
        raise ValueError(msg) from exc


def _person(value: object) -> str:
    """The owner's identity, or a ``ValueError`` before any I/O (ADR-0381 §3:3)."""
    if value != OWNER_PERSON_ID:
        msg = (
            "in this milestone a record names the owner's identity alone (ADR-0381 §3:3), "
            f"got {describe_untrusted(value)}"
        )
        raise ValueError(msg)
    return OWNER_PERSON_ID


def _instant(value: datetime) -> str:
    """An instant as the file holds it: ISO 8601 text, in UTC."""
    return value.astimezone(UTC).isoformat()


def _record_from(row: Sequence[Any]) -> ThingRecord:
    """A record from its row.

    Raises:
        ThingRecordStoreError: If the row does not make a record.
    """
    kind, identifier, person, recorded_at = row
    try:
        return ThingRecord.model_validate(
            {
                "key": {"kind": kind, "identifier": identifier},
                "person": person,
                "recorded_at": recorded_at,
            }
        )
    except (ValidationError, ValueError) as exc:
        msg = "a stored record row is corrupt"
        raise ThingRecordStoreError(msg) from exc


class SqliteThingRecordStore:
    """Whose each connection and source is, on SQLite (ADR-0381 §3)."""

    def __init__(
        self,
        *,
        path: Path | str,
        held: Sequence[ThingKey] = (),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Open the store at ``path``, creating it where new, and record the held things.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            held: The things the hub holds as it starts (ADR-0381 §4:1): in the step that
                opens the store, each that has no record is recorded as the owner's, in the
                order given. Empty, the default, for an opening that is not the hub's
                start, such as a tool reading the file; only the composition root hands
                the things the hub holds.
            now: The clock every instant the store records is read from.

        Raises:
            ValueError: If an entry of ``held`` is not a valid ``ThingKey``.
            ThingRecordStoreError: If the database cannot be opened or prepared, it
                carries tables under another schema version, or the clock's reading is
                not an aware instant where a held thing is to be recorded.
        """
        self._held = tuple(_key(one) for one in held)
        # ADR-0026 §2: every reading aware and converted to UTC, checked where it is read.
        self._clock = checked_clock(now, owner="SqliteThingRecordStore")
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection, create the schema where new, and record the held things.

        Raises:
            ThingRecordStoreError: If the database cannot be opened or prepared, it
                carries tables under another schema version, or the clock fails.
        """
        try:
            # Autocommit, so every transaction is an explicit BEGIN this module
            # controls: the driver's implicit ones are deferred, which would open a
            # read-decide-write member to interleaving.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` for a path carrying a NUL, which the driver raises rather
            # than a ``sqlite3.Error`` (#1933).
            msg = f"failed to open the thing record store at {self._path!r}: {exc}"
            raise ThingRecordStoreError(msg) from exc
        try:
            try:
                # Restricted before the first write: SQLite copies the file's mode onto
                # every journal it creates (ADR-0004 §4).
                self._restrict_permissions()
            except OSError as exc:
                msg = f"failed to open the thing record store at {self._path!r}: {exc}"
                raise ThingRecordStoreError(msg) from exc
            with self._transaction("prepare the thing record store", conn=conn) as held:
                self._prepare(held)
                self._record_held(held)
        except BaseException:
            conn.close()  # never leak the connection when opening fails
            raise
        return conn

    def _prepare(self, conn: sqlite3.Connection) -> None:
        """Check the file's version, and create the table where the file is new.

        Raises:
            ThingRecordStoreError: If the file carries tables under another version.
        """
        tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        # A file is created only where it holds no table and no label. Every other label
        # is refused before anything is written, a table-free file's included: a newer
        # one is a label this code does not understand (ADR-0326 §5:3), and a file that
        # holds tables under any other version, or a label with no tables, is not one
        # any release wrote.
        if tables[0] or version != 0:
            if not tables[0] or version != THING_RECORDS_SCHEMA_VERSION:
                msg = (
                    f"the thing record store at {self._path!r} has schema version "
                    f"{version}; this build opens only version {THING_RECORDS_SCHEMA_VERSION}"
                )
                raise ThingRecordStoreError(msg)
            return
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {THING_RECORDS_SCHEMA_VERSION}")
        _log.info("thing_record_store_created")

    def _record_held(self, conn: sqlite3.Connection) -> None:
        """Record each held thing that has no record as the owner's (ADR-0381 §4:1).

        One reading of the clock dates them all, taken only where one is missing, so an
        opening that writes nothing reads no clock. Which things were recorded is not
        logged: which accounts and sources the owner has is the owner's.
        """
        missing = [
            key
            for key in self._held
            if conn.execute(
                "SELECT 1 FROM records WHERE kind = ? AND identifier = ?",
                (key.kind.value, key.identifier),
            ).fetchone()
            is None
        ]
        if not missing:
            return
        at = _instant(self._now())
        written = 0
        for key in missing:
            cursor = conn.execute(_INSERT, (key.kind.value, key.identifier, OWNER_PERSON_ID, at))
            written += cursor.rowcount
        _log.info("thing_records_written_at_start", recorded=written)

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
        contract's one step, and what keeps a repeated write from writing anything.

        Raises:
            ThingRecordStoreError: If the backend fails at any point.
        """
        return transaction(
            conn or self._conn, what, error=ThingRecordStoreError, immediate=immediate
        )

    async def _run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        """Run one member's SQL under the lock, in a worker thread the lock outlives."""
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _now(self) -> datetime:
        """One reading of the clock, taken before the write it dates changes anything.

        Raises:
            ThingRecordStoreError: If the reading is not an aware instant (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            msg = f"the thing record store cannot record its clock's reading: {exc}"
            raise ThingRecordStoreError(msg) from exc

    @staticmethod
    def _row(conn: sqlite3.Connection, key: ThingKey) -> Sequence[Any] | None:
        row: Sequence[Any] | None = conn.execute(
            "SELECT kind, identifier, person, recorded_at FROM records "
            "WHERE kind = ? AND identifier = ?",
            (key.kind.value, key.identifier),
        ).fetchone()
        return row

    # --- reads ---------------------------------------------------------------------

    async def whose(self, key: ThingKey) -> ThingRecord | None:
        """Read the record of the thing ``key`` names, or ``None`` where it has none.

        Raises:
            ValueError: If ``key`` is malformed.
            ThingRecordStoreError: If the store cannot be read, or the row is corrupt.
        """
        held = _key(key)
        return await self._run(self._whose_sync, held)

    def _whose_sync(self, key: ThingKey) -> ThingRecord | None:
        with self._transaction("read a thing's record", immediate=False) as conn:
            row = self._row(conn, key)
        return None if row is None else _record_from(row)

    async def export(self) -> tuple[ThingRecord, ...]:
        """Every record, in the order recorded.

        Raises:
            ThingRecordStoreError: If the store cannot be read, or a row is corrupt.
        """
        return await self._run(self._export_sync)

    def _export_sync(self) -> tuple[ThingRecord, ...]:
        with self._transaction("export the thing records", immediate=False) as conn:
            rows = conn.execute(
                "SELECT kind, identifier, person, recorded_at FROM records ORDER BY seq"
            ).fetchall()
        return tuple(_record_from(row) for row in rows)

    # --- writes --------------------------------------------------------------------

    async def record_whose(self, key: ThingKey, *, person: str) -> ThingRecording:
        """Record that ``key``'s thing is ``person``'s, where no record stands, in one step.

        Raises:
            ValueError: If an argument is malformed, or ``person`` is not the owner's.
            ThingRecordStoreError: If the store cannot be read or written, or the record
                that stands is corrupt.
        """
        held = _key(key)
        whose = _person(person)
        return await self._run(self._record_sync, held, whose)

    def _record_sync(self, key: ThingKey, person: str) -> ThingRecording:
        with self._transaction("record whose a thing is") as conn:
            standing = self._row(conn, key)
            if standing is not None:
                return ThingRecording(
                    kind=ThingRecordingKind.ALREADY_RECORDED, record=_record_from(standing)
                )
            record = ThingRecord(key=key, person=person, recorded_at=self._now())
            conn.execute(
                _INSERT,
                (key.kind.value, key.identifier, record.person, _instant(record.recorded_at)),
            )
        _log.info("thing_recorded", kind=key.kind.value)
        return ThingRecording(kind=ThingRecordingKind.RECORDED, record=record)
