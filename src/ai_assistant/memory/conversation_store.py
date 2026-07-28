"""A persistent :class:`~ai_assistant.core.protocols.ConversationStore` on SQLite.

Local-first storage (ADR-0002) for ADR-0074's conversation index: the durable
identity of a conversation, and the ordered turns recorded under it. It holds no
content — a turn's content is one ``EpisodicMemory`` in the ``MemoryStore``, named
here by a derived episode id — so this store needs no embedder and no vector
table, which is the whole of why it is a second store rather than a widening of
the first (ADR-0074 §9).

**Why this module lives in `memory/` while its contract does not.** ADR-0074 §9
rules that ``ConversationStore`` is its *own* Protocol and not an extension of
``MemoryStore``, and that separation is intact: the contract is a distinct
Protocol exchanging distinct types, and neither store holds the other. What is
shared is a package, because the architecture map (`CLAUDE.md`) names no
``conversations`` subsystem, and inventing one is an architecture decision owed
its own ADR rather than a side effect of an implementation lane. Placing the file
beside ``sqlite_store.py`` also keeps this change inside one subsystem. Nothing
here imports the memory store, and nothing in the memory store imports this.

The database file is created with owner-only permissions (ADR-0004 §4). Every
mutation runs inside one ``BEGIN IMMEDIATE`` transaction, which is how the
per-conversation exclusion ADR-0074 §8 puts on the *seam* holds across processes
as well as across coroutines — a lock inside one engine would not.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import (
    FIRST_TURN_ORDINAL,
    Conversation,
    ConversationExport,
    ConversationTurn,
    ParkedBinding,
    describe_untrusted,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.clock import Clock

_OWNER_ONLY = 0o600

#: One past the largest value a paging argument accepts: the signed 64-bit ceiling
#: a SQLite bind parameter tops out at (ADR-0073 §2), which this store inherits
#: rather than restates. Duplicated in the canonical fake rather than shared, for
#: the reason ``MemoryStore``'s own bound is: ``ai_assistant.testing`` may not
#: import a subsystem (golden rule 1), and ADR-0074 adds nothing to ``core``.
_PAGE_BOUND = 2**63

#: The configured replay window :meth:`SqliteConversationStore.turns` uses when a
#: caller names no ``limit`` (ADR-0074 §9.3): finite, and the same for everyone.
_DEFAULT_TAIL_LIMIT = 20

#: The default batch :meth:`SqliteConversationStore.episodes_to_purge` yields.
_DEFAULT_PURGE_BATCH = 100

#: The retention horizon an idle conversation is judged against when nobody
#: injects one (ADR-0074 §7). **Finite**: an unbounded default would ship an
#: ever-growing Tier 1 index with no cap decision behind it. ``None`` means "keep
#: forever" and switches reclaim off entirely — the user's deliberate choice.
_DEFAULT_EPISODE_RETENTION = timedelta(days=30)

#: How long a tombstone outlives the deletion that stamped it (ADR-0074 §8):
#: positive and finite, with no ``None`` spelling, because an unbounded grace and
#: a zero one break the deletion protocol in opposite directions.
_DEFAULT_TOMBSTONE_GRACE = timedelta(hours=1)

#: How many times :meth:`SqliteConversationStore.start` re-mints before giving up.
_START_RETRY_BUDGET = 8

#: The reserved namespace a captured turn's episode id is minted into (ADR-0074
#: §3): structurally recognisable, and no other producer may mint into it.
_EPISODE_NAMESPACE = "conv"

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


async def _run_to_completion[T](fn: Callable[..., T], /, *args: object) -> T:
    """Run ``fn`` in a worker thread, holding on until it *physically* finishes (ADR-0054).

    The store serialises one ``sqlite3`` connection behind an :class:`asyncio.Lock`
    and runs the SQL in a worker thread. A thread cannot be interrupted, so if the
    awaiting coroutine were simply cancelled the enclosing ``async with self._lock``
    would unwind and release the lock **while the worker was still using the
    connection** — letting a second caller use the same connection concurrently,
    which SQLite refuses.

    Deliberately duplicated from :mod:`ai_assistant.memory.sqlite_store` rather
    than shared. ADR-0060 refuses a common home for this helper precisely so that
    subsystems depend on the *obligation* and not on one way of meeting it, and
    reaching into another module for a private name would be the wrong way to
    spell "the same shape" in any case.
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _random_id() -> str:
    """Mint an opaque, random, device-agnostic conversation id (ADR-0074 §1)."""
    return str(uuid4())


def _to_micros(instant: datetime) -> int:
    """Exact integer microsecond UTC epoch for an aware datetime (issue #289).

    Integer arithmetic rather than ``datetime.timestamp()``: an IEEE-754 double's
    53-bit mantissa cannot resolve microseconds near the far end of the datetime
    range, and every deadline this store compares — a retention horizon, a
    tombstone grace — has to stay exact there.
    """
    delta = instant - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _instant_from(value: object, *, what: str) -> datetime:
    """Rebuild the aware UTC instant a stored microsecond epoch encodes.

    **An exact ``int`` is required, and that is the point.** SQLite's ``INTEGER``
    affinity is a preference rather than a constraint: a ``REAL`` that is not
    losslessly integral stays a ``REAL`` in the column, and ``timedelta`` would
    silently *round* one into a plausible instant — so a corrupt value would read
    back as data instead of as the corruption it is. ``bool`` is an ``int``
    subclass and is refused with it, since ``True`` is not an epoch.

    Raises:
        ConversationStoreError: If the stored value is not an exact integer, or
            is outside the representable datetime range. Both are store faults,
            and the contract owes this seam's error for a store fault rather than
            a raw ``OverflowError`` from the arithmetic.
    """
    if type(value) is not int:
        msg = f"a stored {what} is not an integer epoch: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    try:
        return _EPOCH + timedelta(microseconds=value)
    except (OverflowError, ValueError) as exc:
        msg = f"a stored {what} is out of range: {describe_untrusted(value)}"
        raise ConversationStoreError(msg) from exc


def _episode_id_of(value: object) -> str:
    """Read a stored episode id, refusing anything that is not a usable identifier.

    This is the one read whose caller *destroys* what it is handed, so coercing a
    corrupt value — ``str()`` on a ``BLOB`` yields a plausible-looking
    ``"b'...'"`` — would send a sweep to delete an id nothing holds, and then let
    it drop the index row that named the real episode. Every other read reaches a
    frozen type whose ``Identifier`` refuses the same values; this one does not,
    so it makes the check itself.

    Raises:
        ConversationStoreError: If the stored value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored episode id is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _stamped_id_of(value: object) -> str:
    """Read a stored conversation id, refusing anything that is not usable.

    The sibling of :func:`_episode_id_of`, and needed for the same reason:
    :meth:`SqliteConversationStore.stamped_conversation_ids` hands its result
    straight to a caller that will act on it, and it reaches no frozen type whose
    ``Identifier`` would refuse a ``BLOB`` or a stray number first. Coercing one
    with ``str()`` would send a sweep after an id nothing holds — and, worse, place
    the *next* batch's lexical cursor after a string no row ever carried, silently
    skipping every tombstone between the two.

    Raises:
        ConversationStoreError: If the stored value is not a non-blank ``str``.
    """
    if type(value) is not str or not value.strip():
        msg = f"a stored conversation id is not usable: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _ordinal_of(value: object) -> int:
    """Read a stored ordinal, refusing anything outside the domain one can have.

    The same affinity argument :func:`_instant_from` makes, plus the range: a
    ``REAL`` in an ``INTEGER`` column is a store fault, and coercing one would
    hand back a turn at a position no append ever allocated. The *whole* domain is
    checked here rather than in pieces, because every caller needs the same
    answer — the reader that decodes a row, the cursor that places a sweep, and
    the allocator that adds one to the highest.

    Raises:
        ConversationStoreError: If the stored value is not an exact ``int`` in
            ``[FIRST_TURN_ORDINAL, 2**63)``.
    """
    if type(value) is not int or not FIRST_TURN_ORDINAL <= value < _PAGE_BOUND:
        msg = f"a stored ordinal is not a usable position: {describe_untrusted(value)}"
        raise ConversationStoreError(msg)
    return value


def _check_page_bound(name: str, value: object, *, floor: int = 0) -> None:
    """Refuse a paging argument that is not an exact ``int`` in ``[floor, 2**63)``.

    ADR-0073 §2's posture, and the check this backend most needs: a negative bound
    would reach SQLite, which reads ``LIMIT -1`` as *no limit at all*, and an
    over-wide one raises ``OverflowError`` out of the driver.

    **The type is part of the range**, because "a signed 64-bit integer" is what
    the rule is about and the two backends disagree without it: ``LIMIT 1.5``
    reaches SQLite as a datatype error while an in-memory store slices a list and
    raises ``TypeError``. Two stores disagreeing about a bad argument is exactly
    the failure ADR-0073 §2 exists to stop. ``bool`` is refused with the rest —
    it is an ``int`` subclass, and ``limit=True`` is not a page size.

    Raises:
        ValueError: If ``value`` is not an ``int``, is below ``floor``, or is
            beyond the signed 64-bit range.
    """
    if type(value) is not int or not floor <= value < _PAGE_BOUND:
        msg = f"{name} must be an int in [{floor}, 2**63), got {describe_untrusted(value)}"
        raise ValueError(msg)


class SqliteConversationStore:
    """A persistent ``ConversationStore`` backed by ``sqlite3``."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam the contract names
        self,
        *,
        path: Path | str,
        now: Clock = _utcnow,
        new_id: Callable[[], str] = _random_id,
        retention: timedelta | None = _DEFAULT_EPISODE_RETENTION,
        tombstone_grace: timedelta = _DEFAULT_TOMBSTONE_GRACE,
        tail_limit: int = _DEFAULT_TAIL_LIMIT,
        purge_batch: int = _DEFAULT_PURGE_BATCH,
    ) -> None:
        """Open (or create) the store at ``path``.

        Args:
            path: Database file path, or ``":memory:"`` for an ephemeral store.
            now: Clock the store stamps and judges deadlines with; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, because this seam
                never reaches a `core` field validator — every reading becomes an
                integer microsecond epoch — so the producer is the only place a
                naive or indeterminate reading can be caught (ADR-0026 §7).
            new_id: The injected id factory ``start`` mints through (ADR-0074 §1).
            retention: The horizon an idle conversation is reclaimed against;
                ``None`` disables reclaim entirely (ADR-0074 §7).
            tombstone_grace: How long a stamped conversation's index outlives the
                stamp (ADR-0074 §8).
            tail_limit: The configured replay window :meth:`turns` uses by default.
            purge_batch: The batch size :meth:`episodes_to_purge` uses by default.

        Raises:
            ValueError: If ``tombstone_grace`` is not strictly positive, if
                ``retention`` is set and not strictly positive, or if either
                default page size is out of range. The two durations are refused
                rather than clamped for ADR-0074 §8's reason: a zero or negative
                grace and an unbounded one break the deletion protocol in opposite
                directions.
            ConversationStoreError: If the database cannot be opened or prepared.
        """
        # The type is checked before the comparison, because `None <= timedelta(0)`
        # raises `TypeError` and this constructor documents `ValueError` for a
        # duration it will not accept — whatever is wrong with it.
        if not isinstance(tombstone_grace, timedelta) or tombstone_grace <= timedelta(0):
            described = describe_untrusted(tombstone_grace)
            msg = f"tombstone_grace must be a strictly positive timedelta, got {described}"
            raise ValueError(msg)
        if retention is not None and (
            not isinstance(retention, timedelta) or retention <= timedelta(0)
        ):
            described = describe_untrusted(retention)
            msg = f"retention must be a strictly positive timedelta or None, got {described}"
            raise ValueError(msg)
        _check_page_bound("tail_limit", tail_limit)
        _check_page_bound("purge_batch", purge_batch)
        self._clock = checked_clock(now, owner="SqliteConversationStore")
        self._new_id = new_id
        self._retention = retention
        self._grace = tombstone_grace
        self._tail_limit = tail_limit
        self._purge_batch = purge_batch
        self._path = path if path == ":memory:" else str(Path(path))
        self._lock = asyncio.Lock()
        self._conn = self._setup()

    # --- opening -------------------------------------------------------------

    def _setup(self) -> sqlite3.Connection:
        """Open the connection and create the schema, or fail with the seam's error."""
        try:
            # `isolation_level=None` puts the driver in autocommit mode, so every
            # transaction below is an explicit `BEGIN ... COMMIT` this module
            # controls. The implicit transactions the driver would otherwise open
            # are *deferred*, upgrading to a write lock only at the first write —
            # which leaves a read-then-write mutation open to exactly the
            # interleaving the exclusion exists to forbid.
            conn = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        except (sqlite3.Error, OSError) as exc:
            msg = f"failed to open conversation store at {self._path!r}: {exc}"
            raise ConversationStoreError(msg) from exc
        try:
            # Restricted *before* the first write, not after the schema is built.
            # SQLite copies the database file's mode onto every rollback journal
            # it creates for it, so a journal written while the file still
            # carried the process umask would be world-readable — and an
            # interrupted write leaves that journal on disk holding Tier 1 pages
            # (ADR-0004 §4). `connect` creates the file, so there is something to
            # restrict by the time this runs.
            self._restrict_permissions()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS conversations("
                "id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, "
                "last_active_at INTEGER NOT NULL, last_turn_at INTEGER, deleted_at INTEGER)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS turns("
                "conversation_id TEXT NOT NULL, ordinal INTEGER NOT NULL, "
                "episode_id TEXT NOT NULL, occurred_at INTEGER NOT NULL, "
                "execution_id TEXT, step_id TEXT, PRIMARY KEY(conversation_id, ordinal))"
            )
            # The two uniqueness invariants the store *proves* rather than asks a
            # caller to keep (ADR-0074 §9.1): one turn per episode id, and one turn
            # per parked binding. In the schema, so a second writer racing the
            # in-transaction check cannot land the row that check refused.
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS turns_episode ON turns(episode_id)")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS turns_binding "
                "ON turns(execution_id, step_id) WHERE execution_id IS NOT NULL"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS conversations_activity "
                "ON conversations(last_active_at DESC, id)"
            )
        except (sqlite3.Error, OSError) as exc:
            conn.close()  # never leak the connection when opening fails
            msg = f"failed to open conversation store at {self._path!r}: {exc}"
            raise ConversationStoreError(msg) from exc
        return conn

    def _restrict_permissions(self) -> None:
        if self._path != ":memory:":
            Path(self._path).chmod(_OWNER_ONLY)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # --- internals -----------------------------------------------------------

    def _now(self) -> datetime:
        """The guarded clock's reading, as this store's own error (ADR-0026 §4).

        Raises:
            ConversationStoreError: If the reading is naive, indeterminate, or
                outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise ConversationStoreError(str(exc)) from exc

    @contextlib.contextmanager
    def _transaction(self, what: str, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Run the block inside one transaction, translating backend failures.

        ``IMMEDIATE`` takes the write lock up front, so a read-then-write mutation
        cannot interleave with another writer's — which is how the exclusion
        ADR-0074 §8 places on the seam holds **across processes** and not merely
        across coroutines on one loop. ``immediate=False`` is the read form: a
        deferred transaction, so several ``SELECT``s in one block see one
        consistent snapshot rather than two states either side of a racing write.

        Anything other than a backend failure propagates unchanged, after the
        transaction is rolled back — which is how :meth:`append` refuses a
        duplicate binding without consuming an ordinal or leaving a row behind.

        Raises:
            ConversationStoreError: If the backend fails at any point.
        """
        conn = self._conn
        begin = "BEGIN IMMEDIATE" if immediate else "BEGIN"
        try:
            conn.execute(begin)
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise ConversationStoreError(msg) from exc
        try:
            yield conn
        except BaseException as exc:
            # `BaseException`, not `Exception`: ADR-0060's resource clause is
            # unconditional, and a transaction left open on the shared connection
            # is a resource held with nothing running that will release it — the
            # next `BEGIN` fails with "cannot start a transaction within a
            # transaction" and the store is poisoned for every later caller.
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                msg = f"failed to {what}: {exc}"
                raise ConversationStoreError(msg) from exc
            raise
        try:
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            with contextlib.suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            msg = f"failed to {what}: {exc}"
            raise ConversationStoreError(msg) from exc

    @staticmethod
    def _fetch(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        """Run one read on an open connection, translating a backend failure.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.Error as exc:
            msg = f"failed to {what}: {exc}"
            raise ConversationStoreError(msg) from exc

    @staticmethod
    def _decode_conversation(row: Sequence[Any]) -> Conversation:
        """Rebuild a :class:`Conversation` from its row, surfacing corruption.

        Raises:
            ConversationStoreError: If the stored row does not validate.
        """
        try:
            return Conversation(
                id=row[0],
                started_at=_instant_from(row[1], what="started_at"),
                last_active_at=_instant_from(row[2], what="last_active_at"),
                last_turn_at=(
                    None if row[3] is None else _instant_from(row[3], what="last_turn_at")
                ),
                deleted_at=None if row[4] is None else _instant_from(row[4], what="deleted_at"),
            )
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored conversation could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @classmethod
    def _decode_turn(cls, row: Sequence[Any]) -> ConversationTurn:
        """Rebuild a :class:`ConversationTurn` from its row, surfacing corruption.

        Raises:
            ConversationStoreError: If the stored row does not validate.
        """
        # The binding is a *pair*, so a row carrying half of one is corrupt — and
        # the half that would otherwise pass unnoticed is `(NULL, 's')`, which a
        # check on `execution_id` alone reads as an unparked turn and hands back
        # as a plausible-but-wrong record, losing the durable recovery binding.
        # This module always writes both columns in one statement, so the pair can
        # only break through something outside the store; the guard therefore sits
        # where the store reads foreign data, which is where the contract's
        # promise about a corrupt row lives.
        if (row[4] is None) != (row[5] is None):
            msg = (
                f"a stored turn carries half a parked binding: "
                f"execution_id={describe_untrusted(row[4])}, step_id={describe_untrusted(row[5])}"
            )
            raise ConversationStoreError(msg)
        try:
            parked = None if row[4] is None else ParkedBinding(execution_id=row[4], step_id=row[5])
            return ConversationTurn(
                conversation_id=row[0],
                ordinal=_ordinal_of(row[1]),
                episode_id=cls._verified_episode_id(row[0], _ordinal_of(row[1]), row[2]),
                occurred_at=_instant_from(row[3], what="occurred_at"),
                parked=parked,
            )
        except (ValidationError, TypeError, OverflowError) as exc:
            msg = f"a stored turn could not be decoded: {exc}"
            raise ConversationStoreError(msg) from exc

    @classmethod
    def _verified_episode_id(cls, conversation_id: str, ordinal: int, stored: object) -> str:
        """Return the stored episode id, having checked it is the one derived.

        The id is a *function* of the conversation and the ordinal (ADR-0074 §3),
        so a stored value that is not that function's output is a store fault, not
        a variant. It matters most on the destructive path: a sweep handed a
        foreign id would delete something that is not this turn's episode — or
        nothing at all — and then drop the index row that named the real one,
        leaving it orphaned with nothing left pointing at it.

        Raises:
            ConversationStoreError: If the stored id is not the derived one.
        """
        expected = cls._episode_id(conversation_id, ordinal)
        if _episode_id_of(stored) != expected:
            described = describe_untrusted(stored)
            msg = f"a stored episode id is not the one this turn derives: {described}"
            raise ConversationStoreError(msg)
        return expected

    @staticmethod
    def _episode_id(conversation_id: str, ordinal: int) -> str:
        """Derive a turn's episode id from the two values the store proved unique.

        Reserved to captured conversation turns (ADR-0074 §3): no other producer
        mints into this namespace, so a collision inside it is a broken invariant
        rather than bad luck.
        """
        return f"{_EPISODE_NAMESPACE}:{conversation_id}:{ordinal}"

    @classmethod
    def _row_of(cls, conn: sqlite3.Connection, conversation_id: str) -> Sequence[Any] | None:
        """Read one conversation row inside an open transaction, or ``None``."""
        rows = cls._fetch(
            conn,
            "read a conversation",
            "SELECT id, started_at, last_active_at, last_turn_at, deleted_at "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        )
        return rows[0] if rows else None

    @staticmethod
    def _unknown(conversation_id: str) -> UnknownConversationError:
        """The refusal §1 requires: an id the store does not know is not created.

        The narrow subclass (ADR-0076 §2), so a sweep can tell an id another
        sweeper already finished from a database that is failing.
        """
        described = describe_untrusted(conversation_id)
        return UnknownConversationError(f"no such conversation: {described}")

    # --- the contract --------------------------------------------------------

    async def start(self) -> Conversation:
        """Mint an id, insert the record if that id is absent, and return it.

        The presence check and the insert are one ``IMMEDIATE`` transaction, so a
        second writer cannot land the row between them; a collision re-mints, and
        an exhausted budget raises rather than returning someone else's
        conversation (ADR-0074 §1).

        Raises:
            ConversationStoreError: If the retry budget is exhausted, the id
                factory produced something unusable, or the store cannot be
                written.
        """
        for _ in range(_START_RETRY_BUDGET):
            minted = self._new_id()
            async with self._lock:
                conversation = await _run_to_completion(self._insert_sync, minted)
            if conversation is not None:
                return conversation
        msg = (
            f"could not mint an unused conversation id in {_START_RETRY_BUDGET} attempts; "
            f"the injected id factory is repeating"
        )
        raise ConversationStoreError(msg)

    def _insert_sync(self, minted: str) -> Conversation | None:
        """Insert a conversation under ``minted``, or ``None`` if that id is taken.

        The clock is read **inside** the transaction, after the write exclusion is
        held. A reading taken before it could go stale while this call queues
        behind another writer — or behind a cross-process ``BEGIN IMMEDIATE`` —
        and a conversation would then be created carrying an activity stamp
        already in the past, which the retention reclaim judges against
        (ADR-0074 §2, §7).
        """
        with self._transaction("start a conversation") as conn:
            now = self._now()
            # Validated before it reaches the database, so a misbehaving factory
            # is this seam's error rather than a raw one from a bind parameter.
            try:
                conversation = Conversation(id=minted, started_at=now, last_active_at=now)
            except (ValidationError, TypeError) as exc:
                msg = f"the id factory minted an unusable id: {describe_untrusted(minted)}"
                raise ConversationStoreError(msg) from exc
            if self._row_of(conn, conversation.id) is not None:
                return None
            conn.execute(
                "INSERT INTO conversations(id, started_at, last_active_at, last_turn_at, "
                "deleted_at) VALUES (?, ?, ?, NULL, NULL)",
                (
                    conversation.id,
                    _to_micros(conversation.started_at),
                    _to_micros(conversation.last_active_at),
                ),
            )
            return conversation

    async def get(self, conversation_id: str) -> Conversation | None:
        """Return the conversation, or ``None`` if it is absent or stamped.

        Raises:
            ConversationStoreError: If the store cannot be read, or the stored row
                is corrupt.
        """
        async with self._lock:
            rows = await _run_to_completion(self._get_sync, conversation_id)
        return self._decode_conversation(rows[0]) if rows else None

    def _get_sync(self, conversation_id: str) -> list[Any]:
        return self._fetch(
            self._conn,
            "read a conversation",
            "SELECT id, started_at, last_active_at, last_turn_at, deleted_at "
            "FROM conversations WHERE id = ? AND deleted_at IS NULL",
            (conversation_id,),
        )

    async def mark_active(self, conversation_id: str) -> Conversation:
        """Record that a turn has begun, leaving ``last_turn_at`` alone.

        The clock is read **inside** the exclusion, not before it. A reading taken
        first could go stale while this call queues behind another writer — or
        behind a cross-process ``BEGIN IMMEDIATE`` — and stamp the conversation
        active at an instant that has already passed, which is the reading a
        reclaim then judges against (ADR-0074 §9.4). Matching ``SqliteMemoryStore``,
        whose reads take the same care for the same reason.

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If the store cannot be written.
        """
        async with self._lock:
            row = await _run_to_completion(self._mark_active_sync, conversation_id)
        return self._decode_conversation(row)

    def _mark_active_sync(self, conversation_id: str) -> Sequence[Any]:
        with self._transaction("mark a conversation active") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            conn.execute(
                "UPDATE conversations SET last_active_at = ? WHERE id = ?",
                (_to_micros(now), conversation_id),
            )
            marked = self._row_of(conn, conversation_id)
            if marked is None:  # pragma: no cover — the row was just updated in this transaction
                raise self._unknown(conversation_id)
            return marked

    async def append(
        self,
        conversation_id: str,
        *,
        occurred_at: datetime,
        parked: ParkedBinding | None = None,
    ) -> ConversationTurn:
        """Allocate the ordinal, derive the episode id, and record the turn.

        Allocation, derivation and the write are one transaction, so two engines
        cannot derive one id for two turns (ADR-0074 §3). A duplicate binding is
        refused before anything is allocated and the transaction is rolled back,
        so no ordinal is consumed and no row is left behind (§9.1).

        Raises:
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
            ConversationStoreError: If ``parked`` duplicates a binding already
                claimed, or the store cannot be written.
            ValueError: If ``occurred_at`` is not a timezone-aware instant.
        """
        async with self._lock:
            row = await _run_to_completion(self._append_sync, conversation_id, occurred_at, parked)
        return self._decode_turn(row)

    def _append_sync(
        self, conversation_id: str, occurred_at: datetime, parked: ParkedBinding | None
    ) -> Sequence[Any]:
        with self._transaction("append a turn") as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if parked is not None:
                claimed = self._fetch(
                    conn,
                    "check a parked binding",
                    "SELECT 1 FROM turns WHERE execution_id = ? AND step_id = ?",
                    (parked.execution_id, parked.step_id),
                )
                if claimed:
                    msg = (
                        f"a turn already parked on execution {parked.execution_id!r} "
                        f"step {parked.step_id!r}"
                    )
                    raise ConversationStoreError(msg)
            highest, stored = self._fetch(
                conn,
                "allocate an ordinal",
                "SELECT MAX(ordinal), COUNT(*) FROM turns WHERE conversation_id = ?",
                (conversation_id,),
            )[0]
            if highest is None:
                ordinal = FIRST_TURN_ORDINAL
            else:
                # Density is exactly `MAX == COUNT` when the numbering starts at
                # one, which is the cheap total check. A gap can only come from
                # outside this module — rows go when the record is dropped and
                # never one at a time — and allocating past one would *extend* the
                # corruption rather than report it, leaving an index whose walks
                # no longer agree with the ordinals they visit.
                last = _ordinal_of(highest)
                if last != stored:
                    msg = (
                        f"conversation {describe_untrusted(conversation_id)} has a gapped "
                        f"turn index: {stored} turns ending at ordinal {last}"
                    )
                    raise ConversationStoreError(msg)
                ordinal = last + 1
            if ordinal >= _PAGE_BOUND:
                # Unreachable by appending — ordinals start at 1 and move by one —
                # so this is a corrupt or hostile row. It still owes this seam's
                # error rather than the `OverflowError` binding the value would
                # raise, which is what the contract promises for a store fault.
                msg = f"conversation {describe_untrusted(conversation_id)} has no ordinal left"
                raise ConversationStoreError(msg)
            # Built before anything is written, because `occurred_at` is the one
            # argument this seam cannot vouch for: a naive value is refused rather
            # than silently localised to the host's zone (ADR-0023 §3), and the
            # rollback leaves the ordinal unconsumed.
            turn = ConversationTurn(
                conversation_id=conversation_id,
                ordinal=ordinal,
                episode_id=self._episode_id(conversation_id, ordinal),
                occurred_at=occurred_at,
                parked=parked,
            )
            stamp = _to_micros(turn.occurred_at)
            conn.execute(
                "INSERT INTO turns(conversation_id, ordinal, episode_id, "
                "occurred_at, execution_id, step_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    turn.conversation_id,
                    turn.ordinal,
                    turn.episode_id,
                    stamp,
                    None if parked is None else parked.execution_id,
                    None if parked is None else parked.step_id,
                ),
            )
            conn.execute(
                "UPDATE conversations SET last_turn_at = ? WHERE id = ?",
                (stamp, conversation_id),
            )
            return (
                turn.conversation_id,
                turn.ordinal,
                turn.episode_id,
                stamp,
                None if parked is None else parked.execution_id,
                None if parked is None else parked.step_id,
            )

    async def turns(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        before_ordinal: int | None = None,
    ) -> list[ConversationTurn]:
        """Return a page of turns, ordinal ascending, ending below ``before_ordinal``.

        Raises:
            ValueError: If ``limit`` or ``before_ordinal`` is out of range.
            UnknownConversationError: If the id names nothing or names a stamped
                conversation.
        """
        page = self._tail_limit if limit is None else limit
        _check_page_bound("limit", page)
        if before_ordinal is not None:
            _check_page_bound("before_ordinal", before_ordinal, floor=FIRST_TURN_ORDINAL)
        async with self._lock:
            rows = await _run_to_completion(self._turns_sync, conversation_id, page, before_ordinal)
        return [self._decode_turn(row) for row in rows]

    def _turns_sync(self, conversation_id: str, page: int, before_ordinal: int | None) -> list[Any]:
        with self._transaction("read a conversation's turns", immediate=False) as conn:
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                raise self._unknown(conversation_id)
            if page == 0:
                return []
            # Take the newest `page` rows below the ceiling, then hand them back
            # oldest-first: the tail is what a continuation wants, and ordinal
            # ascending is the order it replays them in. The unbounded form is a
            # *separate* query rather than a sentinel ceiling, because there is no
            # in-range integer above every ordinal: `2**63` is one past what a
            # SQLite bind parameter can carry and raises `OverflowError`.
            head = (
                "SELECT conversation_id, ordinal, episode_id, "
                "occurred_at, execution_id, step_id FROM turns WHERE conversation_id = ?"
            )
            if before_ordinal is None:
                rows = self._fetch(
                    conn,
                    "read a conversation's turns",
                    head + " ORDER BY ordinal DESC LIMIT ?",
                    (conversation_id, page),
                )
            else:
                rows = self._fetch(
                    conn,
                    "read a conversation's turns",
                    head + " AND ordinal < ? ORDER BY ordinal DESC LIMIT ?",
                    (conversation_id, before_ordinal, page),
                )
            return list(reversed(rows))

    async def episodes_to_purge(
        self,
        conversation_id: str,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of this conversation's episode ids, in ordinal order.

        Reads a stamped conversation *and* a live one — the deletion sweep walks
        the first, the retention reclaim the second — and removes nothing either
        way: the rows are the intent log, and they go only when
        :meth:`drop_if_eligible` succeeds.

        Raises:
            ValueError: If ``limit`` is out of range, or ``after_id`` is not an
                episode id of this conversation.
            UnknownConversationError: If the id names nothing.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        async with self._lock:
            return await _run_to_completion(
                self._episodes_to_purge_sync, conversation_id, batch, after_id
            )

    def _episodes_to_purge_sync(
        self, conversation_id: str, batch: int, after_id: str | None
    ) -> list[str]:
        with self._transaction("read a conversation's episode ids", immediate=False) as conn:
            if self._row_of(conn, conversation_id) is None:
                raise self._unknown(conversation_id)
            floor = 0
            if after_id is not None:
                # The cursor is an id the caller already holds, and the store
                # places it because the encoding is its own. One it cannot place is
                # refused rather than silently restarting the walk, which would
                # make a sweep loop forever over its first batch.
                placed = self._fetch(
                    conn,
                    "place a purge cursor",
                    "SELECT ordinal FROM turns WHERE conversation_id = ? AND episode_id = ?",
                    (conversation_id, after_id),
                )
                if not placed:
                    described = describe_untrusted(after_id)
                    msg = f"after_id {described} is not an episode id of this conversation"
                    raise ValueError(msg)
                floor = _ordinal_of(placed[0][0])
            if batch == 0:
                return []
            rows = self._fetch(
                conn,
                "read a conversation's episode ids",
                "SELECT episode_id, ordinal FROM turns WHERE conversation_id = ? AND ordinal > ? "
                "ORDER BY ordinal ASC LIMIT ?",
                (conversation_id, floor, batch),
            )
            return [
                self._verified_episode_id(conversation_id, _ordinal_of(row[1]), row[0])
                for row in rows
            ]

    async def stamped_conversation_ids(
        self,
        *,
        limit: int | None = None,
        after_id: str | None = None,
    ) -> list[str]:
        """Return the next batch of stamped-but-not-dropped ids, ``id`` ascending.

        The cursor is a **lexical bound on the id space** — ``id > ?`` — and never
        a row lookup, because this walk's rows are dropped by the very sweep
        walking them: by the time the caller asks for the next batch, the id it
        carries may name nothing, and a cursor resolved by lookup would stall
        exactly when the sweep was working correctly (ADR-0076 §2). Grace is not a
        filter here; :meth:`drop_if_eligible` judges it under the exclusion.

        Raises:
            ValueError: If ``limit`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        batch = self._purge_batch if limit is None else limit
        _check_page_bound("limit", batch)
        if batch == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._stamped_ids_sync, batch, after_id)
        return [_stamped_id_of(row[0]) for row in rows]

    def _stamped_ids_sync(self, batch: int, after_id: str | None) -> list[Any]:
        if after_id is None:
            return self._fetch(
                self._conn,
                "list stamped conversations",
                "SELECT id FROM conversations WHERE deleted_at IS NOT NULL ORDER BY id ASC LIMIT ?",
                (batch,),
            )
        return self._fetch(
            self._conn,
            "list stamped conversations",
            "SELECT id FROM conversations WHERE deleted_at IS NOT NULL AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (after_id, batch),
        )

    async def recent(self, *, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List unstamped conversations, last activity first, ``id`` breaking ties.

        Raises:
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConversationStoreError: If the store cannot be read.
        """
        _check_page_bound("limit", limit)
        _check_page_bound("offset", offset)
        if limit == 0:
            return []
        async with self._lock:
            rows = await _run_to_completion(self._recent_sync, limit, offset)
        return [self._decode_conversation(row) for row in rows]

    def _recent_sync(self, limit: int, offset: int) -> list[Any]:
        return self._fetch(
            self._conn,
            "list recent conversations",
            "SELECT id, started_at, last_active_at, last_turn_at, deleted_at "
            "FROM conversations WHERE deleted_at IS NULL "
            "ORDER BY last_active_at DESC, id ASC LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def turn_of_episode(self, episode_id: str) -> ConversationTurn | None:
        """Return the turn an episode records, or ``None`` if absent or stamped."""
        async with self._lock:
            rows = await _run_to_completion(self._turn_of_episode_sync, episode_id)
        return self._decode_turn(rows[0]) if rows else None

    async def turn_of_binding(self, binding: ParkedBinding) -> ConversationTurn | None:
        """Return the turn that parked on ``binding``, or ``None`` if absent or stamped."""
        async with self._lock:
            rows = await _run_to_completion(
                self._turn_of_binding_sync, binding.execution_id, binding.step_id
            )
        return self._decode_turn(rows[0]) if rows else None

    def _turn_of_episode_sync(self, episode_id: str) -> list[Any]:
        """Resolve an episode id, hiding a turn whose conversation is stamped.

        The join is the whole of the rule: a caller holding an episode id from
        before a deletion must not get back the ordinal, timestamp and binding
        metadata every presenting read withholds (ADR-0074 §9).
        """
        return self._fetch(
            self._conn,
            "resolve an episode id",
            "SELECT t.conversation_id, t.ordinal, t.episode_id, "
            "t.occurred_at, t.execution_id, t.step_id "
            "FROM turns t JOIN conversations c ON c.id = t.conversation_id "
            "WHERE t.episode_id = ? AND c.deleted_at IS NULL",
            (episode_id,),
        )

    def _turn_of_binding_sync(self, execution_id: str, step_id: str) -> list[Any]:
        """Resolve a parked binding, hiding a turn whose conversation is stamped."""
        return self._fetch(
            self._conn,
            "resolve a parked binding",
            "SELECT t.conversation_id, t.ordinal, t.episode_id, "
            "t.occurred_at, t.execution_id, t.step_id "
            "FROM turns t JOIN conversations c ON c.id = t.conversation_id "
            "WHERE t.execution_id = ? AND t.step_id = ? AND c.deleted_at IS NULL",
            (execution_id, step_id),
        )

    async def stamp_deleted(self, conversation_id: str) -> bool:
        """Stamp the conversation deleted, returning whether this call did it.

        The clock is read inside the exclusion: a reading taken before it would
        date the tombstone earlier than the stamp actually landed, and the grace
        that outlives the deletion is measured from that instant (ADR-0074 §8).
        """
        async with self._lock:
            return await _run_to_completion(self._stamp_deleted_sync, conversation_id)

    def _stamp_deleted_sync(self, conversation_id: str) -> bool:
        with self._transaction("stamp a conversation deleted") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None or row[4] is not None:
                return False
            conn.execute(
                "UPDATE conversations SET deleted_at = ? WHERE id = ?",
                (_to_micros(now), conversation_id),
            )
            return True

    async def drop_if_eligible(self, conversation_id: str) -> bool:
        """Remove the record and its index if it is still eligible, under the exclusion.

        The eligibility re-check happens *inside* the transaction that drops, which
        is what stops a reclaim destroying a conversation the user has just come
        back to (ADR-0074 §9.4) — and so is the clock reading it is judged
        against, because a reading taken before the exclusion could have gone
        stale while this call queued behind the very continuation that should
        defeat it.
        """
        async with self._lock:
            return await _run_to_completion(self._drop_if_eligible_sync, conversation_id)

    def _drop_if_eligible_sync(self, conversation_id: str) -> bool:
        with self._transaction("drop a conversation") as conn:
            now = self._now()
            row = self._row_of(conn, conversation_id)
            if row is None:
                return False  # nothing to drop; the sweep is idempotent by re-running
            # Decoded through the same guard every read uses, rather than by
            # reaching into the row: a corrupt stamp is a store fault and owes
            # `ConversationStoreError` like any other, and converting a raw epoch
            # here would let an `OverflowError` escape a method the contract
            # documents as returning a bool.
            conversation = self._decode_conversation(row)
            # `now - stamp >= duration` rather than `stamp + duration <= now`:
            # the two are equivalent, but only the first cannot overflow.
            # `checked_clock` admits a reading a day short of `datetime.max`
            # (ADR-0026 §3), and adding a horizon to one raises `OverflowError`
            # out of that same comparison.
            if conversation.deleted_at is not None:
                eligible = now - conversation.deleted_at >= self._grace
            else:
                eligible = (
                    self._retention is not None
                    and now - conversation.last_active_at >= self._retention
                )
            if not eligible:
                return False
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return True

    async def export(self) -> ConversationExport:
        """Return the store's own snapshot: unstamped conversations and their turns.

        No liveness filtering — this store cannot ask the ``MemoryStore`` whether
        an episode still resolves, and the user-facing export is composed in
        `orchestration` (ADR-0074 §9). Both halves are read in one deferred
        transaction, so the turns cannot describe a conversation the other half
        missed.

        Raises:
            ConversationStoreError: If the store cannot be read, or a stored row
                is corrupt.
        """
        async with self._lock:
            exported_at, conversation_rows, turn_rows = await _run_to_completion(self._export_sync)
        return ConversationExport(
            exported_at=exported_at,
            conversations=tuple(self._decode_conversation(row) for row in conversation_rows),
            turns=tuple(self._decode_turn(row) for row in turn_rows),
        )

    def _export_sync(self) -> tuple[datetime, list[Any], list[Any]]:
        with self._transaction("export conversations", immediate=False) as conn:
            exported_at = self._now()
            conversations = self._fetch(
                conn,
                "export conversations",
                "SELECT id, started_at, last_active_at, last_turn_at, deleted_at "
                "FROM conversations WHERE deleted_at IS NULL "
                "ORDER BY last_active_at DESC, id ASC",
            )
            turns = self._fetch(
                conn,
                "export conversation turns",
                "SELECT t.conversation_id, t.ordinal, t.episode_id, "
                "t.occurred_at, t.execution_id, t.step_id "
                "FROM turns t JOIN conversations c ON c.id = t.conversation_id "
                "WHERE c.deleted_at IS NULL ORDER BY t.conversation_id ASC, t.ordinal ASC",
            )
            return exported_at, conversations, turns
