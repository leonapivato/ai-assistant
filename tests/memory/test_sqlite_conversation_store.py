"""SqliteConversationStore: the shared conformance suite, plus what only it owes.

The suite holds the contract; this module holds the properties that belong to a
*persistent* store — that the file it creates is owner-only (ADR-0004 §4), that
what it wrote survives a reopen, and that a broken backend surfaces as the seam's
own error rather than as a raw ``sqlite3`` failure.
"""

from __future__ import annotations

import asyncio
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conversation_store_contract import (
    ConversationStoreContract,
    ConversationStoreFactory,
    MovableClock,
)

from ai_assistant.core.errors import ConversationStoreError, UnknownConversationError
from ai_assistant.core.types import ParkedBinding
from ai_assistant.memory.conversation_store import SqliteConversationStore

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from ai_assistant.core.protocols import ConversationStore

#: The store's own defaults, restated here rather than imported (see the fake's
#: binding for why).
_TAIL_DEFAULT = 20
_PURGE_DEFAULT = 100

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
async def test_a_rollback_journal_is_owner_only_too(tmp_path: Path) -> None:
    """ADR-0004 §4 reaches the sidecars, not only the database file.

    SQLite copies the database file's mode onto a rollback journal it creates
    for it, so the restriction has to land before the first write rather than
    after the schema is built. A journal written in between would carry the
    process umask, and an interrupted write leaves it on disk holding Tier 1
    pages — a base file at ``0600`` beside a world-readable copy of its pages.

    The journal is provoked through a raw connection because the store never
    leaves one behind: it commits every transaction it opens.
    """
    path = tmp_path / "conversations.db"
    store = SqliteConversationStore(path=path, now=_fixed_now)
    try:
        await store.start()

        raw = sqlite3.connect(path)
        try:
            raw.execute("BEGIN IMMEDIATE")
            raw.execute("UPDATE conversations SET last_active_at = last_active_at")
            mode = _journal_mode(path)
            assert mode is not None, "the write should have opened a rollback journal"
            assert mode == 0o600
            raw.execute("ROLLBACK")
        finally:
            raw.close()
    finally:
        store.close()


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
async def test_a_legacy_orphan_survives_the_rebuild_and_is_reported(tmp_path: Path) -> None:
    """The copy runs with enforcement still off, deliberately.

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
