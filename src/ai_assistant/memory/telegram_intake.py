"""A persistent :class:`~ai_assistant.core.protocols.TelegramIntakeRecord` on SQLite.

The Telegram line's own durable record (ADR-0323): the reader's intake — which updates
it took in, by which activation, and which non-text messages it answered (§5:8 to
§5:10) — and the records of the line's own calls (§13:2). It sits under
``Settings.data_dir``, so it is the assistant's own store (ADR-0155 §1:2) and Tier 1,
and it holds no message text.

**Why it lives in ``memory/``.** Every peer durable store whose contract is its own
Protocol does — :mod:`~ai_assistant.memory.conversation_store`, whose ``take_in`` is
the hub chat's version of this bookkeeping (ADR-0293 §6:6), among them — because the
architecture map names no subsystem for it and inventing one is an ADR's decision
rather than an implementation lane's. Nothing here imports another store, and nothing
reads this one but the line.

**The house style** of :mod:`~ai_assistant.planning.sqlite_store` and the stores
beside this one: one owned connection, an :class:`asyncio.Lock` around SQL run in a
worker thread that the lock outlives (ADR-0054), every write one ``BEGIN IMMEDIATE``
transaction — which is how the contract's exclusion holds across processes as well as
coroutines — and an owner-only database file, restricted before the first write
(ADR-0004 §4).

**What binds a new file under the data directory, and how each is met.**

* *Mode* (ADR-0004 §4): the file and any sidecar beside it are ``0600``.
* *Backup* (ADR-0123): the artifact carries every file in the data directory but the
  exclusions ADR-0123 §3 lists for a file that may not leave the device. No clause
  forbids this record leaving it — it holds update ids, activation ids and call
  outcomes, as the conversation store's bookkeeping does — so it is backed up like that
  store, and nothing is registered.
* *Purge* (ADR-0126 §1): the unit is the directory, with no per-store list, so the
  purge destroys this file with everything else, and nothing is registered.
* *Schema marker*: ``PRAGMA user_version`` is written at creation, and a file carrying
  tables under any other version is refused before anything is written. The episode
  record format marker (ADR-0275 §12) is not written: this store holds no episode.

Where the file goes is the composition root's, which names every store's file.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import TelegramIntakeRecordError
from ai_assistant.core.types import (
    Identifier,
    TelegramCallKind,
    TelegramCallRecord,
    TelegramIntake,
    TelegramIntakeExport,
    TelegramIntakeKind,
    TelegramOutcome,
    TelegramPollClaim,
    describe_untrusted,
)
from ai_assistant.memory._transactions import transaction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from contextlib import AbstractContextManager

_OWNER_ONLY: Final = 0o600

#: The sidecars SQLite may keep beside a database file, each holding the same pages
#: the database does, so ADR-0004 §4 reaches them too (#490).
_SIDECARS: Final = ("-journal", "-wal", "-shm")

#: The schema this code writes and the only one it opens. A fresh store: there is no
#: earlier version to read or migrate.
_SCHEMA_VERSION: Final = 1

#: How many update ids one call names at most, as ``ConversationStore``'s positions.
_MAX_NAMED: Final = 1000

#: One past the largest update id: the signed 64-bit ceiling a SQLite integer holds.
_ID_CEILING: Final = 2**63

#: How many finished polls and typing indicators are kept by default, the newest. A
#: poll is claimed every long-poll wait, so an unbounded default would grow the file
#: by one row a minute for as long as the line runs. Duplicated in the canonical fake
#: rather than shared: ``ai_assistant.testing`` may not import a subsystem.
DEFAULT_KEPT_CALLS: Final = 1000

#: How many times a claim re-mints an attempt id that is already held before it fails.
_MINT_BUDGET: Final = 8

_ROUTINE_KINDS: Final = (TelegramCallKind.POLL.value, TelegramCallKind.TYPING.value)

_IDENTIFIER: Final[TypeAdapter[str]] = TypeAdapter(Identifier)

_SCHEMA: Final = (
    # One row per update dealt with: its id, how, and by which activation. No text.
    "CREATE TABLE IF NOT EXISTS intake("
    "update_id INTEGER PRIMARY KEY, kind TEXT NOT NULL, activation_id TEXT)",
    # One row per call claimed, numbered in claim order by an AUTOINCREMENT key so a
    # number is never reused once its row is dropped. `attempt` is the record's id.
    "CREATE TABLE IF NOT EXISTS calls("
    "seq INTEGER PRIMARY KEY AUTOINCREMENT, attempt TEXT NOT NULL UNIQUE, "
    "kind TEXT NOT NULL, sent_offset INTEGER, update_id INTEGER, activation_id TEXT, "
    "finished INTEGER NOT NULL DEFAULT 0, failure TEXT)",
    "CREATE INDEX IF NOT EXISTS calls_by_update ON calls(kind, update_id)",
    "CREATE INDEX IF NOT EXISTS calls_by_activation ON calls(kind, activation_id)",
    # The confirmation owed: one row, its offset NULL where none is owed.
    "CREATE TABLE IF NOT EXISTS owed(id INTEGER PRIMARY KEY CHECK(id = 1), offset_owed INTEGER)",
    "INSERT OR IGNORE INTO owed(id, offset_owed) VALUES (1, NULL)",
)

_CALL_COLUMNS: Final = "attempt, kind, sent_offset, update_id, activation_id, finished, failure"


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    Duplicated from :mod:`ai_assistant.planning.sqlite_store`, whose docstring carries
    the whole argument, rather than shared, for the reason recorded there and in
    :mod:`ai_assistant.memory.notification_outbox`: subsystems depend on ADR-0060's
    obligation and not on one way of meeting it. In short: a cancelled caller keeps
    the lock until the thread using the connection has returned, every failure the
    worker sees is relayed, and the completion wait is submitted at most once (#697).
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


def _random_attempt() -> str:
    """A fresh attempt id: 128 random bits, as lowercase hex."""
    return uuid4().hex


def _checked_update_id(value: object, *, ceiling: int = _ID_CEILING) -> int:
    """Check one update id before any I/O.

    Raises:
        ValueError: If ``value`` is not an ``int`` (a ``bool`` is not one) in
            ``[0, ceiling)``.
    """
    if type(value) is not int or not 0 <= value < ceiling:
        msg = f"an update id must be an int in [0, {ceiling}), got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _checked_update_ids(values: object) -> tuple[int, ...]:
    """Check a caller's sequence of update ids once, before any I/O (ADR-0065).

    Raises:
        ValueError: If ``values`` is a ``str`` or not a sequence, holds more than
            1000 ids, or holds one that is not an update id.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        msg = f"update_ids must be a sequence of int, got {describe_untrusted(values)}"
        raise ValueError(msg)
    held = tuple(values)
    if len(held) > _MAX_NAMED:
        msg = f"update_ids holds {len(held)}; at most {_MAX_NAMED} are named at once"
        raise ValueError(msg)
    for one in held:
        _checked_update_id(one)
    return held


def _checked_identifier(value: object, *, name: str) -> str:
    """Check an activation id or an attempt through ``core``'s own identifier type.

    Raises:
        ValueError: If ``value`` is not a non-blank ``str``.
    """
    try:
        return _IDENTIFIER.validate_python(value, strict=True)
    except ValidationError as exc:
        msg = f"{name} must be a non-blank str, got {describe_untrusted(value)}"
        raise ValueError(msg) from exc


def _checked_outcome(value: object) -> TelegramOutcome:
    """Check :meth:`SqliteTelegramIntakeRecord.finish`'s outcome before any I/O.

    Raises:
        ValueError: If ``value`` is not a ``TelegramOutcome``.
    """
    if not isinstance(value, TelegramOutcome):
        msg = f"outcome must be a TelegramOutcome, got {describe_untrusted(value)}"
        raise ValueError(msg)
    return value


def _blocks_another(record: TelegramCallRecord) -> bool:
    """Whether an earlier claim on the same subject forbids a new one (§5:9, §6:3).

    Only a call that came back with a failure Telegram did not get or said it did not
    send leaves room for another.
    """
    return not (record.finished and record.failure is not None and record.failure.retryable)


def _intake_from(row: Sequence[object]) -> TelegramIntake:
    """Rebuild one intake row, refusing a corrupt one as the seam's error.

    Raises:
        TelegramIntakeRecordError: If the row does not make an intake entry.
    """
    try:
        return TelegramIntake.model_validate(
            {"update_id": row[0], "kind": row[1], "activation_id": row[2]}
        )
    except ValidationError as exc:
        msg = "a stored intake row is corrupt"
        raise TelegramIntakeRecordError(msg) from exc


def _call_from(row: Sequence[object]) -> TelegramCallRecord:
    """Rebuild one call row, refusing a corrupt one as the seam's error.

    Raises:
        TelegramIntakeRecordError: If the row does not make a call record.
    """
    finished = row[5]
    if finished not in {0, 1} or type(finished) is not int:
        msg = "a stored call row is corrupt"
        raise TelegramIntakeRecordError(msg)
    try:
        return TelegramCallRecord.model_validate(
            {
                "attempt": row[0],
                "kind": row[1],
                "offset": row[2],
                "update_id": row[3],
                "activation_id": row[4],
                "finished": bool(finished),
                "failure": row[6],
            }
        )
    except ValidationError as exc:
        msg = "a stored call row is corrupt"
        raise TelegramIntakeRecordError(msg) from exc


class SqliteTelegramIntakeRecord:
    """The Telegram line's intake and call records, on SQLite (ADR-0323 §5:8, §13:2)."""

    def __init__(
        self,
        *,
        path: Path | str,
        kept_calls: int = DEFAULT_KEPT_CALLS,
        new_id: Callable[[], str] = _random_attempt,
    ) -> None:
        """Open (or create) the record at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral record.
            kept_calls: How many finished polls and typing indicators are kept, the
                newest; at least 1.
            new_id: The attempt id factory every claim mints through.

        Raises:
            ValueError: If ``kept_calls`` is not an ``int`` of at least 1.
            TelegramIntakeRecordError: If the database cannot be opened or prepared,
                or it carries tables under another schema version.
        """
        if type(kept_calls) is not int or kept_calls < 1:
            msg = f"kept_calls must be an int of at least 1, got {describe_untrusted(kept_calls)}"
            raise ValueError(msg)
        self._kept_calls = kept_calls
        self._new_id = new_id
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error.

        Raises:
            TelegramIntakeRecordError: If the database cannot be opened or prepared,
                or it carries tables under another schema version.
        """
        try:
            # Autocommit, so every transaction is an explicit BEGIN this module
            # controls: the driver's implicit ones are deferred, which would open a
            # read-decide-write member to the interleaving the exclusion forbids.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError, ValueError) as exc:
            # ``ValueError`` for a path carrying a NUL, which the driver raises
            # rather than a ``sqlite3.Error`` (#1933).
            msg = f"failed to open the telegram intake record at {self._path!r}: {exc}"
            raise TelegramIntakeRecordError(msg) from exc
        try:
            # Restricted before the first write: SQLite copies the file's mode onto
            # every journal it creates, and an interrupted write leaves that journal
            # holding Tier 1 pages (ADR-0004 §4).
            self._restrict_permissions()
            conn.execute("BEGIN IMMEDIATE")
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if tables and version != _SCHEMA_VERSION:
                conn.execute("ROLLBACK")
                msg = (
                    f"the telegram intake record at {self._path!r} has schema version "
                    f"{version}; this build opens only version {_SCHEMA_VERSION}"
                )
                raise TelegramIntakeRecordError(msg)
            for statement in _SCHEMA:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.execute("COMMIT")
        except TelegramIntakeRecordError:
            conn.close()
            raise
        except (sqlite3.Error, OSError) as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open the telegram intake record at {self._path!r}: {exc}"
            raise TelegramIntakeRecordError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        """Make the database file and any sidecar beside it owner-only (ADR-0004 §4).

        A missing sidecar is the ordinary case, and a *symlink* under a sidecar's
        name is skipped rather than followed, since ``chmod`` follows links.
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
        self, what: str, *, immediate: bool = True
    ) -> AbstractContextManager[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read the member's write
        depends on cannot be interleaved by another writer, in this process or
        another.

        Raises:
            TelegramIntakeRecordError: If the backend fails at any point.
        """
        return transaction(self._conn, what, error=TelegramIntakeRecordError, immediate=immediate)

    async def _run[T](self, fn: Callable[..., T], /, *args: object) -> T:
        """Run one member's SQL under the lock, in a worker thread the lock outlives."""
        async with self._lock:
            return await _run_to_completion(fn, *args)

    def _mint(self, conn: sqlite3.Connection) -> str:
        """Mint an attempt id the record does not hold, inside the open transaction.

        Raises:
            TelegramIntakeRecordError: If the factory kept minting one it holds, or
                minted something that is not an identifier.
        """
        for _ in range(_MINT_BUDGET):
            try:
                minted = _checked_identifier(self._new_id(), name="a minted attempt")
            except ValueError as exc:
                msg = "the attempt id factory minted something that is not an identifier"
                raise TelegramIntakeRecordError(msg) from exc
            if conn.execute("SELECT 1 FROM calls WHERE attempt = ?", (minted,)).fetchone() is None:
                return minted
        msg = f"the attempt id factory minted a held id {_MINT_BUDGET} times running"
        raise TelegramIntakeRecordError(msg)

    @staticmethod
    def _insert_call(conn: sqlite3.Connection, record: TelegramCallRecord) -> None:
        conn.execute(
            "INSERT INTO calls(attempt, kind, sent_offset, update_id, activation_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.attempt,
                record.kind.value,
                record.offset,
                record.update_id,
                record.activation_id,
            ),
        )

    @staticmethod
    def _owed(conn: sqlite3.Connection) -> int | None:
        """The offset owed, read inside the open transaction.

        Raises:
            TelegramIntakeRecordError: If the stored row is missing or corrupt.
        """
        row = conn.execute("SELECT offset_owed FROM owed WHERE id = 1").fetchone()
        if row is None:
            msg = "the telegram intake record lost its offset row"
            raise TelegramIntakeRecordError(msg)
        owed = row[0]
        if owed is not None and (type(owed) is not int or not 0 <= owed < _ID_CEILING):
            msg = "the stored offset is corrupt"
            raise TelegramIntakeRecordError(msg)
        return owed

    @staticmethod
    def _subject_calls(
        conn: sqlite3.Connection, kind: TelegramCallKind, column: str, subject: object
    ) -> list[TelegramCallRecord]:
        rows = conn.execute(
            f"SELECT {_CALL_COLUMNS} FROM calls WHERE kind = ? AND {column} = ? "  # noqa: S608 — only constants are interpolated
            "ORDER BY seq ASC",
            (kind.value, subject),
        ).fetchall()
        return [_call_from(row) for row in rows]

    # --- the intake record ---------------------------------------------------------

    async def take_in(self, update_ids: Sequence[int], *, activation_id: str) -> tuple[int, ...]:
        """Mark each named update the record does not hold taken in, in one transaction.

        Raises:
            ValueError: If an argument is malformed.
            TelegramIntakeRecordError: If the record cannot be written.
        """
        named = _checked_update_ids(update_ids)
        activation = _checked_identifier(activation_id, name="activation_id")
        return await self._run(self._take_in_sync, named, activation)

    def _take_in_sync(self, named: tuple[int, ...], activation: str) -> tuple[int, ...]:
        with self._transaction("record updates taken in") as conn:
            marked: list[int] = []
            for one in sorted(set(named)):
                inserted = conn.execute(
                    "INSERT OR IGNORE INTO intake(update_id, kind, activation_id) VALUES (?, ?, ?)",
                    (one, TelegramIntakeKind.TAKEN_IN.value, activation),
                )
                if inserted.rowcount == 1:
                    marked.append(one)
            return tuple(marked)

    async def recorded(self, update_ids: Sequence[int]) -> Mapping[int, TelegramIntake]:
        """Return what the record holds of each named update.

        Raises:
            ValueError: If ``update_ids`` is malformed.
            TelegramIntakeRecordError: If the record cannot be read, or a row is
                corrupt.
        """
        named = _checked_update_ids(update_ids)
        if not named:
            return {}
        rows = await self._run(self._recorded_sync, tuple(sorted(set(named))))
        found: dict[int, TelegramIntake] = {}
        for row in rows:
            entry = _intake_from(row)
            found[entry.update_id] = entry
        return found

    def _recorded_sync(self, named: tuple[int, ...]) -> list[Any]:
        placeholders = ", ".join("?" for _ in named)
        with self._transaction("read updates recorded", immediate=False) as conn:
            return conn.execute(
                "SELECT update_id, kind, activation_id FROM intake "  # noqa: S608 — only placeholders are interpolated
                f"WHERE update_id IN ({placeholders}) ORDER BY update_id ASC",
                named,
            ).fetchall()

    async def confirm_through(self, update_id: int) -> None:
        """Owe Telegram the confirmation of every update up to ``update_id``.

        Raises:
            ValueError: If ``update_id`` is malformed.
            TelegramIntakeRecordError: If the record cannot be written.
        """
        through = _checked_update_id(update_id, ceiling=_ID_CEILING - 1)
        await self._run(self._confirm_through_sync, through + 1)

    def _confirm_through_sync(self, owed: int) -> None:
        with self._transaction("record updates dealt with") as conn:
            held = self._owed(conn)
            if held is None or owed > held:
                conn.execute("UPDATE owed SET offset_owed = ? WHERE id = 1", (owed,))

    # --- the line's own call records -----------------------------------------------

    async def claim_poll(self) -> TelegramPollClaim:
        """Claim a poll's record with the offset owed, in one transaction.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written, or minting
                failed.
        """
        return await self._run(self._claim_poll_sync)

    def _claim_poll_sync(self) -> TelegramPollClaim:
        with self._transaction("claim a poll") as conn:
            offset = self._owed(conn)
            attempt = self._mint(conn)
            self._insert_call(
                conn,
                TelegramCallRecord(attempt=attempt, kind=TelegramCallKind.POLL, offset=offset),
            )
            return TelegramPollClaim(attempt=attempt, offset=offset)

    async def claim_typing(self, activation_id: str) -> str:
        """Claim one typing indicator's record.

        Raises:
            ValueError: If ``activation_id`` is malformed.
            TelegramIntakeRecordError: If the record cannot be written, or minting
                failed.
        """
        activation = _checked_identifier(activation_id, name="activation_id")
        return await self._run(self._claim_typing_sync, activation)

    def _claim_typing_sync(self, activation: str) -> str:
        with self._transaction("claim a typing indicator") as conn:
            attempt = self._mint(conn)
            self._insert_call(
                conn,
                TelegramCallRecord(
                    attempt=attempt, kind=TelegramCallKind.TYPING, activation_id=activation
                ),
            )
            return attempt

    async def claim_reply(self, update_id: int) -> str | None:
        """Answer a non-text message by claiming its fixed reply, in one transaction.

        Raises:
            ValueError: If ``update_id`` is malformed.
            TelegramIntakeRecordError: If the record cannot be written, or minting
                failed.
        """
        update = _checked_update_id(update_id)
        return await self._run(self._claim_reply_sync, update)

    def _claim_reply_sync(self, update: int) -> str | None:
        with self._transaction("claim a fixed reply") as conn:
            row = conn.execute(
                "SELECT update_id, kind, activation_id FROM intake WHERE update_id = ?",
                (update,),
            ).fetchone()
            if row is not None and _intake_from(row).kind is TelegramIntakeKind.TAKEN_IN:
                return None
            earlier = self._subject_calls(conn, TelegramCallKind.FIXED_REPLY, "update_id", update)
            if any(_blocks_another(one) for one in earlier):
                return None
            attempt = self._mint(conn)
            self._insert_call(
                conn,
                TelegramCallRecord(
                    attempt=attempt, kind=TelegramCallKind.FIXED_REPLY, update_id=update
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO intake(update_id, kind, activation_id) VALUES (?, ?, NULL)",
                (update, TelegramIntakeKind.ANSWERED.value),
            )
            return attempt

    async def claim_interrupted(self, activation_id: str) -> str | None:
        """Claim the restart's fixed message for ``activation_id``, in one transaction.

        Raises:
            ValueError: If ``activation_id`` is malformed.
            TelegramIntakeRecordError: If the record cannot be written, or minting
                failed.
        """
        activation = _checked_identifier(activation_id, name="activation_id")
        return await self._run(self._claim_interrupted_sync, activation)

    def _claim_interrupted_sync(self, activation: str) -> str | None:
        with self._transaction("claim a restart's message") as conn:
            earlier = self._subject_calls(
                conn, TelegramCallKind.INTERRUPTED, "activation_id", activation
            )
            if any(_blocks_another(one) for one in earlier):
                return None
            attempt = self._mint(conn)
            self._insert_call(
                conn,
                TelegramCallRecord(
                    attempt=attempt, kind=TelegramCallKind.INTERRUPTED, activation_id=activation
                ),
            )
            return attempt

    async def finish(self, attempt: str, outcome: TelegramOutcome) -> None:
        """Write a claimed call's outcome, once, and apply what it lets go.

        Raises:
            ValueError: If an argument is malformed.
            TelegramIntakeRecordError: If no call is held under ``attempt``, it is
                already finished, or the record cannot be written.
        """
        named = _checked_identifier(attempt, name="attempt")
        result = _checked_outcome(outcome)
        failure = None if result.failure is None else result.failure.value
        await self._run(self._finish_sync, named, failure, result.done)

    def _finish_sync(self, attempt: str, failure: str | None, done: bool) -> None:
        with self._transaction("finish a call") as conn:
            row = conn.execute(
                f"SELECT {_CALL_COLUMNS} FROM calls WHERE attempt = ?",  # noqa: S608 — only constants are interpolated
                (attempt,),
            ).fetchone()
            if row is None:
                msg = "the intake record holds no call under that attempt"
                raise TelegramIntakeRecordError(msg)
            held = _call_from(row)
            if held.finished:
                msg = "that call is already finished"
                raise TelegramIntakeRecordError(msg)
            conn.execute(
                "UPDATE calls SET finished = 1, failure = ? WHERE attempt = ?", (failure, attempt)
            )
            if held.kind is TelegramCallKind.POLL and done and held.offset is not None:
                self._confirmed(conn, held.offset)
            if held.kind.value in _ROUTINE_KINDS:
                conn.execute(
                    "DELETE FROM calls WHERE seq IN (SELECT seq FROM calls "
                    "WHERE kind IN (?, ?) AND finished = 1 ORDER BY seq DESC LIMIT -1 OFFSET ?)",
                    (*_ROUTINE_KINDS, self._kept_calls),
                )

    def _confirmed(self, conn: sqlite3.Connection, offset: int) -> None:
        """Let go of what a done poll carrying ``offset`` confirmed to Telegram."""
        owed = self._owed(conn)
        if owed is not None and owed <= offset:
            conn.execute("UPDATE owed SET offset_owed = NULL WHERE id = 1")
        conn.execute("DELETE FROM intake WHERE update_id < ?", (offset,))
        conn.execute(
            "DELETE FROM calls WHERE kind = ? AND finished = 1 AND update_id < ?",
            (TelegramCallKind.FIXED_REPLY.value, offset),
        )

    async def call(self, attempt: str) -> TelegramCallRecord | None:
        """Return the call record held under ``attempt``, or ``None``.

        Raises:
            ValueError: If ``attempt`` is malformed.
            TelegramIntakeRecordError: If the record cannot be read, or the row is
                corrupt.
        """
        named = _checked_identifier(attempt, name="attempt")
        row = await self._run(self._call_sync, named)
        return None if row is None else _call_from(row)

    def _call_sync(self, attempt: str) -> Any:
        with self._transaction("read a call", immediate=False) as conn:
            return conn.execute(
                f"SELECT {_CALL_COLUMNS} FROM calls WHERE attempt = ?",  # noqa: S608 — only constants are interpolated
                (attempt,),
            ).fetchone()

    # --- the user's data rights ----------------------------------------------------

    async def export(self) -> TelegramIntakeExport:
        """Return everything the record holds, from one consistent reading.

        Raises:
            TelegramIntakeRecordError: If the record cannot be read, or a row is
                corrupt.
        """
        offset, intake, calls = await self._run(self._export_sync)
        try:
            return TelegramIntakeExport(
                offset=offset,
                intake=tuple(_intake_from(row) for row in intake),
                calls=tuple(_call_from(row) for row in calls),
            )
        except ValidationError as exc:
            msg = "the stored offset is corrupt"
            raise TelegramIntakeRecordError(msg) from exc

    def _export_sync(self) -> tuple[int | None, list[Any], list[Any]]:
        with self._transaction("export the record", immediate=False) as conn:
            offset = self._owed(conn)
            intake = conn.execute(
                "SELECT update_id, kind, activation_id FROM intake ORDER BY update_id ASC"
            ).fetchall()
            calls = conn.execute(
                f"SELECT {_CALL_COLUMNS} FROM calls ORDER BY seq ASC"  # noqa: S608 — only constants are interpolated
            ).fetchall()
            return offset, intake, calls

    async def clear(self) -> int:
        """Erase everything, returning how many records went.

        Raises:
            TelegramIntakeRecordError: If the record cannot be written.
        """
        return await self._run(self._clear_sync)

    def _clear_sync(self) -> int:
        with self._transaction("clear the record") as conn:
            intake = conn.execute("DELETE FROM intake").rowcount
            calls = conn.execute("DELETE FROM calls").rowcount
            conn.execute("UPDATE owed SET offset_owed = NULL WHERE id = 1")
            return intake + calls
