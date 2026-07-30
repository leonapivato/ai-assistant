"""SqliteConversationStore: the shared conformance suite, plus what only it owes.

The suite holds the contract; this module holds the properties that belong to a
*persistent* store — that the file it creates is owner-only (ADR-0004 §4), that
what it wrote survives a reopen, and that a broken backend surfaces as the seam's
own error rather than as a raw ``sqlite3`` failure.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import stat
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conversation_store_contract import (
    ConversationStoreContract,
    ConversationStoreFactory,
    MovableClock,
)

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import ParkedBinding
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.testing.cancellation import ResourceLog, SuspendedMidWrite, ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.testing.cancellation import SuspendedCall

#: The store's own defaults, restated here rather than imported (see the fake's
#: binding for why).
_TAIL_DEFAULT = 20
_PURGE_DEFAULT = 100

#: The private method each locked mutation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn. Spelled out rather
#: than derived, because ``start``'s is ``_insert_sync`` — the method is named for
#: what it writes, not for the contract method that calls it.
_SYNC_METHODS = {
    "start": "_insert_sync",
    "mark_active": "_mark_active_sync",
    "append": "_append_sync",
    "stamp_deleted": "_stamp_deleted_sync",
    "drop_if_eligible": "_drop_if_eligible_sync",
}

_NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _fixed_now() -> datetime:
    return _NOW


def _mode_of(path: Path) -> int:
    """The permission bits of ``path``.

    A sync helper because the filesystem cases are ``async def`` and ruff's
    ASYNC240 (rightly) objects to blocking ``pathlib`` calls on an async path.
    The blocking read is real; keeping it in one place makes that visible.
    """
    return stat.S_IMODE(path.stat().st_mode)


def _journal_mode(database: Path) -> int | None:
    """The mode of the rollback journal beside ``database``, or ``None`` if absent."""
    journal = Path(f"{database}-journal")
    return _mode_of(journal) if journal.exists() else None


def _watch_the_journal(monkeypatch: pytest.MonkeyPatch, database: Path) -> list[int | None]:
    """Record the journal's mode at the start of every statement the store runs.

    ``SqliteConversationStore`` has no method running inside ``_setup``'s transaction
    to hook, the way the memory, plan and audit stores are hooked on
    ``_verify_or_init_meta`` / ``_check_schema_version``. So the observation goes on
    the connection itself at ``connect`` — the earliest point that is inside
    ``_setup`` and still ahead of the first statement, which is exactly the window
    the ordering under test lives in. The trace callback fires as each statement
    *starts*, so it sees both a journal opened by the previous statement of an open
    transaction and one that was already on disk before any statement ran.

    Returns:
        The modes observed, in statement order; ``None`` where no journal existed.
    """
    observed: list[int | None] = []
    real_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn: sqlite3.Connection = real_connect(*args, **kwargs)
        conn.set_trace_callback(lambda _statement: observed.append(_journal_mode(database)))
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)
    return observed


#: The conversation id the orphan rows below name, which no record ever carries.
_ABSENT = "no-such-conversation"

#: The turn columns, in the order every insert here binds them.
_TURN_COLUMNS = "conversation_id, ordinal, episode_id, occurred_at, execution_id, step_id"


def _cascading_keys_of(database: Path) -> list[tuple[object, ...]]:
    """The cascading foreign keys ``turns`` carries, read as the store reads them."""
    raw = sqlite3.connect(database)
    try:
        return [
            row
            for row in raw.execute("PRAGMA foreign_key_list(turns)")
            if row[2] == "conversations" and row[3] == "conversation_id" and row[4] == "id"
            if str(row[6]).upper() == "CASCADE"
        ]
    finally:
        raw.close()


def _insert_orphan_turn(database: Path, *, binding: ParkedBinding) -> str:
    """Write a turn naming a conversation that does not exist, and return its episode id.

    Through a raw connection, because that is the only writer that can produce one:
    ``PRAGMA foreign_keys`` is per connection and off unless asked for, so a tool
    that never asked can still land the row the store's own connection refuses.
    That asymmetry is precisely why the constraint is not enough on its own and the
    reads have to report what they find (#452).
    """
    episode_id = f"conv:{_ABSENT}:1"
    raw = sqlite3.connect(database)
    try:
        raw.execute(
            f"INSERT INTO turns({_TURN_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",  # noqa: S608 — literals
            (_ABSENT, 1, episode_id, 0, binding.execution_id, binding.step_id),
        )
        raw.commit()
    finally:
        raw.close()
    return episode_id


def _strip_the_foreign_key(database: Path) -> None:
    """Rewrite ``turns`` back to the unconstrained shape a pre-#452 store wrote.

    The file is produced by the *current* store and then walked backwards, rather
    than assembled from a hand-written legacy schema: everything but the one column
    constraint under test is then authentic, and a legacy database in the wild is
    exactly this file.
    """
    raw = sqlite3.connect(database, isolation_level=None)
    try:
        raw.execute(
            "CREATE TABLE turns_legacy(conversation_id TEXT NOT NULL, ordinal INTEGER NOT NULL, "
            "episode_id TEXT NOT NULL, occurred_at INTEGER NOT NULL, execution_id TEXT, "
            "step_id TEXT, PRIMARY KEY(conversation_id, ordinal))"
        )
        raw.execute(
            f"INSERT INTO turns_legacy({_TURN_COLUMNS}) SELECT {_TURN_COLUMNS} FROM turns"  # noqa: S608 — literals
        )
        raw.execute("DROP TABLE turns")
        raw.execute("ALTER TABLE turns_legacy RENAME TO turns")
        raw.execute("CREATE UNIQUE INDEX turns_episode ON turns(episode_id)")
        raw.execute(
            "CREATE UNIQUE INDEX turns_binding ON turns(execution_id, step_id) "
            "WHERE execution_id IS NOT NULL"
        )
    finally:
        raw.close()


class TestSqliteConversationStoreContract(ConversationStoreContract):
    """Runs SqliteConversationStore through the shared ConversationStore suite."""

    @pytest.fixture
    def store(self) -> Iterator[ConversationStore]:
        opened = SqliteConversationStore(path=":memory:", now=_fixed_now)
        yield opened
        opened.close()

    @pytest.fixture
    def defaults(self) -> Iterator[tuple[ConversationStore, MovableClock]]:
        clock = MovableClock()
        opened = SqliteConversationStore(path=":memory:", now=clock)
        yield opened, clock
        opened.close()

    @pytest.fixture
    def factory(self) -> Iterator[ConversationStoreFactory]:
        opened: list[SqliteConversationStore] = []

        def build(  # noqa: PLR0913 — one keyword per injected seam
            *,
            now: Callable[[], datetime],
            new_id: Callable[[], str],
            retention: timedelta | None,
            tombstone_grace: timedelta,
            tail_limit: int,
            purge_batch: int,
        ) -> ConversationStore:
            store = SqliteConversationStore(
                path=":memory:",
                now=now,
                new_id=new_id,
                retention=retention,
                tombstone_grace=tombstone_grace,
                tail_limit=tail_limit,
                purge_batch=purge_batch,
            )
            opened.append(store)
            return store

        yield build
        for store in opened:
            store.close()

    @pytest.fixture
    def tail_default(self) -> int:
        return _TAIL_DEFAULT

    @pytest.fixture
    def purge_default(self) -> int:
        return _PURGE_DEFAULT

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[ConversationStore]]:
        """Park a named mutation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps that operation's ``_..._sync`` — inside
        ``async with self._lock`` and inside the worker thread the event loop
        cannot interrupt, which is exactly where ADR-0054's bug lived — so the
        first worker to reach it blocks and every later one runs free. Blocking
        there is what makes the case deterministic: left to run, the transaction
        finishes in microseconds and whether the second caller arrives while the
        worker still holds the connection would be a race, so the invariant would
        be exercised only sometimes.

        Its own store on its own connection, not the ``store`` fixture's: the
        suspended worker is parked for the length of the case, and sharing would
        make an unrelated failure hang instead of fail.
        """
        store = SqliteConversationStore(path=":memory:", now=_fixed_now)
        log = ResourceLog()
        suspension = ThreadSuspension()

        def arm(operation: str) -> SuspendedCall:
            attribute = _SYNC_METHODS[operation]
            original = getattr(store, attribute)
            armed = threading.Event()

            def blocking(*args: object) -> object:
                with log.inside():  # the span the connection is genuinely in use for
                    if not armed.is_set():  # the first worker only; later ones run free
                        armed.set()
                        suspension.hold()
                    return original(*args)

            setattr(store, attribute, blocking)
            return suspension

        try:
            yield SuspendedMidWrite(store=store, log=log, arm=arm)
        finally:
            suspension.release()
            # An implementation that released the connection early leaves a worker
            # still using it; closing under that is a native crash rather than a
            # reported failure, so give the worker a turn to unwind and let the
            # assertion in the suite be the thing that speaks.
            await asyncio.sleep(0.05)
            store.close()


@pytest.mark.integration
async def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4: conversation history is Tier 1 and readable by nobody else."""
    path = tmp_path / "conversations.db"

    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.start()
    finally:
        store.close()

    assert _mode_of(path) == 0o600


@pytest.mark.integration
def test_a_journal_opened_during_setup_is_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0004 §4 reaches the sidecars, and reaches them from the first write (#491).

    SQLite copies the database file's mode onto every rollback journal it creates
    for it, so restricting the file after the schema is built leaves every journal
    opened in between carrying the process umask — and an interrupted write leaves
    it on disk holding Tier 1 pages beside a ``0600`` base file.

    Observed **inside** ``_setup`` rather than after it, because that is the only
    place the difference is visible. The case this replaces provoked a journal
    through a raw connection *after* the constructor returned, by which point the
    file is ``0600`` under either ordering — so it passed on the unfixed code and
    was no evidence for the fix it was named for (#491).

    The file is walked back to the pre-#452 shape so that :meth:`_migrate_turns`
    runs: it is the one part of setup with an explicit ``BEGIN``, so its journal
    stays open across statement boundaries where the trace callback can read it —
    and it is also the write most exposed here, since it copies every turn. The
    file is left ``0644`` beforehand so the case does not depend on the runner's
    umask, and because reopening an existing store is the common path anyway.
    """
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    _strip_the_foreign_key(path)
    path.chmod(0o644)

    observed = _watch_the_journal(monkeypatch, path)
    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        journals = [mode for mode in observed if mode is not None]
        assert journals, "the rebuild should have run with a journal open"
        assert set(journals) == {0o600}
    finally:
        reopened.close()


@pytest.mark.integration
def test_a_stale_journal_is_restricted_before_any_statement_reads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0004 §4 reaches a ``-journal`` this process did not create either (#490).

    A crash leaves one behind, and it keeps its own mode across the reopen: SQLite
    copies the database file's mode onto a sidecar it *creates*, never onto one that
    is already there. Asserted from inside ``_setup`` because SQLite discards a
    non-hot journal during the first statement, so there is nothing left to look at
    once the constructor returns — the ``-wal``/``-shm`` cases beside this one, which
    SQLite never touches in the default journal mode, carry the after-the-fact form.

    One store covers the ``-journal`` name for all five: they share the restriction's
    shape line for line, and each has its own ``-wal``/``-shm`` case.
    """
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    journal = Path(f"{path}-journal")
    journal.touch()
    journal.chmod(0o644)

    observed = _watch_the_journal(monkeypatch, path)
    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert observed, "setup should have run at least one statement"
    assert observed[0] == 0o600


@pytest.mark.integration
def test_a_sidecar_that_was_already_there_is_restricted_at_open(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches a sidecar this process did not create (#490).

    SQLite copies the database file's mode onto a sidecar **it creates**, which is
    what makes restricting the file before the first statement enough for those. It
    does nothing for one already on disk: a ``-wal``/``-shm`` left by a process that
    put this file into WAL mode keeps its own mode across a reopen and then takes
    Tier 1 pages.

    Planted at ``0644`` and asserted after a *reopen*, because that is the only shape
    that can fail: a sidecar SQLite makes for an already-``0600`` file is ``0600``
    however this store is written. Nothing in this codebase sets ``journal_mode``, so
    SQLite neither reads nor writes these two — the mode asserted is this store's own
    chmod and nothing else.
    """
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    sidecars = [Path(f"{path}{suffix}") for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.touch()
        sidecar.chmod(0o644)

    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert [_mode_of(each) for each in sidecars] == [0o600, 0o600]


@pytest.mark.integration
def test_a_symlink_under_a_sidecar_name_is_left_alone(tmp_path: Path) -> None:
    """The restriction narrows this store's own files, and only those (#501's review).

    ``chmod`` follows symlinks and ``os.chmod(follow_symlinks=False)`` is unsupported
    on Linux, so a link planted under a sidecar's name would otherwise make the open
    silently set ``0600`` on a file holding none of this store's data — adding owner
    write to something deliberately read-only, or breaking a file another program
    reads. Skipping it exposes nothing extra: SQLite would follow the same link when
    it opened the sidecar for real, so a directory an adversary can write to is
    already past ADR-0004 §4 by a route this method could not close.

    Asserted for one store rather than five: the five copies of the loop are pinned
    by the ``-wal``/``-shm`` case each module carries, and this is a property of the
    rule, not of any one store.
    """
    path = tmp_path / "conversations.db"
    unrelated = tmp_path / "not-ours.txt"
    unrelated.write_text("held by something else")
    unrelated.chmod(0o644)
    Path(f"{path}-wal").symlink_to(unrelated)

    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert _mode_of(unrelated) == 0o644


@pytest.mark.integration
async def test_what_was_written_survives_a_reopen(tmp_path: Path) -> None:
    """The whole point of the persistent store: an id keeps working across a restart."""
    path = tmp_path / "conversations.db"
    binding = ParkedBinding(execution_id="exec-1", step_id="step-1")

    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        first = await store.append(conversation.id, occurred_at=_NOW)
        parked = await store.append(conversation.id, occurred_at=_NOW, parked=binding)
    finally:
        store.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        restored = await reopened.get(conversation.id)
        assert restored is not None
        assert restored.id == conversation.id
        assert restored.started_at == conversation.started_at
        assert restored.last_turn_at == _NOW
        assert await reopened.turns(conversation.id) == [first, parked]
        assert await reopened.turn_of_binding(binding) == parked
        # The ordinal is read back from the index, not from process state, so a
        # restarted engine cannot re-use one (ADR-0064's invariant across a restart).
        following = await reopened.append(conversation.id, occurred_at=_NOW)
        assert following.ordinal == parked.ordinal + 1
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_crashed_deletion_is_rediscoverable_across_a_reopen(tmp_path: Path) -> None:
    """ADR-0076 §4.4, in the case the gap was actually found in: "at engine start".

    §8's reclaim is specified to run at engine start, and #447 was the discovery
    that nothing could find its work there. The shared suite asserts the
    enumeration within one process; only the persistent store can assert it across
    the process boundary the sweep exists for — a stamp that landed, a purge and a
    drop that never did, and a fresh store over the same file.
    """
    path = tmp_path / "conversations.db"
    clock = MovableClock()
    grace = timedelta(hours=1)

    store = SqliteConversationStore(path=path, now=clock, tombstone_grace=grace)
    try:
        conversation = await store.start()
        turn = await store.append(conversation.id, occurred_at=clock())
        assert await store.stamp_deleted(conversation.id) is True
        # ...and here the process dies: no episode purged, no record dropped.
    finally:
        store.close()

    reopened = SqliteConversationStore(path=path, now=clock, tombstone_grace=grace)
    try:
        assert await reopened.stamped_conversation_ids() == [conversation.id]
        assert await reopened.episodes_to_purge(conversation.id) == [turn.episode_id]
        assert await reopened.drop_if_eligible(conversation.id) is False, "inside the grace"

        clock.advance(grace)

        assert await reopened.drop_if_eligible(conversation.id) is True
        assert await reopened.stamped_conversation_ids() == []
    finally:
        reopened.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("execution_id", "step_id"),
    [(None, "step-1"), ("exec-1", None)],
    ids=["execution-lost", "step-lost"],
)
async def test_a_half_present_parked_binding_is_read_as_corruption(
    tmp_path: Path, execution_id: str | None, step_id: str | None
) -> None:
    """A binding is a pair, so half of one is a corrupt row, not an unparked turn.

    The dangerous half is the missing ``execution_id``: a decode that keyed on
    that column alone would hand back a plausible-looking turn with ``parked``
    unset, quietly losing the binding a recovered resume is found by (ADR-0074
    §3). The row is written here through a raw connection because this module
    never produces one — which is exactly why the guard is on the read.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        turn = await store.append(conversation.id, occurred_at=_NOW)
    finally:
        store.close()

    raw = sqlite3.connect(path)
    raw.execute(
        "UPDATE turns SET execution_id = ?, step_id = ? WHERE episode_id = ?",
        (execution_id, step_id, turn.episode_id),
    )
    raw.commit()
    raw.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(ConversationStoreError, match="half a parked binding"):
            await reopened.turns(conversation.id)
        with pytest.raises(ConversationStoreError, match="half a parked binding"):
            await reopened.turn_of_episode(turn.episode_id)
    finally:
        reopened.close()


@pytest.mark.integration
@pytest.mark.parametrize("column", ["last_active_at", "deleted_at"])
async def test_a_corrupt_timestamp_is_a_store_fault_on_the_lifecycle_path_too(
    tmp_path: Path, column: str
) -> None:
    """Every method owes ``ConversationStoreError`` for a store fault — reclaim included.

    ``drop_if_eligible`` is the one path that compares a stored instant against a
    duration, so it is the one that would otherwise convert a corrupt epoch
    itself and let a raw ``OverflowError`` escape a method the contract documents
    as returning a bool. It decodes through the same guard every read uses.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        if column == "deleted_at":
            await store.stamp_deleted(conversation.id)

        raw = sqlite3.connect(path)
        raw.execute(
            f"UPDATE conversations SET {column} = ? WHERE id = ?",  # noqa: S608 — a literal column
            (2**63 - 1, conversation.id),
        )
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError):
            await store.drop_if_eligible(conversation.id)
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("conversations", "last_active_at", 1.5),
        ("conversations", "started_at", "not-an-epoch"),
        ("turns", "occurred_at", 1.5),
        ("turns", "ordinal", 2.5),
    ],
    ids=["activity-float", "started-text", "occurred-float", "ordinal-float"],
)
async def test_a_column_holding_the_wrong_type_is_read_as_corruption(
    tmp_path: Path, table: str, column: str, value: object
) -> None:
    """SQLite's ``INTEGER`` affinity is a preference, not a constraint.

    A ``REAL`` that is not losslessly integral stays a ``REAL`` in the column, and
    ``timedelta`` would happily *round* one into a plausible instant — so the
    store would hand back a fabricated-but-valid record rather than reporting the
    corruption the contract promises to report. The same argument covers an
    ordinal: coercing one would place a turn where no append ever allocated it.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute(f"UPDATE {table} SET {column} = ?", (value,))  # noqa: S608 — literals
        raw.commit()
        raw.close()

        read = (
            store.get(conversation.id) if table == "conversations" else store.turns(conversation.id)
        )
        with pytest.raises(ConversationStoreError):
            await read
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize("ordinal", [-1, 0, 1.5], ids=["negative", "zero", "float"])
async def test_a_corrupt_ordinal_is_refused_on_every_path_that_reads_one(
    tmp_path: Path, ordinal: object
) -> None:
    """The allocator and the sweep cursor read ordinals too, not only the reader.

    ``append`` adds one to the highest stored ordinal, so a corrupt row would
    otherwise be *coerced into a position* — ``-1`` allocating ``0``, which the
    frozen type then rejects with a raw ``ValidationError``, and ``1.5``
    truncating a sweep cursor to a place it does not name. Both are store faults
    and both owe this seam's error.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        turn = await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute("UPDATE turns SET ordinal = ?", (ordinal,))
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError, match="not a usable position"):
            await store.append(conversation.id, occurred_at=_NOW)
        with pytest.raises(ConversationStoreError, match="not a usable position"):
            await store.episodes_to_purge(conversation.id, after_id=turn.episode_id)
    finally:
        store.close()


@pytest.mark.integration
async def test_an_ordinal_at_the_signed_64_bit_ceiling_is_the_seams_own_error(
    tmp_path: Path,
) -> None:
    """A corrupt row at SQLite's ceiling is a store fault, not a value to build on.

    Ordinals start at one and move by one, so a conversation reaches the ceiling
    only through corruption — and the density check catches it first, because a
    single turn at ``2**63 - 1`` is a gapped index before it is an exhausted one.
    The ceiling check behind it stays: it costs one comparison, and it is what
    keeps the allocation from binding a value the driver cannot carry should the
    numbering ever start somewhere else.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute("UPDATE turns SET ordinal = ?", (2**63 - 1,))
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError, match="gapped turn index"):
            await store.append(conversation.id, occurred_at=_NOW)
    finally:
        store.close()


@pytest.mark.integration
async def test_a_corrupt_episode_id_is_refused_on_the_path_that_destroys_it(
    tmp_path: Path,
) -> None:
    """The sweep's read is the one that must not coerce, because its caller deletes.

    ``str()`` on a ``BLOB`` yields a plausible-looking ``"b'...'"``: a sweep handed
    one would delete an id nothing holds, then drop the index row that named the
    real episode, leaving it unreachable. Every other read reaches a frozen type
    that refuses the same value; this one checks for itself.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute("UPDATE turns SET episode_id = ?", (b"\x00\x01",))
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError, match="not usable"):
            await store.episodes_to_purge(conversation.id)
    finally:
        store.close()


@pytest.mark.integration
async def test_two_stores_over_one_file_serialise_their_mutations(tmp_path: Path) -> None:
    """ADR-0074 §8's exclusion has to hold for a *second engine*, not one lock.

    Every in-process case passes on the store's own ``asyncio.Lock`` alone, so
    none of them can tell ``BEGIN IMMEDIATE`` from a deferred transaction. Two
    stores opened independently over one file can: a deferred read-then-write
    would let both allocate one ordinal, and a check-and-write split across two
    transactions would let a turn land in a conversation already stamped.
    """
    path = tmp_path / "conversations.db"
    first = SqliteConversationStore(path=path, now=_fixed_now)
    second = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await first.start()
        assert await second.get(conversation.id) is not None, "both see one database"

        turns = await asyncio.gather(
            *(
                store.append(conversation.id, occurred_at=_NOW)
                for _ in range(4)
                for store in (first, second)
            )
        )

        assert sorted(turn.ordinal for turn in turns) == list(range(1, 9)), (
            "two engines over one file allocated a conflicting ordinal, so the "
            "exclusion is not holding across connections"
        )
        assert len({turn.episode_id for turn in turns}) == 8

        appended, stamped = await asyncio.gather(
            first.append(conversation.id, occurred_at=_NOW),
            second.stamp_deleted(conversation.id),
            return_exceptions=True,
        )

        assert stamped is True
        named = await second.episodes_to_purge(conversation.id)
        if isinstance(appended, BaseException):
            assert isinstance(appended, ConversationStoreError), appended
            assert len(named) == 8
        else:
            assert appended.episode_id in named
            assert len(named) == 9
    finally:
        first.close()
        second.close()


# --- the exclusion across *processes* (#446) ---------------------------------

#: How long a child holds the critical section open once it has announced itself.
#: A *bound* on how long the engine behind it is given to arrive and collide, not a
#: synchronisation primitive — the ordering the cases below depend on comes from the
#: announcement, not from this.
_HOLD_SECONDS = 0.3


def _store_holding_its_ordinal_read(
    path: Path, *, announce: Callable[[], None], hold: float
) -> SqliteConversationStore:
    """A store whose first ordinal allocation announces itself and then waits inside.

    The rendezvous the cross-process claim actually needs. Starting two children
    together only makes them *runnable*: the OS may run one through all its work
    before scheduling the other, and in that execution a deferred read-then-write
    allocates dense ordinals too — so a test without this can pass on the very bug it
    exists to catch. The wait is placed after the competing read and before the write,
    which is precisely the window ``BEGIN IMMEDIATE`` is there to close.

    ``_fetch`` is shadowed on the instance and keyed on the human label the store
    already passes it, so the hook names the read it means rather than matching SQL.
    """
    store = SqliteConversationStore(path=path, now=_fixed_now)
    original = SqliteConversationStore._fetch
    announced = False

    def fetch(
        conn: sqlite3.Connection, what: str, sql: str, params: Sequence[object] = ()
    ) -> list[Any]:
        nonlocal announced
        rows = original(conn, what, sql, params)
        if what == "allocate an ordinal" and not announced:
            announced = True
            announce()
            time.sleep(hold)
        return rows

    # Shadowed on the instance, which is what keeps the hook to this store's reads.
    # `_append_sync` reaches it as `self._fetch`; `_row_of` is a classmethod and
    # resolves on the class, so the liveness read stays unhooked.
    store._fetch = fetch  # type: ignore[method-assign]  # a per-instance test hook
    return store


def _run_child(
    run: Callable[[Callable[[], None]], str], gate_fd: int, signal_fd: int, write_fd: int
) -> None:
    """Wait at the gate, do the work, report through the pipe — in the child.

    Never returns, and never lets an exception out: a traceback in a forked child is
    invisible to pytest, so a failure becomes a report the parent asserts on rather
    than a silent pass. It announces itself unconditionally on the way out too, so a
    child that died before reaching its critical section still releases the one
    waiting behind it.
    """

    def announce() -> None:
        with contextlib.suppress(OSError):
            os.write(signal_fd, b"s")

    try:
        with os.fdopen(gate_fd, "rb") as gate:
            gate.read(1)
        message = run(announce)
    except BaseException as exc:  # a forked child cannot raise into pytest
        message = f"ERROR {exc!r}"
    announce()
    with contextlib.suppress(OSError), os.fdopen(write_fd, "w") as pipe:
        pipe.write(message)
    os._exit(0)


def _in_staged_children(work: Sequence[Callable[[Callable[[], None]], str]]) -> list[str]:
    """Fork each callable into its own process, releasing each once the last announced.

    Staged rather than simultaneous, because simultaneous is not a rendezvous — see
    :func:`_store_holding_its_ordinal_read`. Each child is released only after its
    predecessor has announced that it is *inside* the critical section, so the overlap
    the cases are about is guaranteed rather than merely likely.

    Pipes are created immediately before each fork, so no child inherits a later
    child's, and every parent-side end is closed in the child (and every child-side
    end in the parent) — an inherited write end would keep a report pipe from ever
    reaching end-of-file. Children are reaped in a ``finally`` that first releases
    every gate still unwritten, so a failing assertion cannot leave one parked.
    """
    pids: list[int] = []
    gates: list[int] = []
    signals: list[int] = []
    reads: list[int] = []
    reports: list[str] = []
    try:
        for run in work:
            gate_read, gate_write = os.pipe()
            signal_read, signal_write = os.pipe()
            read_fd, write_fd = os.pipe()
            pid = os.fork()
            if pid == 0:  # child
                for parent_end in (gate_write, signal_read, read_fd):
                    os.close(parent_end)
                _run_child(run, gate_read, signal_write, write_fd)
            for child_end in (gate_read, signal_write, write_fd):
                os.close(child_end)
            pids.append(pid)
            gates.append(gate_write)
            signals.append(signal_read)
            reads.append(read_fd)
        for index, gate_write in enumerate(gates):
            os.write(gate_write, b"g")
            if index + 1 < len(gates):
                # Blocks until that child is inside — or has exited, which closes the
                # write end, so a child that died cannot strand the one behind it.
                os.read(signals[index], 1)
        for read_fd in reads:
            with os.fdopen(read_fd) as pipe:
                reports.append(pipe.read())
        reads.clear()
    finally:
        for leftover in (*gates, *signals, *reads):
            with contextlib.suppress(OSError):
                os.close(leftover)
        for pid in pids:
            os.waitpid(pid, 0)
    return reports


@pytest.mark.integration
@pytest.mark.skipif(not hasattr(os, "fork"), reason="platform has no fork")
async def test_two_processes_over_one_file_allocate_dense_distinct_ordinals(
    tmp_path: Path,
) -> None:
    """The module's claim is about *processes*, and only processes can test it.

    Every other concurrency case is one process. Even the two-connection case above
    is: each store's own ``asyncio.Lock`` serialises its connection before SQLite ever
    sees the contention, so none of them can tell ``BEGIN IMMEDIATE`` from a deferred
    read-then-write. Two engines really running at once can — a deferred transaction
    lets both read the same highest ordinal and go on to allocate it twice.

    The first child holds its transaction open across the read, and the second is
    released only once it is in there, so the collision is *attempted* on every run
    rather than whenever the scheduler happens to arrange it.

    Each child drives ``_append_sync`` on a store it opened itself: the parent's event
    loop is copied into a forked child and must not be reused, and a ``sqlite3``
    connection must not be shared across a fork either.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
    finally:
        store.close()

    each = 4
    total = 2 * each

    def _hold_then_append(announce: Callable[[], None]) -> str:
        child = _store_holding_its_ordinal_read(path, announce=announce, hold=_HOLD_SECONDS)
        try:
            allocated = [child._append_sync(conversation.id, _NOW, None)[1] for _ in range(each)]
        finally:
            child.close()
        return ",".join(str(one) for one in allocated)

    def _append(announce: Callable[[], None]) -> str:
        child = SqliteConversationStore(path=path, now=_fixed_now)
        try:
            allocated = [child._append_sync(conversation.id, _NOW, None)[1] for _ in range(each)]
        finally:
            child.close()
        return ",".join(str(one) for one in allocated)

    reports = _in_staged_children([_hold_then_append, _append])

    allocated: list[int] = []
    for report in reports:
        assert not report.startswith("ERROR"), report
        allocated.extend(int(one) for one in report.split(",") if one)
    assert sorted(allocated) == list(range(1, total + 1)), (
        "two processes over one file allocated a conflicting ordinal, so the "
        "per-conversation exclusion is not holding across processes"
    )

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        recorded = await reopened.turns(conversation.id, limit=total)
        assert [turn.ordinal for turn in recorded] == list(range(1, total + 1))
        assert len({turn.episode_id for turn in recorded}) == total
    finally:
        reopened.close()


@pytest.mark.integration
@pytest.mark.skipif(not hasattr(os, "fork"), reason="platform has no fork")
async def test_a_capture_holds_off_a_deletion_in_another_process(tmp_path: Path) -> None:
    """ADR-0074 §8's other conjunction, across the boundary the clause is written for.

    "A caller-held lock does not survive a second caller" is the whole reason the
    exclusion sits on the seam, so the shared suite's capture-and-deletion case is
    driven here between two engines. The suite's version accepts *either* consistent
    outcome, because in one process it cannot say which lands first. Staged across two
    processes it can, and the determinism is the discriminating power: the append is
    inside its transaction before the deletion is released, so ``BEGIN IMMEDIATE``
    makes the deletion wait, the turn is recorded, and the stamp then names both turns.

    Both weakenings fail it. A deferred *append* lets the stamp reach the row during
    the hold, and the append's write is then refused as busy; a deferred *stamp*
    reaches its update while the append holds the write lock, and it is refused
    instead. Neither leaves the determined outcome below.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)
    finally:
        store.close()

    def _hold_then_append(announce: Callable[[], None]) -> str:
        child = _store_holding_its_ordinal_read(path, announce=announce, hold=_HOLD_SECONDS)
        try:
            return str(child._append_sync(conversation.id, _NOW, None)[1])
        except UnknownConversationError:
            return "REFUSED"
        finally:
            child.close()

    def _stamp(announce: Callable[[], None]) -> str:
        child = SqliteConversationStore(path=path, now=_fixed_now)
        try:
            return str(child._stamp_deleted_sync(conversation.id))
        finally:
            child.close()

    appended, stamped = _in_staged_children([_hold_then_append, _stamp])

    assert appended == "2", (
        f"the append held the write lock across the window, so the deletion had to "
        f"queue behind it and the turn had to be recorded: {appended}"
    )
    assert stamped == "True", f"the deletion is unconditional and must have happened: {stamped}"

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        named = await reopened.episodes_to_purge(conversation.id)
        assert named == [f"conv:{conversation.id}:1", f"conv:{conversation.id}:2"], (
            "the append succeeded, so the index the sweep reads must name its episode"
        )
    finally:
        reopened.close()


@pytest.mark.integration
async def test_an_episode_id_that_is_not_the_derived_one_is_refused(tmp_path: Path) -> None:
    """The id is a function of the conversation and the ordinal, so a variant is a fault.

    The destructive path is why it matters: a sweep handed a foreign id deletes
    something that is not this turn's episode — or nothing at all — and then drops
    the index row that named the real one, leaving it orphaned with nothing left
    pointing at it (ADR-0074 §3, §8).
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute("UPDATE turns SET episode_id = ?", ("conv:somebody-else:1",))
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError, match="not the one this turn derives"):
            await store.turns(conversation.id)
        with pytest.raises(ConversationStoreError, match="not the one this turn derives"):
            await store.episodes_to_purge(conversation.id)
    finally:
        store.close()


# --- the turn index cannot name a conversation that is absent (#452) --------


@pytest.mark.integration
async def test_the_store_enforces_foreign_keys_on_its_own_connection(tmp_path: Path) -> None:
    """``PRAGMA foreign_keys`` is off by default and per connection, so it is asked for.

    Read off the connection because there is no black-box observation to make, and
    that is the finding rather than a weakness of the test: every statement this
    module issues is already referentially clean — the one ``INSERT`` into ``turns``
    proves the parent exists in the same transaction, and the drop deletes the index
    explicitly — so switching enforcement off changes nothing the store itself does.
    Its whole effect is on a writer that is not this module, which is what the
    constraint exists for. Without this case, deleting the pragma would break no test.
    """
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    try:
        assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.integration
async def test_the_schema_refuses_a_turn_that_names_no_conversation(tmp_path: Path) -> None:
    """The constraint is in the schema, so any writer that enforces it is held to it."""
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    store.close()

    raw = sqlite3.connect(path)
    try:
        raw.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                f"INSERT INTO turns({_TURN_COLUMNS}) VALUES (?, ?, ?, ?, NULL, NULL)",  # noqa: S608
                (_ABSENT, 1, f"conv:{_ABSENT}:1", 0),
            )
    finally:
        raw.close()


@pytest.mark.integration
async def test_deleting_a_conversation_row_cascades_to_its_turns(tmp_path: Path) -> None:
    """``ON DELETE CASCADE``, so a foreign writer's delete cannot manufacture an orphan.

    The store's own :meth:`drop_if_eligible` does not rely on this — it deletes the
    index explicitly, because the pragma is per connection and a cascade it depended
    on would silently stop happening on a connection that had not enabled it. The
    cascade is the backstop for everyone else, and this is what pins it.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)
    finally:
        store.close()

    raw = sqlite3.connect(path)
    try:
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("DELETE FROM conversations WHERE id = ?", (conversation.id,))
        raw.commit()
        assert raw.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
    finally:
        raw.close()


@pytest.mark.integration
async def test_a_turn_naming_no_conversation_is_reported_rather_than_joined_away(
    tmp_path: Path,
) -> None:
    """#452: the inner joins hid an orphan from every read instead of reporting it.

    A row a foreign writer landed is structurally valid and names nothing. Both
    reverse lookups and the export used to answer "no such turn" for it — the same
    answer they owe for a conversation deliberately withheld behind a tombstone — so
    the fault was indistinguishable from correct behaviour. And it is not merely
    hidden: the purge walk needs the *conversation* record to enumerate anything, so
    nothing could ever reach the episode this row names to destroy it.
    """
    path = tmp_path / "conversations.db"
    binding = ParkedBinding(execution_id="exec-orphan", step_id="step-orphan")
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        live = await store.start()
        await store.append(live.id, occurred_at=_NOW)
    finally:
        store.close()

    episode_id = _insert_orphan_turn(path, binding=binding)

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.turn_of_episode(episode_id)
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.turn_of_binding(binding)
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.export()
        # The other half of why hiding it was the wrong answer: there is no record
        # to enumerate it under, so the episode it names is unreachable.
        with pytest.raises(UnknownConversationError):
            await reopened.episodes_to_purge(_ABSENT)
        # A tombstone is still withheld rather than reported, which is the
        # distinction the left join exists to preserve.
        sound = await reopened.turns(live.id)
        assert await reopened.turn_of_episode(sound[0].episode_id) == sound[0]
        assert await reopened.stamp_deleted(live.id) is True
        assert await reopened.turn_of_episode(sound[0].episode_id) is None
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_legacy_database_without_the_foreign_key_is_rebuilt(tmp_path: Path) -> None:
    """``CREATE TABLE IF NOT EXISTS`` binds fresh databases only, so a rebuild is owed.

    SQLite has no ``ADD CONSTRAINT``, so the only way an existing file starts
    carrying the key is the table rebuild ``SqliteMemoryStore._migrate_records``
    already establishes as this repo's shape. What the case has to prove beyond
    "the key is there" is that nothing was lost on the way: the rows, their
    ordinals, and the two unique indexes ``DROP TABLE`` takes with it.
    """
    path = tmp_path / "conversations.db"
    binding = ParkedBinding(execution_id="exec-1", step_id="step-1")
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        first = await store.append(conversation.id, occurred_at=_NOW)
        parked = await store.append(conversation.id, occurred_at=_NOW, parked=binding)
    finally:
        store.close()

    _strip_the_foreign_key(path)
    assert not _cascading_keys_of(path), "the legacy file must really carry no key"

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert _cascading_keys_of(path), "opening the store should have rebuilt the table"
        assert await reopened.turns(conversation.id) == [first, parked]
        assert await reopened.turn_of_binding(binding) == parked
        # The ordinal is read back from the migrated index, not from process state.
        following = await reopened.append(conversation.id, occurred_at=_NOW)
        assert following.ordinal == parked.ordinal + 1
        # And the uniqueness invariants the schema *proves* came back with it: the
        # rebuild drops the table, and its indexes go with it (ADR-0074 §9.1).
        with pytest.raises(ConversationStoreError, match="already parked"):
            await reopened.append(conversation.id, occurred_at=_NOW, parked=binding)
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_legacy_orphan_migrates_even_where_enforcement_starts_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enforcement being off is a *compile-time* default, so the rebuild says ``OFF``.

    A driver built with ``SQLITE_DEFAULT_FOREIGN_KEYS`` hands out connections with
    enforcement already on. A rebuild that merely ran *before* the store switched it
    on would, on such a build, refuse the legacy orphan mid-copy and leave the file
    unopenable — the outcome the migration exists to avoid, unreachable on the
    machine running this and reachable on somebody else's. Simulated by handing the
    store the kind of connection such a build produces.
    """
    path = tmp_path / "conversations.db"
    binding = ParkedBinding(execution_id="exec-orphan", step_id="step-orphan")
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        live = await store.start()
        turn = await store.append(live.id, occurred_at=_NOW)
    finally:
        store.close()

    _strip_the_foreign_key(path)
    episode_id = _insert_orphan_turn(path, binding=binding)

    real_connect = sqlite3.connect

    # Typed to the one call the store makes, rather than to `connect`'s overloads:
    # the double stands in for a driver default, not for the whole function.
    def connect_enforcing(
        database: str, *, check_same_thread: bool, isolation_level: None
    ) -> sqlite3.Connection:
        conn = real_connect(
            database, check_same_thread=check_same_thread, isolation_level=isolation_level
        )
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # Scoped to the constructor, which is the only call that has to meet the
    # simulated driver — the helpers below open their own ordinary connections.
    with monkeypatch.context() as patched:
        patched.setattr(sqlite3, "connect", connect_enforcing)
        reopened = SqliteConversationStore(path=path, now=_fixed_now)

    try:
        assert _cascading_keys_of(path), "the rebuild should have happened anyway"
        assert await reopened.turns(live.id) == [turn], "the sound rows are still readable"
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.turn_of_episode(episode_id)
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_legacy_orphan_survives_the_rebuild_and_is_reported(tmp_path: Path) -> None:
    """The copy runs with enforcement switched off, deliberately.

    A legacy file may already hold an orphan. Enforcing during the rebuild would
    refuse it and make that file *unopenable* — no read could reach the sound rows
    beside the broken one, and the fault would surface as a failure to construct the
    store rather than as the report the contract owes. So the row is carried across
    and named by the reads that would otherwise join it away.
    """
    path = tmp_path / "conversations.db"
    binding = ParkedBinding(execution_id="exec-orphan", step_id="step-orphan")
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        live = await store.start()
        turn = await store.append(live.id, occurred_at=_NOW)
    finally:
        store.close()

    _strip_the_foreign_key(path)
    episode_id = _insert_orphan_turn(path, binding=binding)

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert _cascading_keys_of(path), "the rebuild should have happened anyway"
        assert await reopened.turns(live.id) == [turn], "the sound rows are still readable"
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.turn_of_episode(episode_id)
        with pytest.raises(ConversationStoreError, match="names a conversation that is absent"):
            await reopened.export()
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_gapped_turn_index_is_reported_rather_than_extended(tmp_path: Path) -> None:
    """Density is the store's invariant, so a gap is a fault and not a shape to build on.

    A gap can only come from outside this module — rows go when the record is
    dropped and never one at a time — and allocating past one would extend the
    corruption instead of reporting it, leaving an index whose walks no longer
    agree with the ordinals they visit (ADR-0074 §9.2).
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.append(conversation.id, occurred_at=_NOW)
        second = await store.append(conversation.id, occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute(
            "UPDATE turns SET ordinal = ?, episode_id = ? WHERE ordinal = ?",
            (3, f"conv:{conversation.id}:3", second.ordinal),
        )
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError, match="gapped turn index"):
            await store.append(conversation.id, occurred_at=_NOW)
    finally:
        store.close()


@pytest.mark.integration
async def test_a_transaction_is_rolled_back_even_for_a_base_exception(tmp_path: Path) -> None:
    """ADR-0060's resource clause is unconditional, so the rollback cannot be either.

    A transaction left open on the shared connection is a resource held with
    nothing running that will release it: every later mutation fails at ``BEGIN``
    with "cannot start a transaction within a transaction", and the store is
    poisoned for every caller rather than for the one that failed.
    """

    class _Cancelling:
        """A clock that raises a ``BaseException`` the second time it is read."""

        def __init__(self) -> None:
            self.readings = 0

        def __call__(self) -> datetime:
            self.readings += 1
            if self.readings == 2:
                raise asyncio.CancelledError
            return _NOW

    clock = _Cancelling()
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=clock)
    try:
        conversation = await store.start()

        with pytest.raises(asyncio.CancelledError):
            await store.mark_active(conversation.id)

        # The store is still usable: the failed transaction released the
        # connection rather than leaving it mid-transaction.
        marked = await store.mark_active(conversation.id)
        assert marked.id == conversation.id
    finally:
        store.close()


@pytest.mark.integration
async def test_a_closed_store_reports_the_seams_own_error(tmp_path: Path) -> None:
    """A backend failure crosses the seam as ``ConversationStoreError``, never raw."""
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    conversation = await store.start()
    store.close()

    with pytest.raises(ConversationStoreError):
        await store.get(conversation.id)
    with pytest.raises(ConversationStoreError):
        await store.append(conversation.id, occurred_at=_NOW)
    with pytest.raises(ConversationStoreError):
        await store.export()


@pytest.mark.integration
async def test_opening_in_a_missing_directory_fails_with_the_seams_own_error(
    tmp_path: Path,
) -> None:
    """No connection to leak, and no raw ``sqlite3`` error escaping the constructor."""
    with pytest.raises(ConversationStoreError):
        SqliteConversationStore(path=tmp_path / "nope" / "conversations.db", now=_fixed_now)


@pytest.mark.integration
async def test_a_naive_clock_reading_is_refused_at_the_producer(tmp_path: Path) -> None:
    """ADR-0026 §7: this seam never reaches a `core` validator, so the guard is here."""
    store = SqliteConversationStore(
        path=tmp_path / "conversations.db",
        now=lambda: datetime(2026, 6, 1),  # noqa: DTZ001 — the point of the case
    )
    try:
        with pytest.raises(ConversationStoreError):
            await store.start()
    finally:
        store.close()
