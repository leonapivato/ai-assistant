"""``SqliteRecipientGrantStore``: the shared suites, and what only a file can say.

The durable store bound to all three of ADR-0193 §1's faces, plus the cases the
shared suites cannot state because they are about **bytes on disk** rather than
about a store's surface: the file mode, the schema marker, and a record that
survives a restart.

ADR-0049 §5's division is what puts them here: a clause a fake can exhibit belongs
in the shared suite, and one that is a property of *persisting a serialised
payload and rebuilding it* belongs in the implementation's own tests, where there
are bytes to seed.
"""

from __future__ import annotations

import sqlite3
import stat
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from recipient_builders import ALICE, AT, BOB, EXPIRES, MovableClock, binding, member, request
from recipient_grant_contract import (
    CEILING,
    RecipientGrantStoreContract,
)

from ai_assistant.core.errors import RecipientGrantError
from ai_assistant.permissions.recipient_grants import SqliteRecipientGrantStore
from ai_assistant.testing.recipient_grants import recipient_grant, recipient_revocation_of

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import RecipientGrantStore


class TestSqliteRecipientGrantStoreContract(RecipientGrantStoreContract):
    """Runs the durable store through all three shared suites.

    The two narrow suites bind **this same object**, which is ADR-0193 §1's "one
    concrete store satisfies all three faces" tested against the durable store
    rather than only against the fake — the half that matters, because the fake
    and the store could otherwise agree with their own suites and disagree with
    each other.
    """

    @pytest.fixture(autouse=True)
    def _directory(self, tmp_path: Path) -> None:
        """Stash the directory the stores this case builds live in.

        An autouse fixture rather than a constructor argument because pytest
        instantiates the class per test and :meth:`make_store` is a plain method
        the suite calls from inside one — so there is no other moment at which a
        path could reach it.
        """
        self._tmp = tmp_path
        self._minted = 0
        self._paths: dict[int, Path] = {}

    def make_store(self, *, max_outstanding: int, now: MovableClock) -> RecipientGrantStore:
        """A **fresh** store, in its own file, at ``max_outstanding``."""
        self._minted += 1
        path = self._tmp / f"recipient_grants-{self._minted}.db"
        store = SqliteRecipientGrantStore(path=path, max_outstanding=max_outstanding, now=now)
        self._paths[id(store)] = path
        return store

    def reopened(self, store: RecipientGrantStore, *, max_outstanding: int) -> RecipientGrantStore:
        """The **same file**, opened again under a different ceiling.

        Which is what a deployment does when it edits
        ``Settings.recipient_grant_max_outstanding`` and restarts, and the reason
        the durable store answers the admission-not-eviction clause more directly
        than the fake can: the records are on disk and nothing about reopening
        re-admits them.
        """
        path = self._paths[id(store)]
        reopened = SqliteRecipientGrantStore(
            path=path, max_outstanding=max_outstanding, now=MovableClock()
        )
        self._paths[id(reopened)] = path
        return reopened


# --- what only a file can say ------------------------------------------------


def test_a_negative_ceiling_is_refused_at_construction(tmp_path: Path) -> None:
    """Zero is meaningful and admitted; a negative names no bound (ADR-0193 §1).

    An implementation special-casing only zero would accept ``-1`` while refusing
    every granting write for a reason no message explains — which is why
    ``Settings`` carries ``ge=0`` and why this constructor states the same rule
    rather than trusting it.
    """
    with pytest.raises(ValueError, match="negative"):
        SqliteRecipientGrantStore(path=tmp_path / "grants.db", max_outstanding=-1)


def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """A canonical destination is a recipient of the user's (ADR-0004 §4, §7).

    Restricted **before** the first statement, so a rollback journal SQLite opens
    for the file inherits the mode rather than the process umask — an interrupted
    write otherwise leaves one on disk holding Tier 1 pages (#489).
    """
    path = tmp_path / "grants.db"

    SqliteRecipientGrantStore(path=path, max_outstanding=CEILING).close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_grant_survives_a_restart(tmp_path: Path) -> None:
    """Durability is the whole reason this implementation exists.

    Asserted over a **reopened** store rather than over the same object, because
    what is under test is that the record is bytes on disk and not state in a
    process — the property a fake cannot have and the one a user's standing policy
    depends on.
    """
    path = tmp_path / "grants.db"
    granted = recipient_grant(member(ALICE), grant_id="g-1")

    async def write() -> None:
        store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
        try:
            await store.record(granted)
        finally:
            store.close()

    async def read() -> object:
        store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING, now=MovableClock())
        try:
            return await store.covering(request(binding(ALICE)))
        finally:
            store.close()

    import asyncio  # noqa: PLC0415 — two loops, deliberately: this is the restart

    asyncio.run(write())

    assert asyncio.run(read()) == granted


def test_a_cleared_id_is_free_again_across_a_restart(tmp_path: Path) -> None:
    """``clear`` retains **nothing** — no record, no id, no tombstone (ADR-0193 §1).

    Across a restart specifically, because that is where a durable store could
    have kept something a fake could not: a row in another table, a marker in
    ``meta``, a sequence. Round 3 of ADR-0193's loop reached for exactly such a
    tombstone and round 5 killed it; what stands in its place is the row's own
    ``subject_digest``, which is ``AuditTrail.record``'s to check.
    """
    import asyncio  # noqa: PLC0415 — three loops, deliberately: two restarts

    path = tmp_path / "grants.db"

    async def act(step: str) -> object:
        store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
        try:
            if step == "record":
                return await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
            if step == "clear":
                return await store.clear()
            return await store.record(recipient_grant(member(BOB), grant_id="g-1"))
        finally:
            store.close()

    asyncio.run(act("record"))
    assert asyncio.run(act("clear")) == 1

    assert asyncio.run(act("re-record")) == "g-1"


def test_only_the_history_is_erased(tmp_path: Path) -> None:
    """Burning the book leaves a database this code can still open (ADR-0193 §9).

    The ``meta`` schema marker describes the file's *shape* rather than the user's
    history, so ``clear`` leaves it — and a store that dropped it would make the
    next open stamp a fresh marker over a file it had not created, which is the
    one case ``_check_schema_version`` cannot tell from a downgrade.
    """
    import asyncio  # noqa: PLC0415 — a restart, as above

    path = tmp_path / "grants.db"

    async def act() -> None:
        store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
        try:
            await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
            await store.clear()
        finally:
            store.close()

    asyncio.run(act())

    connection = sqlite3.connect(path)
    try:
        stored = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchall()
    finally:
        connection.close()

    assert stored == [("1",)]


def test_a_database_labelled_with_another_schema_is_refused(tmp_path: Path) -> None:
    """Refused at open rather than read blindly (ADR-0049 §1).

    Reading it would let a downgrade construct successfully and fail later with a
    raw SQLite error — a fault to report at open, and one this layer owes as its
    own error class rather than as whatever the driver threw.
    """
    path = tmp_path / "grants.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RecipientGrantError, match="schema_version=2"):
        SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)


def test_a_store_that_cannot_be_opened_reports_this_layers_error(tmp_path: Path) -> None:
    """A bad path is this layer's fault to report, never a raw builtin (#238)."""
    with pytest.raises(RecipientGrantError, match="failed to open"):
        SqliteRecipientGrantStore(path=tmp_path / "missing" / "grants.db", max_outstanding=CEILING)


async def test_a_row_that_no_longer_validates_is_a_store_fault(tmp_path: Path) -> None:
    """The **base** class, not the refusal (ADR-0193 §1).

    Nothing the caller handed in was refused — the store itself is unreadable —
    and a consumer's fail-closed branch is exactly the right response. A store
    answering ``None`` here would report "no grant covers this" for a corrupted
    file, which is the one thing ADR-0193 §1 says ``None`` never means.
    """
    path = tmp_path / "grants.db"
    store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
    try:
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
        store._conn.execute(
            "UPDATE recipient_grants SET data = ? WHERE id = ?", ('{"id": "g-1"}', "g-1")
        )
        store._conn.commit()

        with pytest.raises(RecipientGrantError, match="no longer validates"):
            await store.outstanding("g-1")
    finally:
        store.close()


async def test_the_unique_index_survives_a_bug_in_the_revocation_check(
    tmp_path: Path,
) -> None:
    """One revocation per grant, held by the schema and not only by the read.

    The mechanical sibling of ``grants_revokes`` on the source-grant store: the
    read exists to give the friendlier error, and the index is what makes the
    invariant true even if a later edit lost the read.
    """
    path = tmp_path / "grants.db"
    store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
    try:
        granted = recipient_grant(member(ALICE), grant_id="g-1")
        await store.record(granted)
        await store.record(recipient_revocation_of(granted, grant_id="r-1"))
        second = recipient_revocation_of(granted, grant_id="r-2")

        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO recipient_grants("
                "id, decided_at_us, expires_at_us, revokes, data"
                ") VALUES (?, ?, ?, ?, ?)",
                (second.id, 0, 1, second.revokes, second.model_dump_json()),
            )
    finally:
        store.close()


async def test_an_expired_grant_still_occupies_its_slot_across_a_restart(
    tmp_path: Path,
) -> None:
    """The outstanding-not-live substitution, over bytes rather than objects.

    A store reopened long after every grant it holds has expired still refuses a
    new one, because ``record`` reads no clock and the count is over outstanding
    records. The recourse is the revocation the user can always make, and the
    shared suite states the same rule; this is the half that could only be lost by
    a durable store recomputing the count from a clock at open.
    """
    path = tmp_path / "grants.db"
    clock = MovableClock()
    store = SqliteRecipientGrantStore(path=path, max_outstanding=1, now=clock)
    try:
        await store.record(recipient_grant(member(ALICE), grant_id="g-1"))
    finally:
        store.close()

    later = MovableClock(EXPIRES + timedelta(days=365))
    reopened = SqliteRecipientGrantStore(path=path, max_outstanding=1, now=later)
    try:
        assert await reopened.standing() == []

        with pytest.raises(RecipientGrantError):
            await reopened.record(recipient_grant(member(BOB), grant_id="g-2"))
    finally:
        reopened.close()


async def test_a_record_reloads_as_the_record_that_was_written(tmp_path: Path) -> None:
    """The parity the digest depends on, over an actual serialisation (ADR-0193 §6).

    ``authorised_subject`` is computed over a grant read back out of *this* store
    and compared against a digest computed before it was written, so a store whose
    round trip changed any digested field — an instant losing its offset, a tuple
    losing its order — would make every route-(b) row fail its own check on the
    first restart. A fake holding objects cannot exhibit it.
    """
    path = tmp_path / "grants.db"
    granted = recipient_grant(member(BOB), member(ALICE), grant_id="g-1", decided_at=AT)
    store = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING)
    try:
        await store.record(granted)
    finally:
        store.close()

    reopened = SqliteRecipientGrantStore(path=path, max_outstanding=CEILING, now=MovableClock())
    try:
        reloaded = await reopened.outstanding("g-1")
    finally:
        reopened.close()

    assert reloaded == granted
    assert reloaded is not None
    assert reloaded.subject_digest == granted.subject_digest
    assert reloaded.destinations == granted.destinations
