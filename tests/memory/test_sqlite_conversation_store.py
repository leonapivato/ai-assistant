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
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conversation_store_contract import (
    ConversationStoreContract,
    ConversationStoreFactory,
    MovableClock,
)

from ai_assistant.core.errors import (
    ConversationStoreError,
    IncompatibleStateError,
)
from ai_assistant.core.types import (
    ChatDevice,
    DeletedMessage,
    DeviceAccess,
    MessageAuthor,
    NewMessage,
    SendOutcome,
    SpokenDelivery,
    SpokenDeliveryState,
)
from ai_assistant.memory import conversation_store
from ai_assistant.memory._episode_format import EPISODE_RECORD_FORMAT
from ai_assistant.memory.conversation_store import SqliteConversationStore, _run_to_completion
from ai_assistant.testing.cancellation import (
    ResourceLog,
    SuspendedMidWrite,
    ThreadSuspension,
    worker_finished_before_the_first_check,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence

    from ai_assistant.core.protocols import ConversationStore
    from ai_assistant.testing.cancellation import SuspendedCall

#: The store's own defaults, restated here rather than imported (see the fake's
#: binding for why).
_PURGE_DEFAULT = 100

#: The private method each locked operation does its SQL in, which ADR-0060's hook
#: wraps to park a worker thread inside the connection's turn. Spelled out rather
#: than derived, because two of them are named for what they touch rather than for
#: the contract method that calls them (``start`` → ``_insert_sync``,
#: ``stamped_conversation_ids`` → ``_stamped_ids_sync``). The reads are here for the
#: reason the mutations are: each is its own ``async with self._lock`` site (#492).
_SYNC_METHODS = {
    "start": "_insert_sync",
    "mark_active": "_mark_active_sync",
    "stamp_deleted": "_stamp_deleted_sync",
    "drop_if_eligible": "_drop_if_eligible_sync",
    "record_turn": "_record_turn_sync",
    "record_delivery": "_record_delivery_sync",
    "deliveries": "_deliveries_sync",
    "get": "_get_sync",
    "stamped_conversation_ids": "_stamped_ids_sync",
    "recent": "_recent_sync",
    "export": "_export_sync",
    "append_message": "_append_message_sync",
    "delete_message": "_delete_message_sync",
    "set_conversation_devices": "_set_conversation_devices_sync",
    "take_in": "_take_in_sync",
    "set_my_devices": "_set_my_devices_sync",
    "transcript": "_transcript_sync",
    "changes": "_changes_sync",
    "my_devices": "_my_devices_sync",
    "conversation_devices": "_conversation_devices_sync",
    "untaken_messages": "_untaken_sync",
    "conversations_awaiting": "_awaiting_sync",
    "taken_in": "_taken_in_sync",
    "device_changes": "_device_changes_sync",
    "device_conversations": "_device_conversations_sync",
    "remove_device": "_remove_device_sync",
}

_NOW = datetime(2026, 6, 1, tzinfo=UTC)

#: How long an input-observation case waits for its gated call to arrive before
#: declaring the scenario broken. Only ever reached when something has hung.
_GATE_SECONDS = 5.0


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

    def shared_history(self) -> tuple[ConversationStore, ConversationStore] | None:
        """Two connections over one file — what two engines over one data directory get.

        A file rather than ``":memory:"``, because that is the whole question: ADR-0074
        §9's exclusion is owed **across processes**, and an in-memory database is a
        private history no second handle can reach. The pair is closed by the
        ``_shared`` fixture's teardown.
        """
        return self._shared_pair

    @pytest.fixture(autouse=True)
    def _shared(self, tmp_path: Path) -> Iterator[None]:
        """Open the pair lazily-ish and close both, whatever the case did with them."""
        path = tmp_path / "conversations.db"
        first = SqliteConversationStore(path=path, now=_fixed_now)
        second = SqliteConversationStore(path=path, now=_fixed_now)
        self._shared_pair: tuple[ConversationStore, ConversationStore] = (first, second)
        yield
        first.close()
        second.close()

    @pytest.fixture
    def factory(self) -> Iterator[ConversationStoreFactory]:
        opened: list[SqliteConversationStore] = []

        def build(
            *,
            now: Callable[[], datetime],
            new_id: Callable[[], str],
            retention: timedelta | None,
            tombstone_grace: timedelta,
            purge_batch: int,
        ) -> ConversationStore:
            store = SqliteConversationStore(
                path=":memory:",
                now=now,
                new_id=new_id,
                retention=retention,
                tombstone_grace=tombstone_grace,
                purge_batch=purge_batch,
            )
            opened.append(store)
            return store

        yield build
        for store in opened:
            store.close()

    @pytest.fixture
    def purge_default(self) -> int:
        return _PURGE_DEFAULT

    @contextlib.asynccontextmanager
    async def store_suspended_mid_write(
        self,
    ) -> AsyncIterator[SuspendedMidWrite[ConversationStore]]:
        """Park a named operation's worker thread inside the connection's turn.

        ``arm(operation)`` wraps that operation's ``_..._sync`` (:data:`_SYNC_METHODS`)
        — inside ``async with self._lock`` and inside the worker thread the event
        loop cannot interrupt, which is exactly where ADR-0054's bug lived — so the
        first worker to reach it blocks and every later one runs free. Every lock
        site is its own place the bug can reappear, the locked reads included
        (#492). Blocking
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

    @contextlib.asynccontextmanager
    async def store_suspended_at_its_first_await(
        self,
    ) -> AsyncIterator[tuple[ConversationStore, Callable[[str], SuspendedCall]]]:
        """Park the named call at its own first ``await``, which here is the lock.

        A different position from ``store_suspended_mid_write`` above, and
        deliberately so. ADR-0060's hook goes *inside* the connection — inside the
        worker thread, past every argument this store reads. ADR-0065's must be at
        the method's own first suspension point, which for both operations the cases
        drive is ``async with self._lock``: neither ``record_turn`` nor
        ``deliveries`` awaits anything before it, and both hand their argument to
        the worker only afterwards. Suspending any later would put the mutation
        past the point a non-conforming implementation would have read the argument
        — the entry-side mistake ADR-0065 §3 warns about, in mirror image.

        The gate goes *before* ``acquire``, not after: a conforming implementation
        has observed its argument on its first executed lines and cannot be reached
        by the mutation, while one that reads it after taking the lock would be.

        Arming is deferred to ``arm`` because the cases seed the store first, and
        every seeding call takes the same lock: a hook armed at construction would
        spend its one suspension on a precondition.

        Its own store on its own connection, like the hook above, so a failure leaves
        nothing parked on the ``store`` fixture's.
        """
        store = SqliteConversationStore(path=":memory:", now=_fixed_now)
        lock = _GatedLock(store._lock)
        # `_lock` is typed `asyncio.Lock`; this stands in for one and is only ever
        # entered through `async with`.
        store._lock = lock  # type: ignore[assignment]

        def arm(_operation: str) -> SuspendedCall:
            lock.arm()
            return lock

        try:
            yield store, arm
        finally:
            lock.release()
            store.close()


class _GatedLock:
    """The store's ``asyncio.Lock``, wrapped so one acquisition can be held at the door.

    Every ``ConversationStore`` method's first ``await`` is this lock, so ADR-0065's
    input-observation cases gate it rather than a collaborator. The suspension goes
    *before* ``acquire`` for the reason the hook above gives.
    """

    def __init__(self, delegate: asyncio.Lock) -> None:
        """Wrap ``delegate``; unarmed, so nothing suspends until :meth:`arm`."""
        self._delegate = delegate
        self._armed = False
        self._entered = asyncio.Event()
        self._released = asyncio.Event()

    def arm(self) -> None:
        """Make the next acquisition suspend before it takes the lock."""
        self._armed = True

    async def __aenter__(self) -> None:
        """Suspend if armed, then take the real lock."""
        if self._armed:
            self._armed = False
            self._entered.set()
            await self._released.wait()
        await self._delegate.acquire()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release the real lock."""
        self._delegate.release()

    async def reached(self) -> None:
        """Wait until the gated call has arrived."""
        async with asyncio.timeout(_GATE_SECONDS):
            await self._entered.wait()

    def release(self) -> None:
        """Let the gated call take the lock; idempotent."""
        self._released.set()


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
    """Fresh M36 initialization restricts the file before transactional writes."""
    path = tmp_path / "conversations.db"
    path.touch(mode=0o644)

    observed = _watch_the_journal(monkeypatch, path)
    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        journals = [mode for mode in observed if mode is not None]
        assert journals, "initialization should have run with a journal open"
        assert set(journals) == {0o600}
    finally:
        reopened.close()


@pytest.mark.integration
def test_a_stale_journal_is_restricted_before_initialization_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0275 probes compatibility before chmod; writes still require owner-only mode."""
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    journal = Path(f"{path}-journal")
    journal.touch()
    journal.chmod(0o644)

    observed = _watch_the_journal(monkeypatch, path)
    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert observed, "setup should have run at least one statement"
    assert 0o600 in observed
    first_restricted = observed.index(0o600)
    assert all(mode in (None, 0o600) for mode in observed[first_restricted:])


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


#: What the symlink cases below plant, and expect to find untouched afterwards.
_NOT_OURS = "held by something else"


@pytest.mark.integration
@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_a_symlink_under_a_sidecar_name_is_never_followed(tmp_path: Path, suffix: str) -> None:
    """The restriction narrows this store's own files, and only those (#501's review).

    ``chmod`` follows symlinks and ``os.chmod(follow_symlinks=False)`` is unsupported
    on Linux, so a link planted under a sidecar's name would otherwise make the open
    silently set ``0600`` on a file holding none of this store's data — adding owner
    write to something deliberately read-only, or breaking a file another program
    reads. Both the mode *and* the contents are asserted, because "left alone" is the
    whole claim.

    Asserted for one store rather than five: the five copies of the loop are pinned
    by the ``-wal``/``-shm`` case each module carries, and this is a property of the
    rule, not of any one store.
    """
    path = tmp_path / "conversations.db"
    unrelated = tmp_path / "not-ours.txt"
    unrelated.write_text(_NOT_OURS)
    unrelated.chmod(0o644)
    Path(f"{path}{suffix}").symlink_to(unrelated)

    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert _mode_of(unrelated) == 0o644
    assert unrelated.read_text() == _NOT_OURS


@pytest.mark.integration
def test_sqlite_discards_a_symlinked_journal_rather_than_writing_through_it(
    tmp_path: Path,
) -> None:
    """Skipping the link leaves no Tier 1 page anywhere it could not reach (#501's review).

    The worry the case above does not answer on its own: if this store declines to
    restrict a symlinked sidecar and SQLite then *followed* that link when it opened
    the sidecar for real, pages would land in a world-readable file the store had
    deliberately left alone — a worse outcome than the chmod it stopped doing.

    It does not happen, and this pins the behaviour rather than trusting it, because
    it belongs to another project's file layer. A ``-journal`` that is a symlink is
    not a hot journal, so SQLite unlinks *the link* at the first statement and writes
    a real file in its place — one that inherits the database's ``0600``, which the
    ordering cases above already assert. The target is never opened. (A symlinked
    ``-wal`` on a WAL-mode database is refused outright, which surfaces through each
    store's existing ``sqlite3.Error`` arm; nothing in this codebase sets
    ``journal_mode``, so that path is #505's to decide, not this module's to drive.)
    """
    path = tmp_path / "conversations.db"
    unrelated = tmp_path / "not-ours.txt"
    unrelated.write_text(_NOT_OURS)
    unrelated.chmod(0o644)
    journal = Path(f"{path}-journal")
    journal.symlink_to(unrelated)

    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert not journal.is_symlink(), "SQLite should have unlinked the planted link"
        assert unrelated.read_text() == _NOT_OURS
        assert _mode_of(unrelated) == 0o644
    finally:
        store.close()


@pytest.mark.integration
async def test_what_was_written_survives_a_reopen(tmp_path: Path) -> None:
    """The whole point of the persistent store: an id keeps working across a restart."""
    path = tmp_path / "conversations.db"

    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        recorded = await store.record_turn(
            conversation.id, episode_id="activation:a", occurred_at=_NOW
        )
        assert recorded is not None
    finally:
        store.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        restored = await reopened.get(conversation.id)
        assert restored == recorded
        assert restored is not None
        assert restored.started_at == conversation.started_at
        assert restored.last_turn_at == _NOW
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_fresh_store_holds_no_turn_table_and_reopens(tmp_path: Path) -> None:
    """ADR-0283 §6, §12: the turn index is retired, so the schema does not carry it.

    Read from the file, because no read on the seam could show a table's absence —
    and reopened, because the open path no longer probes a turn table's shape and
    must not refuse a file for lacking one.
    """
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()

    raw = sqlite3.connect(path)
    try:
        tables = {row[0] for row in raw.execute("SELECT name FROM sqlite_master")}
    finally:
        raw.close()
    assert "turns" not in tables
    assert {"conversations", "deliveries", "episode_record_format"} <= tables

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert await reopened.recent() == []
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
        await store.record_turn(conversation.id, episode_id="activation:a", occurred_at=clock())
        assert await store.stamp_deleted(conversation.id) is True
        # ...and here the process dies: no episode purged, no record dropped.
    finally:
        store.close()

    reopened = SqliteConversationStore(path=path, now=clock, tombstone_grace=grace)
    try:
        assert await reopened.stamped_conversation_ids() == [conversation.id]
        assert await reopened.drop_if_eligible(conversation.id) is False, "inside the grace"

        clock.advance(grace)

        assert await reopened.drop_if_eligible(conversation.id) is True
        assert await reopened.stamped_conversation_ids() == []
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
    ("column", "value"),
    [
        ("last_active_at", 1.5),
        ("started_at", "not-an-epoch"),
        ("last_turn_at", 1.5),
    ],
    ids=["activity-float", "started-text", "turn-float"],
)
async def test_a_column_holding_the_wrong_type_is_read_as_corruption(
    tmp_path: Path, column: str, value: object
) -> None:
    """SQLite's ``INTEGER`` affinity is a preference, not a constraint.

    A ``REAL`` that is not losslessly integral stays a ``REAL`` in the column, and
    ``timedelta`` would happily *round* one into a plausible instant — so the
    store would hand back a fabricated-but-valid record rather than reporting the
    corruption the contract promises to report.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        await store.record_turn(conversation.id, episode_id="activation:a", occurred_at=_NOW)

        raw = sqlite3.connect(path)
        raw.execute(f"UPDATE conversations SET {column} = ?", (value,))  # noqa: S608 — literals
        raw.commit()
        raw.close()

        with pytest.raises(ConversationStoreError):
            await store.get(conversation.id)
    finally:
        store.close()


@pytest.mark.integration
async def test_two_stores_over_one_file_serialise_their_mutations(tmp_path: Path) -> None:
    """ADR-0074 §8's exclusion has to hold for a *second engine*, not one lock.

    Every in-process case passes on the store's own ``asyncio.Lock`` alone, so
    none of them can tell ``BEGIN IMMEDIATE`` from a deferred transaction. Two
    stores opened independently over one file can: a check-and-write split across
    two transactions would let a turn land in a conversation already stamped.
    """
    path = tmp_path / "conversations.db"
    first = SqliteConversationStore(path=path, now=_fixed_now)
    second = SqliteConversationStore(path=path, now=_fixed_now)
    unstamped = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    try:
        conversation = await first.start()
        assert await second.get(conversation.id) is not None, "both see one database"

        episodes = [f"activation:{index}" for index in range(8)]
        await asyncio.gather(
            *(
                (first, second)[index % 2].record_turn(
                    conversation.id, episode_id=episode, occurred_at=_NOW, delivery=unstamped
                )
                for index, episode in enumerate(episodes)
            )
        )
        assert await second.deliveries(conversation.id, episode_ids=episodes) == dict.fromkeys(
            episodes, unstamped
        ), "every recorded episode from either engine has its delivery row"

        recorded, stamped = await asyncio.gather(
            first.record_turn(
                conversation.id, episode_id="activation:late", occurred_at=_NOW, delivery=unstamped
            ),
            second.stamp_deleted(conversation.id),
        )

        assert stamped is True
        assert await first.get(conversation.id) is None
        if recorded is not None:
            assert recorded.deleted_at is None, (
                "a recorded conversation is the one as it stood before the stamp"
            )
    finally:
        first.close()
        second.close()


# --- the exclusion across *processes* (#446) ---------------------------------

#: How long a child holds the critical section open once it has announced itself.
#: A *bound* on how long the engine behind it is given to arrive and collide, not a
#: synchronisation primitive — the ordering the cases below depend on comes from the
#: announcement, not from this.
_HOLD_SECONDS = 0.3


def _store_holding_its_liveness_read(
    path: Path, *, announce: Callable[[], None], hold: float
) -> SqliteConversationStore:
    """A store whose first conversation read announces itself and then waits inside.

    The rendezvous the cross-process claim actually needs. Starting two children
    together only makes them *runnable*: the OS may run one through all its work
    before scheduling the other, and in that execution a deferred read-then-write
    passes too — so a test without this can pass on the very bug it exists to catch.
    The wait is placed after the liveness read and before the write, which is
    precisely the window ``BEGIN IMMEDIATE`` is there to close.

    ``_row_of`` is shadowed on the instance, which an instance attribute does for a
    classmethod, so the hook stays on this store's reads.
    """
    store = SqliteConversationStore(path=path, now=_fixed_now)
    original = SqliteConversationStore._row_of
    announced = False

    def row_of(conn: sqlite3.Connection, conversation_id: str) -> Sequence[Any] | None:
        nonlocal announced
        row = original(conn, conversation_id)
        if not announced:
            announced = True
            announce()
            time.sleep(hold)
        return row

    store._row_of = row_of  # type: ignore[method-assign]  # a per-instance test hook
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
    :func:`_store_holding_its_liveness_read`. Each child is released only after its
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
async def test_a_capture_holds_off_a_deletion_in_another_process(tmp_path: Path) -> None:
    """ADR-0074 §8's conjunction, across the boundary the clause is written for.

    "A caller-held lock does not survive a second caller" is the whole reason the
    exclusion sits on the seam, so the shared suite's record-and-deletion case is
    driven here between two engines. The suite's version accepts *either* consistent
    outcome, because in one process it cannot say which lands first. Staged across two
    processes it can, and the determinism is the discriminating power: ``record_turn``
    is inside its transaction before the deletion is released, so ``BEGIN IMMEDIATE``
    makes the deletion wait, the episode is recorded, and the stamp then lands.

    Both weakenings fail it. A deferred ``record_turn`` lets the stamp reach the row
    during the hold, and the record's write is then refused as busy; a deferred stamp
    reaches its update while the record holds the write lock, and it is refused
    instead. Neither leaves the determined outcome below.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
    finally:
        store.close()
    unstamped = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)

    def _hold_then_record(announce: Callable[[], None]) -> str:
        child = _store_holding_its_liveness_read(path, announce=announce, hold=_HOLD_SECONDS)
        try:
            row = child._record_turn_sync(conversation.id, "activation:held", _NOW, unstamped)
        finally:
            child.close()
        return "NONE" if row is None else "RECORDED"

    def _stamp(announce: Callable[[], None]) -> str:
        child = SqliteConversationStore(path=path, now=_fixed_now)
        try:
            return str(child._stamp_deleted_sync(conversation.id))
        finally:
            child.close()

    recorded, stamped = _in_staged_children([_hold_then_record, _stamp])

    assert recorded == "RECORDED", (
        f"the record held the write lock across the window, so the deletion had to "
        f"queue behind it and the episode had to be recorded: {recorded}"
    )
    assert stamped == "True", f"the deletion is unconditional and must have happened: {stamped}"
    assert [row[1] for row in _delivery_rows(path)] == ["activation:held"], (
        "the record succeeded, so its delivery row is on the stamped conversation"
    )


# --- a delivery row cannot name a conversation that is absent (#452) --------


@pytest.mark.integration
async def test_the_store_enforces_foreign_keys_on_its_own_connection(tmp_path: Path) -> None:
    """``PRAGMA foreign_keys`` is off by default and per connection, so it is asked for.

    Read off the connection because there is no black-box observation to make, and
    that is the finding rather than a weakness of the test: every statement this
    module issues is already referentially clean — the one ``INSERT`` into
    ``deliveries`` proves the parent exists in the same transaction, and the drop
    deletes the rows explicitly — so switching enforcement off changes nothing the
    store itself does.
    Its whole effect is on a writer that is not this module, which is what the
    constraint exists for. Without this case, deleting the pragma would break no test.
    """
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    try:
        assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
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

        # The lever, because the rollback is only half of what this case observes:
        # the other half is that the caller learns *what* failed, and which of
        # ``_run_to_completion``'s two waiting paths delivers that is otherwise a
        # race. This case failed intermittently under load for exactly that reason
        # (#680) — the losing path answered with an `IndexError` from an empty
        # relay — so it now takes the path the defect lives on every time.
        with worker_finished_before_the_first_check(), pytest.raises(asyncio.CancelledError):
            await store.mark_active(conversation.id)

        # The store is still usable: the failed transaction released the
        # connection rather than leaving it mid-transaction.
        marked = await store.mark_active(conversation.id)
        assert marked.id == conversation.id
    finally:
        store.close()


async def test_a_delivery_row_duration_this_store_cannot_hold_is_this_seams_error(
    tmp_path: Path,
) -> None:
    """ADR-0205 §3: ``ConversationStoreError`` "where the store cannot be written".

    ``timedelta`` reaches ``timedelta.max`` — about 8.6e19 microseconds — which
    :class:`~ai_assistant.core.types.SpokenDelivery`'s partition admits and a signed
    64-bit SQLite ``INTEGER`` cannot hold. Left to the driver it is an
    ``OverflowError``, which is **not** a ``sqlite3.Error``, so it would cross this
    module's translation untouched and escape ``record_delivery``.

    **In this store's own tests and not the shared suite**: the bound is a property
    of a backend that persists 64-bit integers, and the canonical fake holds the value
    perfectly well. The row is read back afterwards, because a refusal that had
    already written half a delivery would be the worse failure.
    """
    store = SqliteConversationStore(path=str(tmp_path / "conversations.db"), now=_fixed_now)
    try:
        conversation = await store.start()
        unstamped = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
        await store.record_turn(
            conversation.id, episode_id="activation:a", occurred_at=_NOW, delivery=unstamped
        )

        with pytest.raises(ConversationStoreError, match="outside the range"):
            await store.record_delivery(
                conversation.id,
                episode_id="activation:a",
                delivery=SpokenDelivery(
                    state=SpokenDeliveryState.COMPLETE,
                    played=timedelta.max,
                    rendered=timedelta.max,
                ),
            )

        assert await store.deliveries(conversation.id, episode_ids=["activation:a"]) == {
            "activation:a": unstamped
        }, "the refusal wrote nothing, so a report that fits still lands"
    finally:
        store.close()


def _delivery_rows(database: Path) -> list[tuple[Any, ...]]:
    """Every row the ``deliveries`` table holds, read through a raw connection."""
    raw = sqlite3.connect(database, isolation_level=None)
    try:
        return [tuple(row) for row in raw.execute("SELECT * FROM deliveries")]
    finally:
        raw.close()


async def test_a_dropped_conversation_leaves_no_delivery_row_behind(tmp_path: Path) -> None:
    """ADR-0283 §6:7 against the table itself, which the contract can only infer.

    Deleted explicitly rather than left to the cascade: ``PRAGMA foreign_keys`` is
    per connection, and a drop that relied on it would leave
    the rows behind on any connection that had not enabled it.
    """
    path = tmp_path / "conversations.db"
    clock = [_NOW]
    store = SqliteConversationStore(path=path, now=lambda: clock[0])
    try:
        conversation = await store.start()
        kept = await store.start()
        unstamped = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
        for one in (conversation, kept):
            await store.record_turn(
                one.id, episode_id=f"activation:{one.id}", occurred_at=_NOW, delivery=unstamped
            )
        assert await store.stamp_deleted(conversation.id) is True
        clock[0] = _NOW + timedelta(days=1)

        assert await store.drop_if_eligible(conversation.id) is True

        assert [row[0] for row in _delivery_rows(path)] == [kept.id]
    finally:
        store.close()


async def test_delivery_rows_survive_a_reopen(tmp_path: Path) -> None:
    """They are durable state, which is the whole reason they are a table."""
    path = tmp_path / "conversations.db"
    unstamped = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    first = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await first.start()
        await first.record_turn(
            conversation.id, episode_id="activation:a", occurred_at=_NOW, delivery=unstamped
        )
        await first.record_turn(
            conversation.id, episode_id="activation:b", occurred_at=_NOW, delivery=unstamped
        )
        complete = SpokenDelivery(
            state=SpokenDeliveryState.COMPLETE,
            played=timedelta(seconds=4),
            rendered=timedelta(seconds=4),
        )
        assert await first.record_delivery(
            conversation.id, episode_id="activation:b", delivery=complete
        )
    finally:
        first.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert await reopened.deliveries(
            conversation.id, episode_ids=["activation:a", "activation:b"]
        ) == {"activation:a": unstamped, "activation:b": complete}
    finally:
        reopened.close()


async def test_the_schema_refuses_a_delivery_row_that_names_no_conversation(
    tmp_path: Path,
) -> None:
    """The ``deliveries`` table carries a cascading key (#452, ADR-0283 §6)."""
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO deliveries(conversation_id, episode_id, delivery_state) "
                "VALUES ('nobody', 'activation:a', 'unknown')"
            )
    finally:
        store.close()


@pytest.mark.parametrize(
    ("state", "played"),
    [("not-a-state", None), ("complete", "four seconds")],
    ids=["unknown-state", "non-integer-duration"],
)
async def test_a_corrupt_delivery_row_is_a_store_fault_on_the_read(
    tmp_path: Path, state: str, played: object
) -> None:
    """A row the store cannot decode is this seam's error, never a guessed delivery."""
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
        raw = sqlite3.connect(path, isolation_level=None)
        try:
            raw.execute(
                "INSERT INTO deliveries(conversation_id, episode_id, delivery_state, "
                "delivery_played, delivery_rendered) VALUES (?, 'activation:a', ?, ?, NULL)",
                (conversation.id, state, played),
            )
        finally:
            raw.close()

        with pytest.raises(ConversationStoreError):
            await store.deliveries(conversation.id, episode_ids=["activation:a"])
    finally:
        store.close()


async def test_a_base_exception_from_the_worker_reaches_the_caller() -> None:
    """ADR-0054's relay carries every failure, not only the ``Exception`` half (#680).

    ``_run_to_completion`` answers out of its relay lists alone whenever the worker
    finished before the wait loop's first check. A failure the relay never captured
    leaves both lists empty, so the caller is answered from an empty ``outcome`` —
    an ``IndexError`` standing in for the cause and not chained to it.

    The lever forces that path every time. Without it, which of the two paths a
    caller gets is a race, and a case that only sometimes reaches the defect is not
    evidence about it. ``KeyboardInterrupt`` stands in for the class; ``SystemExit``
    and a ``CancelledError`` raised by the work itself are the other members, and
    the rollback case above is that last one end to end.
    """

    def aborts() -> None:
        raise KeyboardInterrupt

    with worker_finished_before_the_first_check(), pytest.raises(KeyboardInterrupt):
        await _run_to_completion(aborts)


async def _spin(iterations: int = 50) -> None:
    """Yield to the event loop repeatedly so a pending cancellation can unwind."""
    for _ in range(iterations):
        await asyncio.sleep(0)


async def test_repeated_cancellation_does_not_consume_the_executor() -> None:
    """Absorbing a cancellation costs one executor job, however many arrive (#697).

    Each absorbed cancellation hands the loop something to wait on. A copy that
    submits a fresh blocking ``done.wait`` per cancellation leaves every earlier
    one running, because nothing can interrupt a thread parked in ``Event.wait``
    before the worker sets it — so repeated cancellation of *one* blocked call
    occupies the whole default pool and starves unrelated thread work, which turns
    a single stalled store operation into a process that can run none.

    Pinned in this module rather than once for the family, because ADR-0060
    refuses this helper a shared home: each copy is a separate place the reuse can
    be lost, and a single pin on one copy is exactly how six later copies came to
    be written with the defect rather than without it (#697).

    The pool is deliberately small and the probe is the assertion: counting
    threads would measure the executor's growth policy, while the probe measures
    the property — that something else can still run. The cancellation is still
    re-raised at the end, because a "fix" that stopped absorbing it would bound
    the pool by abandoning ADR-0054's invariant instead.

    The bounded executor is installed as this loop's default because the helper
    submits to ``None``; pytest-asyncio gives each test its own loop, so the
    substitution dies with the test and only the pool needs shutting down.
    """
    workers = 4
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=workers)
    loop.set_default_executor(executor)
    release = threading.Event()
    entered = threading.Event()

    def blocked() -> str:
        entered.set()
        if not release.wait(timeout=5):  # pragma: no cover - only on a hang
            msg = "the blocked worker was never released"
            raise AssertionError(msg)
        return "done"

    call = asyncio.ensure_future(_run_to_completion(blocked))
    try:
        assert await asyncio.to_thread(entered.wait, 5), "worker never entered"
        for _ in range(workers * 3):
            call.cancel()
            await _spin()

        probe = loop.run_in_executor(executor, lambda: "probe")
        finished, _ = await asyncio.wait([probe], timeout=1)
        assert finished, "the absorbed cancellations consumed the whole executor"

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await call
    finally:
        # Released and settled *before* the pool is shut down, so a failing run
        # reports the assertion above rather than a "cannot schedule new futures
        # after shutdown" from the helper still submitting into a closing pool.
        release.set()
        await asyncio.gather(call, return_exceptions=True)
        executor.shutdown(wait=True)


@pytest.mark.integration
async def test_a_closed_store_reports_the_seams_own_error(tmp_path: Path) -> None:
    """A backend failure crosses the seam as ``ConversationStoreError``, never raw."""
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    conversation = await store.start()
    store.close()

    with pytest.raises(ConversationStoreError):
        await store.get(conversation.id)
    with pytest.raises(ConversationStoreError):
        await store.record_turn(conversation.id, episode_id="activation:a", occurred_at=_NOW)
    with pytest.raises(ConversationStoreError):
        await store.export()


@pytest.mark.integration
async def test_opening_in_a_missing_directory_fails_with_the_seams_own_error(
    tmp_path: Path,
) -> None:
    """No connection to leak, and no raw ``sqlite3`` error escaping the constructor."""
    with pytest.raises(ConversationStoreError):
        SqliteConversationStore(path=tmp_path / "nope" / "conversations.db", now=_fixed_now)


async def test_a_path_the_driver_refuses_outright_is_still_the_seams_own_error() -> None:
    """A path with an embedded NUL leaves ``sqlite3.connect`` as a ``ValueError``.

    Neither a ``sqlite3.Error`` nor an ``OSError``, so a constructor catching only
    those lets a bare builtin escape the ``ConversationStoreError`` boundary this
    constructor documents — and this one already raises ``ValueError`` for a
    duration it refuses, so an untranslated one from the path would read as that
    instead (#1933). No filesystem is touched, so unlike its neighbour above this
    case is not an ``integration`` one: the driver refuses the argument before it
    opens anything.
    """
    with pytest.raises(ConversationStoreError, match="failed to open"):
        SqliteConversationStore(path="conversations\x00.db", now=_fixed_now)


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


# --- one transaction idiom (#563) ------------------------------------------


@contextlib.contextmanager
def _traced(store: SqliteConversationStore) -> Iterator[list[str]]:
    """Collect every statement the store's connection runs inside the block."""
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    try:
        yield statements
    finally:
        store._conn.set_trace_callback(None)


async def test_each_transaction_opens_in_the_form_its_call_site_asked_for() -> None:
    """The write form takes the lock up front; the read form does not, and both close.

    Deterministic where the staged races elsewhere in this module are not: a race
    proves the lock excludes once held, never *when* it was taken, so an
    implementation that began the transaction just before the write would satisfy
    every race and still leave the read-to-``BEGIN`` window #526 names wide open.
    The read form is asserted too, because a bare ``BEGIN`` is what makes several
    ``SELECT``s one snapshot without taking a write lock nothing here needs.
    """
    store = SqliteConversationStore(path=":memory:", now=_fixed_now)
    try:
        with _traced(store) as opened:
            conversation = await store.start()
        assert opened[0].strip().upper() == "BEGIN IMMEDIATE"
        assert opened[-1].strip().upper() == "COMMIT"

        with _traced(store) as read:
            await store.deliveries(conversation.id, episode_ids=["activation:a"])
        assert read[0].strip().upper() == "BEGIN"
        assert read[-1].strip().upper() == "COMMIT"

        with _traced(store) as stamped:
            await store.stamp_deleted(conversation.id)
        assert stamped[0].strip().upper() == "BEGIN IMMEDIATE"
        assert stamped[-1].strip().upper() == "COMMIT"
    finally:
        store.close()


async def test_a_backend_fault_inside_a_transaction_is_the_seams_own_error() -> None:
    """The translation is per store: this one owes ``ConversationStoreError``.

    Driven by writing on a closed connection, which is the cheapest real
    ``sqlite3.Error`` the transaction's own ``BEGIN`` can raise. The message form
    is asserted as well as the class, because it is what tells a reader *which*
    operation the backend refused.
    """
    store = SqliteConversationStore(path=":memory:", now=_fixed_now)
    store.close()

    with pytest.raises(ConversationStoreError, match="failed to start a conversation"):
        await store.start()


# --- ADR-0285 §4: no observation watermark, and nothing drops an old one ------


def _conversation_columns(database: Path) -> set[str]:
    """The column names ``conversations`` actually holds, read from the file."""
    raw = sqlite3.connect(database, isolation_level=None)
    try:
        return {str(row[1]) for row in raw.execute("PRAGMA table_info(conversations)")}
    finally:
        raw.close()


def _format_marker(database: Path) -> list[tuple[Any, ...]]:
    """The store format the file's marker records, read from the file."""
    raw = sqlite3.connect(database, isolation_level=None)
    try:
        return raw.execute("SELECT version FROM episode_record_format").fetchall()
    finally:
        raw.close()


def test_a_fresh_file_has_no_watermark_column(tmp_path: Path) -> None:
    """ADR-0285 §4:2: the schema creates no ``observed_through`` column.

    Read from the file, because the claim is about the table's shape and no read
    through the seam could show a column it never selects.
    """
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()

    assert _conversation_columns(path) == {
        "id",
        "started_at",
        "last_active_at",
        "last_turn_at",
        "deleted_at",
        "search_calls",
        "all_external_user_chosen",
    }


async def test_a_file_that_holds_the_old_column_opens_keeps_it_and_serves(
    tmp_path: Path,
) -> None:
    """ADR-0285 §4:3: nothing drops the column, and no store format advances for it.

    The file an earlier build wrote — the column present, a position recorded in it
    — is reopened by this one. It opens without a migration, every presenting read
    serves the conversation, a new conversation and a turn are written against the
    old shape, and afterwards the column, the recorded value and the format marker
    are exactly as they were: the column is left in place rather than dropped, and
    the marker does not move. That is ADR-0285 §4's "a development file that still
    holds the column opens and works, because nothing selects it".
    """
    path = tmp_path / "conversations.db"
    first = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        earlier = await first.start()
    finally:
        first.close()
    raw = sqlite3.connect(path, isolation_level=None)
    try:
        raw.execute("ALTER TABLE conversations ADD COLUMN observed_through INTEGER")
        raw.execute("UPDATE conversations SET observed_through = 7 WHERE id = ?", (earlier.id,))
    finally:
        raw.close()
    marker = _format_marker(path)

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        later = await reopened.start()
        await reopened.record_turn(earlier.id, episode_id="activation:a", occurred_at=_NOW)

        read = await reopened.get(earlier.id)
        assert read is not None
        assert read.last_turn_at == _NOW
        assert {one.id for one in await reopened.recent()} == {earlier.id, later.id}
        assert {one.id for one in (await reopened.export()).conversations} == {
            earlier.id,
            later.id,
        }
    finally:
        reopened.close()

    assert "observed_through" in _conversation_columns(path), "nothing drops the column"
    assert _format_marker(path) == marker, "no store format advances for the column"
    raw = sqlite3.connect(path, isolation_level=None)
    try:
        rows = dict(raw.execute("SELECT id, observed_through FROM conversations").fetchall())
    finally:
        raw.close()
    assert rows == {earlier.id: 7, later.id: None}, "the column is neither read nor written"


# --- ADR-0247 §5: the two vestigial columns and their migration stay ---------


async def test_start_writes_neither_vestigial_column_and_both_take_their_default(
    tmp_path: Path,
) -> None:
    """ADR-0247 §5: "read by nothing and **written by nothing**".

    ``start`` used to be the one place a draw was created, writing the flag ``1``
    explicitly. With the budget removed it names neither column, so both take the
    ``NOT NULL DEFAULT 0`` their declaration carries — which is also what makes a build
    that names only the columns it knows go on inserting against an upgraded file.

    Read from the file rather than through the store, because there is no longer any
    read that presents either value — which is the point.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = await store.start()
    finally:
        store.close()

    raw = sqlite3.connect(path, isolation_level=None)
    try:
        row = raw.execute(
            "SELECT search_calls, all_external_user_chosen FROM conversations WHERE id = ?",
            (conversation.id,),
        ).fetchone()
    finally:
        raw.close()
    assert row == (0, 0), "both columns take their declared default and neither is written"


async def test_an_insert_naming_only_the_pre_decision_columns_still_succeeds(
    tmp_path: Path,
) -> None:
    """The schema half of the same claim, pinned against the file rather than the code.

    A build written before ADR-0238 names only the columns it knows in its
    ``INSERT INTO conversations(...)``. ``NOT NULL DEFAULT 0`` is what keeps that
    build's ``start`` working against an upgraded database — a ``NOT NULL`` column with
    no default would make it fail, which is a refusal to serve arriving through the
    schema.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        raw = sqlite3.connect(path, isolation_level=None)
        try:
            raw.execute(
                "INSERT INTO conversations(id, started_at, last_active_at, last_turn_at, "
                "deleted_at) VALUES ('older-build', 0, 0, NULL, NULL)"
            )
        finally:
            raw.close()

        assert await store.get("older-build") is not None
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "shape", ["unmarked", "m36", "m37", "m38", "m39", "format5", "format6", "newer", "malformed"]
)
def test_incompatible_conversation_state_is_refused_without_mutation(
    tmp_path: Path, shape: str
) -> None:
    """Cutover neither upgrades nor deletes an old or unsupported database."""
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    with sqlite3.connect(path) as raw:
        if shape == "unmarked":
            raw.execute("DROP TABLE episode_record_format")
        elif shape == "m36":
            raw.execute("UPDATE episode_record_format SET version = 1")
        elif shape == "m37":
            raw.execute("UPDATE episode_record_format SET version = 2")
        elif shape == "m38":
            raw.execute("UPDATE episode_record_format SET version = 3")
        elif shape == "m39":
            raw.execute("UPDATE episode_record_format SET version = 4")
        elif shape == "format5":
            raw.execute("UPDATE episode_record_format SET version = 5")
        elif shape == "format6":
            raw.execute("UPDATE episode_record_format SET version = 6")
        elif shape == "newer":
            raw.execute("UPDATE episode_record_format SET version = 8")
        else:
            raw.execute("ALTER TABLE episode_record_format RENAME COLUMN version TO invalid")
    path.chmod(0o644)
    before = path.read_bytes()

    error = ConversationStoreError if shape == "malformed" else IncompatibleStateError
    with pytest.raises(error):
        SqliteConversationStore(path=path, now=_fixed_now)

    assert path.read_bytes() == before
    assert _mode_of(path) == 0o644


class _InitializationFails(sqlite3.Connection):
    """Fail after the marker and conversation table have been created."""

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        """Inject a storage failure partway through fresh initialization."""
        if sql.startswith("CREATE TABLE IF NOT EXISTS deliveries"):
            raise sqlite3.OperationalError("injected initialization failure")
        return super().execute(sql, parameters)


@pytest.mark.integration
def test_fresh_conversation_initialization_rolls_back_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed initial open leaves no marker advertising a partial schema."""
    path = tmp_path / "conversations.db"
    real_connect = sqlite3.connect

    def failing_connect(
        database: str, *, check_same_thread: bool, isolation_level: None
    ) -> sqlite3.Connection:
        return real_connect(
            database,
            check_same_thread=check_same_thread,
            isolation_level=isolation_level,
            factory=_InitializationFails,
        )

    with monkeypatch.context() as patched:
        patched.setattr(sqlite3, "connect", failing_connect)
        with pytest.raises(ConversationStoreError, match="injected initialization failure"):
            SqliteConversationStore(path=path, now=_fixed_now)

    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    SqliteConversationStore(path=path, now=_fixed_now).close()
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT version FROM episode_record_format").fetchall() == [
            (EPISODE_RECORD_FORMAT,)
        ]


# --- the chat space (ADR-0293) ------------------------------------------------

_PHONE = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)


def _said(text: str, message_id: str) -> NewMessage:
    return NewMessage(
        author=MessageAuthor.USER, text=text, device_id="phone", message_id=message_id
    )


@pytest.mark.integration
async def test_the_chat_space_survives_a_reopen_and_its_numbering_goes_on(tmp_path: Path) -> None:
    """Transcripts, devices, the stream and the bookkeeping are durable (ADR-0293 §1:4).

    The sequence counter is the one ``AUTOINCREMENT`` keeps, so a reopened store
    goes on numbering after the last change rather than reusing a number a device
    already holds as its cursor (§5:10).
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        await store.append_message(conversation, _said("one", "m-1"))
        await store.append_message(conversation, _said("two", "m-2"))
        await store.delete_message(conversation, 2)
        await store.take_in(conversation, positions=[1], activation_id="a-1")
        head = (await store.changes(after=0)).next_after
        before = await store.transcript(conversation)
    finally:
        store.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        assert await reopened.transcript(conversation) == before
        assert await reopened.my_devices() == (_PHONE,)
        assert await reopened.taken_in(conversation, positions=[1]) == {1: "a-1"}
        repeated = await reopened.append_message(conversation, _said("two", "m-2"))
        assert (repeated.outcome, repeated.position) == (SendOutcome.REPEATED, 2)
        await reopened.append_message(conversation, _said("three", "m-3"))
        (added,) = (await reopened.changes(after=head)).changes
        assert added.seq == head + 1
    finally:
        reopened.close()


@pytest.mark.integration
async def test_a_file_written_before_the_chat_space_opens_with_empty_transcripts(
    tmp_path: Path,
) -> None:
    """The chat tables are created on open; no existing row changes shape (ADR-0293).

    Simulated by dropping them from a file this build wrote, which leaves exactly
    what a build before them wrote: the format marker, the conversations and the
    delivery rows.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        conversation = (await store.start()).id
    finally:
        store.close()
    raw = sqlite3.connect(path)
    try:
        for table in (
            "messages",
            "chat_devices",
            "conversation_devices",
            "chat_changes",
            "taken_in",
        ):
            raw.execute(f"DROP TABLE {table}")
        raw.execute("DELETE FROM sqlite_sequence")
        raw.commit()
    finally:
        raw.close()

    reopened = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        page = await reopened.transcript(conversation)
        assert page is not None
        assert page.entries == ()
        assert await reopened.conversation_devices(conversation) == ()
        assert await reopened.set_conversation_devices(conversation, [_PHONE]) is True
        receipt = await reopened.append_message(conversation, _said("hello", "m-1"))
        assert receipt.position == 1
    finally:
        reopened.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("statement", "read"),
    [
        ("UPDATE messages SET cut_off = 7", "transcript"),
        ("UPDATE messages SET options = 'not json'", "transcript"),
        ("""UPDATE messages SET options = '"yes"'""", "transcript"),
        ("UPDATE messages SET options = '{}'", "transcript"),
        ("UPDATE messages SET author = 'stranger'", "transcript"),
        ("UPDATE messages SET written_at = 1.5", "export"),
        ("UPDATE chat_changes SET kind = 'mystery'", "changes"),
        (
            "UPDATE chat_changes SET devices = '[{\"device_id\": 3}]' WHERE devices IS NOT NULL",
            "changes",
        ),
        ("UPDATE chat_changes SET devices = '{}' WHERE devices IS NOT NULL", "changes"),
        ("""UPDATE chat_changes SET devices = '"phone"' WHERE devices IS NOT NULL""", "changes"),
        ("UPDATE conversation_devices SET access = 'everything'", "devices"),
        ("UPDATE taken_in SET activation_id = ' '", "taken_in"),
        ("UPDATE chat_changes SET kind = 'mystery'", "device_changes"),
        (
            "UPDATE chat_changes SET devices = '[{\"device_id\": 3}]' WHERE devices IS NOT NULL",
            "device_changes",
        ),
        ("UPDATE chat_changes SET devices = '{}' WHERE devices IS NOT NULL", "device_changes"),
        (
            "UPDATE chat_changes SET devices = 'not json' WHERE devices IS NOT NULL",
            "device_changes",
        ),
        ("UPDATE conversations SET started_at = 'then'", "device_conversations"),
    ],
)
async def test_a_corrupt_chat_row_is_a_store_fault_on_the_read(
    tmp_path: Path, statement: str, read: str
) -> None:
    """A row this module did not write reads as corruption, never as data."""
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        await store.append_message(conversation, _said("hello", "m-1"))
        await store.take_in(conversation, positions=[1], activation_id="a-1")
        store._conn.execute(statement)
        reads: dict[str, Callable[[], Awaitable[object]]] = {
            "transcript": lambda: store.transcript(conversation),
            "export": store.export,
            "changes": lambda: store.changes(after=0),
            "devices": lambda: store.conversation_devices(conversation),
            "taken_in": lambda: store.taken_in(conversation, positions=[1]),
            "device_changes": lambda: store.device_changes("phone", after=0),
            "device_conversations": lambda: store.device_conversations("phone"),
        }
        with pytest.raises(ConversationStoreError):
            await reads[read]()
    finally:
        store.close()


@pytest.mark.integration
async def test_a_deleted_message_keeps_no_text_in_the_file(tmp_path: Path) -> None:
    """ADR-0293 §5:12: the marker carries its id and that it was deleted, no text."""
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        await store.append_message(conversation, _said("my PIN is 1234", "m-1"))
        assert await store.delete_message(conversation, 1) is True
        page = await store.transcript(conversation)
        assert page is not None
        assert page.entries == (DeletedMessage(conversation_id=conversation, position=1),)
    finally:
        store.close()

    raw = sqlite3.connect(path)
    try:
        rows = raw.execute("SELECT text, author, written_at, options FROM messages").fetchall()
        changes = raw.execute("SELECT kind FROM chat_changes ORDER BY seq").fetchall()
    finally:
        raw.close()
    assert rows == [(None, None, None, None)]
    assert ("message_added",) not in changes


@pytest.mark.integration
async def test_a_repeated_send_over_a_corrupt_position_is_a_store_fault(tmp_path: Path) -> None:
    """The repeat path reads a stored position too, and a corrupt one is this seam's error."""
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        await store.append_message(conversation, _said("hello", "m-1"))
        store._conn.execute("UPDATE messages SET position = 0")
        with pytest.raises(ConversationStoreError):
            await store.append_message(conversation, _said("hello", "m-1"))
    finally:
        store.close()


@pytest.mark.integration
@pytest.mark.parametrize("act", ["append", "delete"])
async def test_a_change_that_cannot_be_recorded_leaves_the_transcript_as_it_was(
    tmp_path: Path, act: str
) -> None:
    """ADR-0293 §5:10: a change and its sequence number are one fact with the act.

    A trigger refuses every insert into the change stream, so the act's last write
    fails; the act must then have written nothing — no message, no marker, no
    repeat-recognition row — and, once the stream accepts writes again, the same
    act succeeds as if the failed one had never happened.
    """
    store = SqliteConversationStore(path=tmp_path / "conversations.db", now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        if act == "delete":
            await store.append_message(conversation, _said("hello", "m-1"))
        before_page = await store.transcript(conversation)
        before_changes = await store.changes(after=0)
        store._conn.execute(
            "CREATE TRIGGER refuse_changes BEFORE INSERT ON chat_changes "
            "BEGIN SELECT RAISE(ABORT, 'refused'); END"
        )

        failing = (
            store.append_message(conversation, _said("hello", "m-1"))
            if act == "append"
            else store.delete_message(conversation, 1)
        )
        with pytest.raises(ConversationStoreError):
            await failing

        assert await store.transcript(conversation) == before_page
        assert await store.changes(after=0) == before_changes
        store._conn.execute("DROP TRIGGER refuse_changes")
        if act == "append":
            receipt = await store.append_message(conversation, _said("hello", "m-1"))
            assert (receipt.outcome, receipt.position) == (SendOutcome.RECORDED, 1)
        else:
            assert await store.delete_message(conversation, 1) is True
        (recorded,) = (await store.changes(after=before_changes.next_after)).changes
        assert recorded.conversation_id == conversation
    finally:
        store.close()


@pytest.mark.integration
async def test_a_deletion_recorded_before_its_ends_were_kept_reaches_every_device(
    tmp_path: Path,
) -> None:
    """A ``conversation_deleted`` row with no ends is read as reaching every device.

    Such a row was written by a build before the deletion kept who its ends were
    (ADR-0296 §4:5). It carries an opaque id alone, and a device left holding a
    deleted conversation is the worse error.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        conversation = (await store.start()).id
        await store.stamp_deleted(conversation)
        store._conn.execute(
            "UPDATE chat_changes SET devices = NULL WHERE kind = 'conversation_deleted'"
        )

        for device in ("phone", "stranger"):
            seen = (await store.device_changes(device, after=0)).changes
            assert [one.conversation_id for one in seen if one.kind == "conversation_deleted"] == [
                conversation
            ]
    finally:
        store.close()


@pytest.mark.integration
async def test_a_devices_page_is_filled_across_batches_in_one_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A device passed over for many changes still gets a full page, in sequence order."""
    monkeypatch.setattr(conversation_store, "_DEVICE_CHANGES_BATCH", 2)
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.set_my_devices([_PHONE])
        mine = (await store.start()).id
        await store.set_my_devices([ChatDevice(device_id="laptop", access=DeviceAccess.READ)])
        other = (await store.start()).id
        for index in range(3):
            await store.append_message(other, NewMessage(author=MessageAuthor.ASSISTANT, text="x"))
            await store.append_message(mine, _said(str(index), f"m-{index}"))
        head = (await store.changes(after=0)).next_after

        whole = await store.device_changes("phone", after=0)
        first = await store.device_changes("phone", after=0, limit=4)

        assert [one.conversation_id for one in whole.changes] == [
            None,
            mine,
            None,
            mine,
            mine,
            mine,
        ]
        assert whole.next_after == head
        assert first.changes == whole.changes[:4]
        assert first.next_after == whole.changes[3].seq
    finally:
        store.close()


def test_a_devices_conversations_are_indexed_by_device(tmp_path: Path) -> None:
    """A device's own reads and its removal do not scan every conversation's devices."""
    path = tmp_path / "conversations.db"
    SqliteConversationStore(path=path, now=_fixed_now).close()
    raw = sqlite3.connect(path)
    try:
        plan = raw.execute(
            "EXPLAIN QUERY PLAN SELECT conversation_id FROM conversation_devices "
            "WHERE device_id = ?",
            ("phone",),
        ).fetchall()
    finally:
        raw.close()
    assert any("conversation_devices_device" in str(row[-1]) for row in plan)
