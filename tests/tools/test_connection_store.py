"""The connection store's own obligations (ADR-0149 §3, §5, §8).

The provisioner's tests drive this store through an act; these drive it directly,
because three of its properties are about the *file* rather than about an act:
that an append survives the process, that the file is owner-only, and that a
database this build cannot read is refused rather than read blindly.
"""

from __future__ import annotations

import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    ACCOUNT_IDENTITY_MAX_BYTES,
    ProvisioningState,
    SecretName,
    SecretScope,
)
from ai_assistant.tools.connection_store import ConnectionEntry, SqliteConnectionStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def slot(key: str) -> SecretName:
    """A credential slot in the one scope this store's writer is bound to."""
    return SecretName(scope=SecretScope.INTEGRATION, key=key)


def entry(
    reference: str = "ref-1",
    revision: int = 1,
    *,
    state: ProvisioningState | None = ProvisioningState.PENDING,
    key: str | None = "slot-1",
) -> ConnectionEntry:
    """A provisioning entry, or a removal entry where ``state`` is ``None``."""
    removal = state is None
    return ConnectionEntry(
        reference=reference,
        revision=revision,
        identity=None if removal else "owner@example.com",
        state=state,
        slot=None if removal or key is None else slot(key),
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SqliteConnectionStore]:
    """An empty store on a real file."""
    opened = SqliteConnectionStore(path=tmp_path / "connections.db")
    yield opened
    opened.close()


# --- the file ---------------------------------------------------------------


async def test_an_append_survives_a_reopen(tmp_path: Path) -> None:
    """ADR-0149 §3: the store is durable hub-side state, not a cache.

    This is the property the whole delete right rests on: the store is the only
    durable list of the credential slots the provisioner wrote (ADR-0149 §8), so a
    store that forgot on restart would orphan Tier 0 data nothing could ever name.
    """
    path = tmp_path / "connections.db"
    first = SqliteConnectionStore(path=path)
    await first.append(entry(), expected_latest=None)
    first.close()

    second = SqliteConnectionStore(path=path)
    try:
        held = await second.latest("ref-1")
    finally:
        second.close()

    assert held is not None
    assert held.entry.revision == 1


def test_the_database_file_is_owner_only(tmp_path: Path) -> None:
    """ADR-0004 §4: a Tier 1 store's file is created owner-only."""
    path = tmp_path / "connections.db"
    opened = SqliteConnectionStore(path=path)
    opened.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_schema_this_build_cannot_read_is_refused(tmp_path: Path) -> None:
    """ADR-0049 §1: refused at open rather than read blindly.

    A downgrade would otherwise construct successfully and fail later with a raw
    SQLite error, which is a fault to report at open.
    """
    path = tmp_path / "connections.db"
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '99')")
    conn.close()

    with pytest.raises(ConnectionStoreError, match="schema_version=99"):
        SqliteConnectionStore(path=path)


async def test_an_entry_that_no_longer_validates_is_reported(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0149 §3: a corrupted row is a fault to report, never a record to hand on."""
    await store.append(entry(), expected_latest=None)
    conn: sqlite3.Connection = store._conn
    with conn:
        conn.execute('UPDATE entries SET data = \'{"reference": ""}\'')

    with pytest.raises(ConnectionStoreError, match="no longer validates"):
        await store.live()


async def test_a_row_whose_projection_disagrees_with_its_entry_is_reported(
    store: SqliteConnectionStore,
) -> None:
    """The duplicate representation is checked rather than trusted.

    ``permissions/grants.py`` states the hazard for its own shadow columns: "two
    spellings of 'is this source granted' are two answers free to drift apart, and
    the one that drifted would still pass its own half of the suite". This store
    keeps ``reference`` and ``revision`` so SQLite can narrow and group, and no
    ``state`` or ``slot`` column at all — so the only way a projection can decide
    anything is by selecting rows, and a row whose projection does not describe its
    own entry is a fault to report rather than an answer to give.
    """
    await store.append(entry(), expected_latest=None)
    conn: sqlite3.Connection = store._conn
    with conn:
        conn.execute("UPDATE entries SET revision = 99")

    with pytest.raises(ConnectionStoreError, match="the store is corrupt"):
        await store.live()


async def test_liveness_is_not_decided_by_a_column_a_file_edit_can_flip(
    store: SqliteConnectionStore,
) -> None:
    """An active record stays live however the table beside it is edited.

    An earlier draft projected ``state`` and made ``state IS NOT NULL`` the
    liveness predicate, so an ``UPDATE`` on that column silently reported a
    connected account as gone while its JSON payload was still a valid *active*
    record — a change of meaning rather than a corruption the store reports. There
    is no such column now, which is what this case pins.
    """
    await store.append(entry(state=ProvisioningState.ACTIVE), expected_latest=None)
    conn: sqlite3.Connection = store._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info(entries)")}

    assert columns == {"sequence", "reference", "revision", "data"}
    assert [record.state for record in await store.live()] == [ProvisioningState.ACTIVE]


@pytest.mark.parametrize(
    "identity",
    [
        pytest.param("owner\nadmin", id="line-break"),
        pytest.param("owner\u2028admin", id="unicode-line-separator"),
        pytest.param("owner\x07", id="control-character"),
        pytest.param("o" * (ACCOUNT_IDENTITY_MAX_BYTES + 1), id="over-the-bound"),
    ],
)
async def test_a_persisted_identity_outside_the_shape_is_reported_on_the_way_out(
    store: SqliteConnectionStore, identity: str
) -> None:
    """ADR-0149 §4 binds the store, so the read enforces it as well as the write.

    A row whose JSON ``identity`` was edited stays a syntactically valid entry:
    the reference, the revision, the state and the slot all still validate, so the
    decode alone lets it through. A store that enforced only on append would hand
    a caller an identity it would refuse to accept, which is one file edit away.
    """
    await store.append(entry(), expected_latest=None)
    conn: sqlite3.Connection = store._conn
    with conn:
        conn.execute("UPDATE entries SET data = json_set(data, '$.identity', ?)", (identity,))

    with pytest.raises(ConnectionStoreError):
        await store.live()


@pytest.mark.parametrize(
    "corrupted",
    [
        pytest.param("'not-a-number'", id="text"),
        pytest.param("1.5", id="fractional"),
        pytest.param("X'00'", id="blob"),
    ],
)
async def test_a_projection_this_code_cannot_read_is_reported_not_coerced(
    store: SqliteConnectionStore, corrupted: str
) -> None:
    """Every read raises from the ``AssistantError`` hierarchy, corruption included.

    ``sqlite3`` hands back whatever the file holds and ``revision`` carries no
    affinity strong enough to promise otherwise, so a bare ``int(...)`` on a
    hand-edited row raises ``ValueError`` — which is not an
    :class:`~ai_assistant.core.errors.AssistantError` and would leave this layer's
    error boundary through the hole #238 records on the audit trail.

    **The fractional case is why this refuses rather than converts.** ``int(1.5)``
    is ``1``, which decodes against a JSON revision of 1 and passes the projection
    check — while ``recent``'s ``GROUP BY revision`` has already split that one act
    into two groups reported at the same revision. A conversion hides it; a type
    test does not.

    ``sequence`` is not parametrised beside ``revision`` because SQLite refuses
    the same edit outright: it is the table's ``INTEGER PRIMARY KEY``, so the
    rowid rule rejects a non-integer with a datatype mismatch. Its check is kept
    anyway, on the same footing as every other read of a value this code did not
    just write.
    """
    await store.append(entry(), expected_latest=None)
    conn: sqlite3.Connection = store._conn
    with conn:
        conn.execute(f"UPDATE entries SET revision = {corrupted}")  # noqa: S608

    with pytest.raises(ConnectionStoreError, match="the store is corrupt"):
        await store.latest("ref-1")


# --- ADR-0148 §6's compare-and-swap, as one primitive -----------------------


async def test_the_first_append_refuses_a_reference_the_store_already_holds(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0151 §3: the half of the mint's uniqueness a store can establish itself."""
    assert await store.append(entry(), expected_latest=None) is not None

    assert await store.append(entry(revision=2), expected_latest=None) is None


async def test_an_append_against_a_stale_observation_does_not_land(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0149 §3: an act appends only if the entry it observed is still the latest."""
    first = await store.append(entry(), expected_latest=None)
    assert first is not None
    await store.append(entry(revision=2, key="slot-2"), expected_latest=first.sequence)

    displaced = await store.append(entry(revision=2, key="slot-3"), expected_latest=first.sequence)

    assert displaced is None


async def test_an_append_below_the_latest_revision_is_refused(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0148 §6: a revision is never reused and never decreases.

    Not a displacement — a caller that computed a revision below one the reference
    already holds — so the store refuses rather than filing an entry that breaks
    the monotonicity a credential read's "unchanged since I looked" rests on.
    """
    first = await store.append(entry(revision=5), expected_latest=None)
    assert first is not None

    with pytest.raises(ConnectionStoreError, match="monotonicity"):
        await store.append(entry(revision=4, key="slot-2"), expected_latest=first.sequence)


# --- ADR-0149 §3's projections ----------------------------------------------


async def test_a_removed_reference_has_no_live_record(store: SqliteConnectionStore) -> None:
    """ADR-0149 §3: a reference whose latest entry is a removal has no live record."""
    first = await store.append(entry(), expected_latest=None)
    assert first is not None
    await store.append(entry(revision=2, state=None), expected_latest=first.sequence)

    assert await store.live() == ()


async def test_a_pending_record_is_live(store: SqliteConnectionStore) -> None:
    """ADR-0151 §4: ``connected`` does not omit a reference whose live record is pending."""
    await store.append(entry(), expected_latest=None)

    live = await store.live()

    assert [record.state for record in live] == [ProvisioningState.PENDING]


async def test_one_act_is_one_row_however_many_entries_it_wrote(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0151 §9: one row per ``(reference, revision)``, carrying the furthest state.

    The store writes the record twice per act — pending, then active — and that
    granularity is `tools/`-internal.
    """
    first = await store.append(entry(), expected_latest=None)
    assert first is not None
    await store.append(entry(state=ProvisioningState.ACTIVE), expected_latest=first.sequence)

    acts = await store.recent(limit=10)

    assert [(act.revision, act.account and act.account.state) for act in acts] == [
        (1, ProvisioningState.ACTIVE)
    ]


# --- ADR-0149 §5's deletion set and §8's purge set --------------------------


async def test_the_deletion_set_excludes_a_slot_at_or_above_the_cutoff(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0149 §5: a slot at or above the removal's revision belongs to a later act.

    Deleting one would leave that act's activation standing over an empty slot,
    which is the mirror failure §5's revision cutoff closes.
    """
    first = await store.append(entry(), expected_latest=None)
    assert first is not None
    second = await store.append(entry(revision=2, key="slot-2"), expected_latest=first.sequence)
    assert second is not None
    await store.append(entry(revision=3, key="slot-3"), expected_latest=second.sequence)

    below = await store.slots_below("ref-1", 3)

    assert [name.key for name in below] == ["slot-1", "slot-2"]


async def test_the_purge_set_is_every_distinct_slot_deduplicated(
    store: SqliteConnectionStore,
) -> None:
    """ADR-0149 §8: the live records' slots and every superseded or removed one.

    Deduplicated, which is half of what makes the purge idempotent — an act writes
    its record twice under one slot, so a set built by counting rows would delete
    the same name twice.
    """
    first = await store.append(entry(), expected_latest=None)
    assert first is not None
    second = await store.append(
        entry(state=ProvisioningState.ACTIVE), expected_latest=first.sequence
    )
    assert second is not None
    await store.append(entry(revision=2, state=None), expected_latest=second.sequence)
    await store.append(entry(reference="ref-2", key="slot-9"), expected_latest=None)

    assert [name.key for name in await store.slots()] == ["slot-1", "slot-9"]


async def test_clearing_empties_the_entries_and_leaves_the_store_openable(
    tmp_path: Path,
) -> None:
    """ADR-0149 §8: the ``meta`` marker describes the file, not the user's history."""
    path = tmp_path / "connections.db"
    opened = SqliteConnectionStore(path=path)
    await opened.append(entry(), expected_latest=None)
    await opened.clear()
    opened.close()

    reopened = SqliteConnectionStore(path=path)
    try:
        assert await reopened.live() == ()
    finally:
        reopened.close()


# --- the entry's own shape --------------------------------------------------


def test_an_entry_is_a_provisioning_entry_or_a_removal_and_never_a_mixture() -> None:
    """ADR-0149 §5: a removal carries no identity, no state and no slot.

    An entry with a state but no slot would name a record no credential read could
    satisfy; one with a slot but no state would be a record ADR-0148 §6 has no
    state for.
    """
    with pytest.raises(ValueError, match="a provisioning entry"):
        ConnectionEntry(
            reference="ref-1",
            revision=1,
            identity="owner",
            state=ProvisioningState.ACTIVE,
            slot=None,
        )
