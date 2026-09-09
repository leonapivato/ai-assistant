"""The durable ``DestinationTrustStore`` on SQLite (ADR-0238 §1).

The shared suite bound to the production store, plus the arms that are about a *file*
rather than about the contract: the schema marker, the objects held to their own
definitions, the owner-only mode, and the one mutation this table admits.
"""

from __future__ import annotations

import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest
from destination_trust_store_contract import (
    LATER,
    DestinationTrustStoreContract,
    trust_record,
)
from recipient_builders import ALICE, member

from ai_assistant.core.errors import InvalidDestinationTrustError
from ai_assistant.core.types import DestinationTrust
from ai_assistant.permissions.destination_trust import SqliteDestinationTrustStore

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.protocols import DestinationTrustStore


class TestSqliteDestinationTrustStoreContract(DestinationTrustStoreContract):
    """The durable store against every clause of ADR-0238 §1."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SqliteDestinationTrustStore:
        return SqliteDestinationTrustStore(path=tmp_path / "destination_trust.db")

    def reopened(self, store: DestinationTrustStore) -> DestinationTrustStore:
        """A second handle over the same file — what a restart gets."""
        assert isinstance(store, SqliteDestinationTrustStore)
        return SqliteDestinationTrustStore(path=store._path)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "destination_trust.db"


def test_the_database_file_is_owner_only(path: Path) -> None:
    """ADR-0004 §4, and restricted before the first statement.

    SQLite copies the database file's mode onto every rollback journal it creates for
    it, so a journal opened while the file still carried the process umask would be
    world-readable — and an interrupted write leaves it on disk holding Tier 1 pages
    (#489).
    """
    SqliteDestinationTrustStore(path=path).close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_unlabelled_database_is_stamped_rather_than_migrated(path: Path) -> None:
    """Version 1 is the first shape this store has ever had, so there is nothing to
    migrate from — an unlabelled file is one this open is creating."""
    store = SqliteDestinationTrustStore(path=path)
    store.close()

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() == (
            "1",
        )


def test_a_database_labelled_with_a_schema_this_code_cannot_read_is_refused(path: Path) -> None:
    """Refused rather than read blindly: rows under an unknown shape cannot be trusted
    to say what the user chose."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")

    with pytest.raises(InvalidDestinationTrustError, match="schema_version=2"):
        SqliteDestinationTrustStore(path=path)


def test_a_file_holding_a_table_of_this_name_that_is_not_this_store_is_refused(
    path: Path,
) -> None:
    """``CREATE TABLE IF NOT EXISTS`` is a no-op against a table already there under
    that name **whatever shape it has**.

    Its generated ``revoked_at`` projection would then read as ``NULL`` for every row —
    because the insert writes only the two stored columns — and **every stored record
    would answer as live**, revoked ones included. That is the exact failure the
    generated columns exist to make impossible, walked around rather than through.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE destination_trust(id TEXT, data TEXT, revoked_at TEXT)")

    with pytest.raises(InvalidDestinationTrustError, match="is not the one this store defines"):
        SqliteDestinationTrustStore(path=path)


async def test_the_table_admits_no_mutation_but_a_revocation(path: Path) -> None:
    """ADR-0238 §1's "a revocation … rewrites no recorded decision", said to SQLite.

    The trigger compares the two blobs with ``revoked_at`` removed from each, so every
    other field is frozen against ``UPDATE`` — the invariant is enforced by the
    database rather than by the module's care, the way a ``UNIQUE`` index enforces
    write-once. It is not a boundary against an actor who can already run arbitrary SQL
    against the file, who could drop it as easily as run the ``UPDATE``; ADR-0004 §4's
    owner-only mode is where that question is answered.
    """
    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match="never edited"):
        conn.execute(
            "UPDATE destination_trust SET data = json_set(data, '$.id', 'forged')",
        )


async def test_the_ordering_key_cannot_be_rewritten(path: Path) -> None:
    """The same trigger's second limb, and it guards a *listing* rather than a value.

    ``established_at_us`` orders both reads, so a row whose key was altered to sort
    late would be handed to a caller in the wrong place with every row on it valid.
    """
    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match="never edited"):
        conn.execute("UPDATE destination_trust SET established_at_us = 0")


async def test_a_row_that_no_longer_validates_is_a_fault_rather_than_an_absent_record(
    path: Path,
) -> None:
    """A corrupt row is reported, not skipped — on ``live`` and ``export``.

    Skipping would let a **revoked** record vanish from the export that is the user's
    evidence of their own history, and would let an unreadable live record silently
    narrow what the store says the user chose.
    """
    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))
    store.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM destination_trust")
        conn.execute(
            "INSERT INTO destination_trust(established_at_us, data) VALUES (?, ?)",
            (0, '{"id": "t-1"}'),
        )

    reopened = SqliteDestinationTrustStore(path=path)
    with pytest.raises(InvalidDestinationTrustError, match="no longer validates"):
        await reopened.live()
    with pytest.raises(InvalidDestinationTrustError, match="no longer validates"):
        await reopened.export()


async def test_an_unreadable_store_answers_unchosen_rather_than_raising(path: Path) -> None:
    """ADR-0238 §1's fail-closed clause, over the durable store's own fault path.

    "Where a record cannot be read" is a state a *file* can actually be in, so this is
    where the clause earns its keep: the one read a policy path depends on answers
    ``UNCHOSEN`` instead of raising into a call site that would have to catch it
    correctly.
    """
    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))
    assert await store.trust_of([member(ALICE)]) is DestinationTrust.USER_CHOSEN
    store.close()

    assert await store.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN


async def test_a_revocation_survives_a_restart(path: Path) -> None:
    """Durable in both directions: the record *and* its withdrawal."""
    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))
    await store.revoke("t-1", LATER)
    store.close()

    reopened = SqliteDestinationTrustStore(path=path)

    assert await reopened.trust_of([member(ALICE)]) is DestinationTrust.UNCHOSEN
    assert [held.revoked_at for held in await reopened.export()] == [LATER]


def test_a_path_whose_parent_does_not_exist_is_this_layers_error(tmp_path: Path) -> None:
    """A bad path is reported by this layer rather than as a raw driver complaint."""
    with pytest.raises(InvalidDestinationTrustError, match="failed to open"):
        SqliteDestinationTrustStore(path=tmp_path / "absent" / "destination_trust.db")


async def test_a_naive_revocation_instant_is_refused(path: Path) -> None:
    """The store is durable **and** ordered, so a naive instant is refused by name.

    :attr:`RecipientGrant.decided_at`'s reason one store over, and the reason the
    instant is rendered through the record's own serializer rather than by a second
    spelling here.
    """
    import datetime  # noqa: PLC0415 — the naive instant is the subject

    store = SqliteDestinationTrustStore(path=path)
    await store.record(trust_record(ALICE, record_id="t-1"))

    with pytest.raises(InvalidDestinationTrustError):
        await store.revoke("t-1", datetime.datetime(2026, 9, 9, 12, 0))  # noqa: DTZ001
