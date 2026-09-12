"""The durable ``ParkedReads`` on SQLite (ADR-0244 §3, §18's Lane 2).

The shared suite bound to the production store, plus the arms that are about a *file*
rather than about the contract: the schema marker, the objects held to their own
definitions, the owner-only mode, the constraints ADR-0244 §3's three store invariants
are stated to SQLite as, and the restart the whole decision turns on (§15).

**Why the file arms matter more here than at the sibling store.** ADR-0244 §3 rules that
"two engines over one data directory" can none of them be admitted against the same
conversation's park, and a lock in one process is no evidence at all about that sentence.
What the arms below hold is the *file*: a second handle over it, a hand-written ``UPDATE``
against it, a table of this name that is not this store's.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import stat
import threading
import time
from typing import TYPE_CHECKING, Any, Final

import pytest
from parked_reads_contract import AT, CONTENT, EXPIRES_AT, LATER, ParkedReadsContract, park

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import ParkedRead, ParkedReadDisposition
from ai_assistant.permissions.parked_reads import (
    _CREATE_TABLE,
    _INDEXES,
    _META_SCHEMA,
    _READ_SCHEMA_VERSION,
    _SETTLE_ONLY_V1,
    _WRITE_SCHEMA_VERSION,
    SqliteParkedReads,
    _sort_key,
)
from ai_assistant.testing.cancellation import ThreadSuspension

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence
    from pathlib import Path


class TestSqliteParkedReadsContract(ParkedReadsContract):
    """The durable store against every clause of ADR-0244 §3."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> SqliteParkedReads:
        return SqliteParkedReads(path=tmp_path / "parked_reads.db")


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "parked_reads.db"


#: What :data:`~ai_assistant.permissions.parked_reads._SETTLE_ONLY` says when it aborts.
#: One phrase for every limb, because it is one trigger: which limb fired is what each case
#: name says, and a per-limb ``match`` would be asserting the message rather than the rule.
_TRIGGER: Final = "mutated only by settling an open park"


# --- the file (ADR-0004 §2, §4) ----------------------------------------------


def test_the_database_file_is_owner_only(path: Path) -> None:
    """ADR-0004 §4, and restricted before the first statement.

    SQLite copies the database file's mode onto every rollback journal it creates for it,
    so a journal opened while the file still carried the process umask would be
    world-readable — and an interrupted write leaves it on disk holding the Tier 1 pages
    a park's ``parameters``, ``goal`` and ``plan`` are (#489).
    """
    SqliteParkedReads(path=path).close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_path_whose_parent_does_not_exist_is_this_layers_error(tmp_path: Path) -> None:
    """A bad path is reported by this layer rather than as a raw driver complaint."""
    with pytest.raises(AssistantError, match="failed to open"):
        SqliteParkedReads(path=tmp_path / "absent" / "parked_reads.db")


def test_an_unlabelled_database_is_stamped_rather_than_migrated(path: Path) -> None:
    """An unlabelled file is one this open is creating, so it is stamped at the current
    version rather than upgraded from a shape it never had."""
    SqliteParkedReads(path=path).close()

    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone() == (
            "2",
        )


def test_a_database_labelled_with_a_schema_this_code_cannot_read_is_refused(path: Path) -> None:
    """Refused rather than read blindly: rows under an unknown shape cannot be trusted to
    say what the user was asked, or whether they answered.

    **A version this code can *upgrade* is a different case** and is admitted — see
    :func:`test_a_version_1_database_is_upgraded_and_its_legacy_park_stays_answerable`.
    What is refused is a version it can neither read nor reach, which after ADR-0248 §9
    means anything outside ``{1, 2}``.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '3')")

    with pytest.raises(AssistantError, match="schema_version=3"):
        SqliteParkedReads(path=path)


def test_a_refused_open_leaves_the_file_unlabelled(path: Path) -> None:
    """The object check runs inside the setup transaction and **before** the marker.

    So a refusal leaves the file exactly as it arrived: not carrying this store's marker
    over a shape that is not this store's, which a later release would then read as one it
    had itself created.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE parked_reads(id TEXT, data TEXT)")

    with pytest.raises(AssistantError, match="is not the one this store defines"):
        SqliteParkedReads(path=path)

    with sqlite3.connect(path) as conn:
        held = conn.execute("SELECT name FROM sqlite_master WHERE name = 'meta'").fetchall()
    assert held == [], "a refused open wrote nothing, the meta table included"


def test_a_file_holding_a_table_of_this_name_that_is_not_this_store_is_refused(
    path: Path,
) -> None:
    """``CREATE TABLE IF NOT EXISTS`` is a no-op against a table already there under that
    name **whatever shape it has**.

    All four generated projections would then read as ``NULL`` for every row — the insert
    writes only ``parked_at_us`` and ``data`` — so no park would answer as open or as
    terminal, both uniqueness constraints would constrain nothing, and one conversation
    could hold as many standing questions as it liked. That is the exact failure the
    generated columns exist to make impossible, walked around rather than through.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE parked_reads(id TEXT, data TEXT, disposition TEXT)")

    with pytest.raises(AssistantError, match="is not the one this store defines"):
        SqliteParkedReads(path=path)


@pytest.mark.parametrize(
    "object_name",
    ["parked_reads_id", "parked_reads_decision", "parked_reads_one_open", "parked_reads_order"],
)
def test_a_file_whose_index_is_not_this_stores_is_refused(path: Path, object_name: str) -> None:
    """Each index is held to its own definition, not merely to its name.

    The partial index is the one that matters most: an index over ``conversation_id``
    **without** the ``WHERE disposition = 'open'`` clause would refuse a conversation's
    *second* park forever, and one over the wrong column would admit two open ones — and
    both are files a hand-built database can arrive as.
    """
    SqliteParkedReads(path=path).close()
    with sqlite3.connect(path) as conn:
        conn.execute(f"DROP INDEX {object_name}")
        conn.execute(f"CREATE INDEX {object_name} ON parked_reads(parked_at_us)")

    with pytest.raises(AssistantError, match="is not the one this store defines"):
        SqliteParkedReads(path=path)


def test_a_file_whose_settle_trigger_is_not_this_stores_is_refused(path: Path) -> None:
    """The trigger is held to its own definition like the indexes are.

    It is what ADR-0244 §2's "no transition leaves a terminal member" is stated to the
    database as, so a file carrying a *weaker* trigger of this name is one whose rows could
    have been re-opened, re-answered or stripped of a terminal fact by anything holding the
    connection — and ``CREATE TRIGGER IF NOT EXISTS`` would leave it exactly as it found it.

    A trigger that is merely **absent** is a different case and is deliberately not a
    refusal: the setup creates it, exactly as it creates the table and the indexes on a
    first open.
    """
    SqliteParkedReads(path=path).close()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER parked_reads_settle_only")
        conn.execute(
            "CREATE TRIGGER parked_reads_settle_only BEFORE UPDATE ON parked_reads "
            "WHEN 0 BEGIN SELECT RAISE(ABORT, 'never'); END"
        )

    with pytest.raises(AssistantError, match="is not the one this store defines"):
        SqliteParkedReads(path=path)


# --- ADR-0248 §9's schema upgrade, 1 → 2 --------------------------------------


def _version_1_database(path: Path, *, parks: Sequence[ParkedRead] = ()) -> None:
    """Build the database this store shipped **before** ADR-0248, and seed it.

    The whole point of §10's upgrade arm is that "a fresh database seeded with legacy JSON
    cannot stand in for it, because it is the **stored trigger definition** and not the row
    that the object check refuses" — so this writes version 1's own table, indexes,
    settlement trigger and marker, and never opens the current store to make them.

    A seeded park is written **without an** ``utterance`` **key at all**, which is what a
    row written by that release holds: the field did not exist, so it is absent rather than
    present-and-null, and a decode that leaned on an explicit ``null`` would pass here
    while failing on a real file.
    """
    with sqlite3.connect(path) as conn:
        conn.execute(_META_SCHEMA)
        conn.execute(_WRITE_SCHEMA_VERSION, ("1",))
        conn.execute(_CREATE_TABLE)
        for statement in _INDEXES.values():
            conn.execute(statement)
        conn.execute(_SETTLE_ONLY_V1)
        for record in parks:
            legacy = json.loads(record.model_dump_json())
            del legacy["utterance"]
            conn.execute(
                "INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)",
                (_sort_key(record.parked_at), json.dumps(legacy)),
            )


async def test_a_version_1_database_is_upgraded_and_its_legacy_park_stays_answerable(
    path: Path,
) -> None:
    """ADR-0248 §9's upgrade, end to end, and §10's arm for it.

    A database labelled 1 is **upgraded rather than refused**, which is the one shape this
    store's version check did not admit before. Its legacy park decodes with ``utterance``
    ``None`` (§7), is still enumerated and is still answerable (ADR-0244 §15) — and a park
    written *after* the upgrade settles through the new trigger, clearing four fields.
    """
    _version_1_database(path, parks=[park(utterance=None)])

    store = SqliteParkedReads(path=path)
    try:
        held = await store.get("park-1")
        assert held is not None
        assert held.utterance is None, "a park older than the field, decoded rather than repaired"
        assert held.disposition is ParkedReadDisposition.OPEN
        assert [one.id for one in await store.outstanding()] == ["park-1"]

        assert await store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER), (
            "the question the user was asked is still answerable"
        )

        after = park(park_id="park-2", conversation_id="conv-2", decision_id="decision-2")
        assert await store.park(after) is True
        assert await store.settle("park-2", disposition=ParkedReadDisposition.DENIED, at=LATER)
        settled = await store.get("park-2")
        assert settled is not None
        assert all(getattr(settled, field) is None for field in CONTENT), (
            "the upgraded trigger admits the settlement that clears all four"
        )
    finally:
        store.close()

    with sqlite3.connect(path) as conn:
        assert conn.execute(_READ_SCHEMA_VERSION).fetchone() == ("2",)


async def test_the_upgrade_rewrites_no_row_and_reads_no_park(path: Path) -> None:
    """ADR-0248 §9: "the upgrade touches definitions and a marker, and no content".

    The blob is compared byte for byte across the open, which is the assertion that no
    back-fill, re-derivation, re-validation or re-serialisation happened to it — and the
    park's own state is unmoved: ``OPEN`` before, ``OPEN`` after, same deadline.
    """
    _version_1_database(path, parks=[park(utterance=None)])
    with sqlite3.connect(path) as conn:
        (before,) = conn.execute("SELECT data FROM parked_reads").fetchone()

    SqliteParkedReads(path=path).close()

    with sqlite3.connect(path) as conn:
        (after,) = conn.execute("SELECT data FROM parked_reads").fetchone()
    assert after == before
    assert "utterance" not in json.loads(after)


def test_a_version_1_database_whose_trigger_is_neither_definition_is_still_refused(
    path: Path,
) -> None:
    """ADR-0248 §9: "where it is anything else the existing refusal stands, word for word".

    The marker says a shape this code can upgrade; the stored trigger says a file that is
    not this store's. The upgrade recognises only version 1's own definition, so it drops
    nothing, ``CREATE TRIGGER IF NOT EXISTS`` leaves what is there, and the object check
    refuses with the message it refuses with today.
    """
    _version_1_database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TRIGGER parked_reads_settle_only")
        conn.execute(
            "CREATE TRIGGER parked_reads_settle_only BEFORE UPDATE ON parked_reads "
            "WHEN 0 BEGIN SELECT RAISE(ABORT, 'never'); END"
        )

    with pytest.raises(AssistantError, match="is not the one this store defines"):
        SqliteParkedReads(path=path)

    with sqlite3.connect(path) as conn:
        assert conn.execute(_READ_SCHEMA_VERSION).fetchone() == ("1",), (
            "a refused open leaves the marker where it was — the upgrade and the check "
            "are one transaction, so the file is unupgraded rather than half-migrated"
        )


def test_a_current_database_is_opened_twice_without_a_second_upgrade(path: Path) -> None:
    """The idempotence half: an upgrade that ran once does not run again.

    Version 2's trigger is not version 1's, so :meth:`_upgrade_settle_trigger` is not even
    reached — the marker already reads 2. Asserted because an upgrade keyed on the trigger
    alone rather than on the marker would drop and recreate on every open, which is a write
    to a file this decision promises to leave alone.
    """
    SqliteParkedReads(path=path).close()

    SqliteParkedReads(path=path).close()

    with sqlite3.connect(path) as conn:
        assert conn.execute(_READ_SCHEMA_VERSION).fetchone() == ("2",)


# --- the three invariants, said to SQLite (ADR-0244 §3) ----------------------


async def test_a_second_open_park_for_one_conversation_is_refused_by_the_database(
    path: Path,
) -> None:
    """ADR-0244 §3's one-open-park rule against a *hand-written* insert.

    The guarded read in ``park`` is what makes the refusal an **answer**; this is what
    makes the refused **state** unreachable, which is the half §3 states in terms — "so
    that an implementation cannot reach a state where two rows answer one decision id",
    and the same for two open parks over one conversation. A second engine over this file
    is exactly the writer this constrains.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    second = park(park_id="park-2", decision_id="decision-2").model_dump_json()
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)", (1, second))


async def test_a_second_park_naming_one_decision_is_refused_by_the_database(path: Path) -> None:
    """The other uniqueness constraint, from a *second* conversation so that the
    one-open-park index cannot be what refuses it.

    It is what makes ``park_of_decision`` a single answer rather than a listing.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    second = park(park_id="park-2", conversation_id="conv-2").model_dump_json()
    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)", (1, second))


@pytest.mark.parametrize(
    "disposition",
    ["denied", "open"],
    ids=["a terminal park moved again", "a spent question re-opened"],
)
async def test_the_table_admits_no_mutation_of_a_settled_park(path: Path, disposition: str) -> None:
    """ADR-0244 §2's "no transition leaves a terminal member", said to SQLite.

    A park that could be re-opened is a question the user already answered being asked
    again — and, worse, an ``APPROVED`` park moved back to ``OPEN`` is a second dispatch
    of a read whose one answer was already spent (§3's resolve-once gate).
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    await store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match=_TRIGGER):
        conn.execute(
            "UPDATE parked_reads SET data = json_set(data, '$.disposition', ?)", (disposition,)
        )


async def test_a_settlement_that_kept_the_content_is_refused_by_the_database(path: Path) -> None:
    """ADR-0244 §3's retention rule, enforced rather than remembered.

    "The content lives exactly as long as the question does" is the whole of what this
    decision states about retention, and a settlement that moved the disposition while
    leaving the query behind would breach it in the one place a reader would not look.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match=_TRIGGER):
        conn.execute("UPDATE parked_reads SET data = json_set(data, '$.disposition', 'denied')")


#: The blob of a well-formed settlement: **every** content field cleared — ADR-0248 §3's
#: ``utterance`` included, which is the fourth — and the disposition moved to a terminal
#: member. Built from :data:`CONTENT` so the list the suite settles by hand and the list
#: the store clears cannot come apart; a hand-typed copy is exactly the place a fifth
#: field would be forgotten and the trigger's new limb would go untested.
_SETTLED_BLOB: Final = (
    "json_set("
    + "json_set(" * len(CONTENT)
    + "data"
    + "".join(f", '$.{field}', NULL)" for field in CONTENT)
    + ", '$.disposition', 'denied')"
)

#: A well-formed settlement of the suite's park, which the trigger admits. Each case below
#: rewrites exactly one further field on top of it, so what the trigger refuses is that
#: field and never the settlement it rides on — a case built the other way round would
#: pass against a trigger with no terminal-fact limb at all.
_SETTLE_BY_HAND: Final = f"UPDATE parked_reads SET data = {_SETTLED_BLOB}"  # noqa: S608 — the interpolated part is this module's own constant, built from CONTENT

#: The same settlement with one further field forged on top of it, bound as a parameter.
_FORGE_A_TERMINAL_FACT: Final = (
    # The interpolated part is this module's own constant; the forged field and its
    # value are bound parameters.
    f"UPDATE parked_reads SET data = json_set({_SETTLED_BLOB}, ?, ?)"  # noqa: S608
)


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("$.decision_id", "forged-decision"),
        ("$.conversation_id", "forged-conversation"),
        ("$.expires_at", "2030-01-01T00:00:00Z"),
        ("$.parked_at", "2030-01-01T00:00:00Z"),
        ("$.id", "forged-park"),
    ],
)
async def test_a_settlement_may_not_rewrite_a_terminal_fact(
    path: Path, field: str, forged: str
) -> None:
    """The facts a settled park keeps are frozen across the one mutation admitted.

    A settlement that could move ``decision_id`` would let ADR-0244 §5's eighth condition
    exclude the wrong decision from ``grantable_decisions``; one that could move
    ``expires_at`` would move a deadline the user was shown.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match=_TRIGGER):
        conn.execute(_FORGE_A_TERMINAL_FACT, (field, forged))


async def test_the_ordering_key_cannot_be_rewritten(path: Path) -> None:
    """The trigger's last limb, and it guards a *listing* rather than a value.

    ``outstanding`` is contractually in ``parked_at`` order, and a row whose stored key was
    altered to sort late would be enumerated in the wrong place with every field on it
    valid — so ADR-0244 §5's enumeration would offer the user an older question after a
    newer one.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    with sqlite3.connect(path) as conn, pytest.raises(sqlite3.IntegrityError, match=_TRIGGER):
        conn.execute("UPDATE parked_reads SET parked_at_us = 0")


async def test_a_well_formed_settlement_is_admitted_by_the_trigger(path: Path) -> None:
    """The anti-vacuity half of every case above, and it is not optional.

    A trigger that aborted *every* ``UPDATE`` would pass all of them and leave this store
    unable to settle a park at all — so the settlement the trigger exists to admit is run
    here through the same hand-written statement the refusals use, and lands.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    with sqlite3.connect(path) as conn:
        conn.execute(_SETTLE_BY_HAND)

    reopened = SqliteParkedReads(path=path)
    try:
        held = await reopened.get("park-1")
        assert held is not None
        assert held.disposition is ParkedReadDisposition.DENIED
        assert held.parameters is None
    finally:
        reopened.close()


# --- restart survival (ADR-0244 §15) -----------------------------------------


async def test_a_park_and_its_settlement_both_survive_a_restart(path: Path) -> None:
    """ADR-0244 §15, which is the whole reason this implementation exists.

    A token minted before a restart must find its park after one, and §19's Arm 14 —
    "the exclusion survives a restart" — fails an implementation holding the terminal row
    in memory. Both directions are asserted over a **second handle**, because "it survived"
    is a claim about the file rather than about the object.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    reopened = SqliteParkedReads(path=path)
    try:
        held = await reopened.get("park-1")
        assert held is not None
        assert held.parameters == {"origin": "search.example", "query": "bell tower porto"}
        assert held.goal is not None, "the parked turn's objective is durable"
        assert held.plan is not None, "and the plan §8 composes over"
        assert held.expires_at == EXPIRES_AT
        assert [outstanding.id for outstanding in await reopened.outstanding()] == ["park-1"]
        assert await reopened.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER)
    finally:
        reopened.close()

    again = SqliteParkedReads(path=path)
    try:
        terminal = await again.park_of_decision("decision-1")
        assert terminal is not None
        assert terminal.disposition is ParkedReadDisposition.DENIED
        assert terminal.parameters is None, "the content went with the question"
        assert await again.outstanding() == ()
    finally:
        again.close()


async def test_two_handles_over_one_file_admit_exactly_one_park(path: Path) -> None:
    """ADR-0244 §3's "two engines over one data directory", as literally as a test can.

    Two ``SqliteParkedReads`` over one file are two connections with two ``asyncio``
    locks, so nothing in this process serialises them — what refuses the second park is
    ``BEGIN IMMEDIATE`` and the partial unique index, which is the half of §3 that a
    single-object case cannot reach.
    """
    first = SqliteParkedReads(path=path)
    second = SqliteParkedReads(path=path)
    try:
        assert await first.park(park()) is True
        assert await second.park(park(park_id="park-2", decision_id="decision-2")) is False
        assert await second.get("park-2") is None
        settled = await second.settle(
            "park-1", disposition=ParkedReadDisposition.CANCELLED, at=LATER
        )
        assert settled is True, "either engine can take the park's one answer"
        lost = await first.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
        assert lost is False, "the park's one answer was already spent"
    finally:
        first.close()
        second.close()


# --- the store's own refusals ------------------------------------------------


async def test_a_second_write_under_one_park_id_is_a_fault_rather_than_an_answer(
    path: Path,
) -> None:
    """The id check raises where the other two refusals answer, and the split is §3's own.

    A conversation that already holds an open park, and a decision a park already names,
    are states an ordinary turn reaches and ADR-0244 §1's third clause is written over the
    ``False`` they produce. A duplicate *id* is not: ids are minted once each, so a second
    write under one is a caller replaying a write into a write-once store.
    """
    store = SqliteParkedReads(path=path)
    try:
        await store.park(park())
        with pytest.raises(AssistantError, match="already recorded"):
            await store.park(park(conversation_id="conv-2", decision_id="decision-2"))
    finally:
        store.close()


async def test_a_terminal_park_may_not_be_written_directly(path: Path) -> None:
    """A terminal park is reached by settlement and never by a write (ADR-0244 §2, §3).

    Admitting one would let a caller record an answer nobody gave, and the store would hold
    a ``DENIED`` row excluding a decision from ``grantable_decisions`` on the strength of a
    question that was never asked.
    """
    store = SqliteParkedReads(path=path)
    try:
        terminal = ParkedRead(
            id="park-1",
            conversation_id="conv-1",
            decision_id="decision-1",
            parameters=None,
            goal=None,
            plan=None,
            parked_at=AT,
            expires_at=EXPIRES_AT,
            disposition=ParkedReadDisposition.DENIED,
        )
        with pytest.raises(AssistantError, match="written OPEN"):
            await store.park(terminal)
        assert await store.get("park-1") is None
    finally:
        store.close()


async def test_a_row_that_no_longer_validates_is_a_fault_rather_than_an_absent_park(
    path: Path,
) -> None:
    """A corrupt row is reported, not skipped.

    Skipping it would let an **answered** park read as unasked — which is the one state
    ADR-0244 §5's eighth condition and §6's gate are both stated to make unreachable.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()
    # The row keeps every field the four projections are derived from, so each read below
    # genuinely *matches* it and the case is about the decode rather than about a miss.
    # What it loses is ``expires_at``, which ADR-0244 §2 makes required with no default.
    broken = {
        key: value
        for key, value in json.loads(park().model_dump_json()).items()
        if key != "expires_at"
    }
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM parked_reads")
        conn.execute(
            "INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)",
            (0, json.dumps(broken)),
        )

    reopened = SqliteParkedReads(path=path)
    reads: tuple[Callable[[], Coroutine[Any, Any, object]], ...] = (
        lambda: reopened.get("park-1"),
        lambda: reopened.open_park("conv-1"),
        lambda: reopened.park_of_decision("decision-1"),
        reopened.outstanding,
    )
    try:
        for read in reads:
            with pytest.raises(AssistantError, match="no longer validates"):
                await read()
    finally:
        reopened.close()


async def test_a_refusal_names_no_field_of_the_row_it_refuses(path: Path) -> None:
    """ADR-0004 §5, at the one diagnostic in this store that could breach it.

    ADR-0244 §2's validator fires on exactly the three Tier 1 content fields, so a pydantic
    message rendered whole is where the user's own query would leave this process. What an
    operator needs is the store and the count, and that is all this says.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM parked_reads")
        conn.execute(
            "INSERT INTO parked_reads(parked_at_us, data) VALUES (?, ?)",
            (
                0,
                json.dumps(
                    {
                        **json.loads(park().model_dump_json()),
                        "disposition": "denied",
                    }
                ),
            ),
        )

    reopened = SqliteParkedReads(path=path)
    try:
        with pytest.raises(AssistantError) as refusal:
            await reopened.get("park-1")
    finally:
        reopened.close()
    assert "bell tower porto" not in str(refusal.value)
    assert "porto" not in str(refusal.value).lower()


async def test_an_unreadable_store_raises_rather_than_answering_none(path: Path) -> None:
    """Every member here raises where the store is broken, and ``None`` means **no park**.

    The ``ParkedReads`` contract has no fail-closed answer of ``DestinationTrustStore``'s
    kind: a ``None`` from ``open_park`` is what admits a search, and a store that turned a
    fault into one would admit a park against a conversation that already holds a standing
    question.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    store.close()

    with pytest.raises(AssistantError):
        await store.open_park("conv-1")
    with pytest.raises(AssistantError):
        await store.park(park(park_id="park-2", conversation_id="conv-2", decision_id="d-2"))


# --- ADR-0060 §3: the resource outlives the cancelled coroutine ---------------


#: Every ``async with self._lock`` site this store has, and the private sync method a
#: worker runs inside it. ADR-0060 §3 binds *any* method that acquires the resource rather
#: than any method that mutates, so the reads are here beside the writes — and ``get``,
#: ``open_park`` and ``park_of_decision`` genuinely share ``_one_sync``, which is why
#: parking it holds all three.
_SYNC_SEAMS: Final = {
    "park": "_park_sync",
    "settle": "_settle_sync",
    "drop_for_conversation": "_drop_sync",
    "get": "_one_sync",
    "outstanding": "_outstanding_sync",
}

#: How long the case waits for the second worker to *fail* to start. Only ever spent in
#: full on a passing run, so it is short; a conforming store never sets the event at all
#: and a breached one sets it in microseconds.
_ENTRY_SECONDS: Final = 0.25


def _call(store: SqliteParkedReads, operation: str) -> Coroutine[Any, Any, object]:
    """One call of ``operation`` against ``store``, ready to be scheduled."""
    if operation == "park":
        return store.park(park(park_id="park-2", conversation_id="conv-2", decision_id="d-2"))
    if operation == "settle":
        return store.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
    if operation == "drop_for_conversation":
        return store.drop_for_conversation("conv-nobody-used")
    if operation == "get":
        return store.get("park-1")
    return store.outstanding()


@pytest.mark.parametrize("operation", sorted(_SYNC_SEAMS))
async def test_a_cancelled_call_holds_the_connection_until_its_worker_finishes(
    path: Path, operation: str
) -> None:
    """ADR-0060 §3's clause, at **every** lock site and not only the write path.

    ``_run_to_completion`` absorbs the cancellation and keeps waiting on the worker's
    physical completion signal, so ``async with self._lock`` is held for the whole life of
    the thread. Without that, the cancellation unwinds the ``async with`` **while the
    worker is still using the connection**, and a second caller then uses the same
    ``sqlite3`` connection concurrently — which SQLite refuses, and which no assertion
    about this store's answers would catch.

    **What is observed is the second worker's *entry*, and nothing weaker.** Asserting
    that the second call is not ``done()`` proves nothing: it has an executor round trip
    ahead of it either way. What discriminates is whether its sync method **began** while
    the cancelled worker was still parked, so the observer is always a *different* seam
    from the parked one and the case waits for an entry a conforming store never makes.
    """
    store = SqliteParkedReads(path=path)
    await store.park(park())
    suspension = ThreadSuspension()
    parked_attribute = _SYNC_SEAMS[operation]
    parked_seam = getattr(store, parked_attribute)
    armed = threading.Event()

    def blocking(*args: object) -> object:
        if not armed.is_set():  # the first worker only; later ones run free
            armed.set()
            suspension.hold()
        return parked_seam(*args)

    watched_attribute = (
        "_one_sync" if parked_attribute == "_outstanding_sync" else "_outstanding_sync"
    )
    observed = getattr(store, watched_attribute)
    entered = threading.Event()

    def watching(*args: object) -> object:
        entered.set()
        return observed(*args)

    setattr(store, parked_attribute, blocking)
    setattr(store, watched_attribute, watching)
    try:
        first = asyncio.ensure_future(_call(store, operation))
        await suspension.reached()
        first.cancel()
        second = asyncio.ensure_future(
            store.get("park-1") if watched_attribute == "_one_sync" else store.outstanding()
        )

        # Waited *off* the loop, so the executor genuinely gets its chance: a store that
        # released the lock early submits the second worker at once and this returns true
        # within microseconds.
        assert not await asyncio.to_thread(entered.wait, _ENTRY_SECONDS), (
            f"a second worker entered the connection while {operation}'s cancelled worker "
            f"was still inside it (ADR-0060 §3, ADR-0054)"
        )

        suspension.release()

        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert entered.is_set(), "the second call ran once the first worker finished"
    finally:
        suspension.release()
        store.close()


async def test_a_cancelled_write_is_absorbed_and_its_work_still_lands(path: Path) -> None:
    """The other half of the same clause: the *caller's* task cancels, the work does not.

    ``_run_to_completion`` re-raises the cancellation once the thread has finished, so the
    awaiting task still cancels — what is prevented is connection reuse, not the write.
    Asserted over a reopened store, because "the worker ran to completion" is a claim about
    the file rather than about the object.
    """
    store = SqliteParkedReads(path=path)
    suspension = ThreadSuspension()
    original = store._park_sync
    armed = threading.Event()

    def blocking(snapshot: ParkedRead) -> bool:
        if not armed.is_set():  # the first worker only; later ones run free
            armed.set()
            suspension.hold()
        return original(snapshot)

    store._park_sync = blocking  # type: ignore[method-assign]
    try:
        first = asyncio.ensure_future(store.park(park()))
        await suspension.reached()
        first.cancel()
        second = asyncio.ensure_future(
            store.park(park(park_id="park-2", conversation_id="conv-2", decision_id="decision-2"))
        )
        await asyncio.sleep(0)

        # The second call has not started: the cancelled one still holds the lock, because
        # its worker has not physically finished.
        assert not second.done()
        suspension.release()

        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second is True
    finally:
        suspension.release()
        store.close()

    reopened = SqliteParkedReads(path=path)
    try:
        # Both parks reached the file: the cancelled one's worker ran to completion, which
        # is what "the cancellation is absorbed and the work finishes" means.
        assert {held.id for held in await reopened.outstanding()} == {"park-1", "park-2"}
    finally:
        reopened.close()


# --- the retention rule, held against the file (ADR-0244 §3) -----------------


#: A query no other byte of this file or of SQLite's own pages could be. Long enough, in
#: the second case, that SQLite spills the row onto **overflow** pages rather than
#: keeping it inside the leaf — which is a second place freed content can be left behind
#: and is why the parametrisation is not decoration.
_NEEDLE: Final = b"heliotrope-belfry-quintessence"

_SIZES: Final = {"one leaf page": 1, "several overflow pages": 800}


def _asked(repeats: int) -> ParkedRead:
    """An open park whose composed query is :data:`_NEEDLE` ``repeats`` times over."""
    return park(
        parameters={
            "origin": "search.example",
            "query": _NEEDLE.decode() * repeats,
        }
    )


@pytest.mark.parametrize("repeats", list(_SIZES.values()), ids=list(_SIZES))
async def test_a_settlement_leaves_no_trace_of_the_query_in_the_file(
    path: Path, repeats: int
) -> None:
    """ADR-0244 §3's retention rule is about the **content**, not about the row.

    "``parameters``, ``goal`` and ``plan`` do not [survive], and **no implementation
    retains a copy, a digest of the query, a snapshot or an archive of them**. The
    content lives exactly as long as the question does." A settlement that nulled three
    columns and left their old bytes in the page SQLite marks free would satisfy every
    assertion the shared suite can make — it reads decoded rows — while the whole
    composed query stayed recoverable by reading the file, which is the one thing this
    rule is stated to make untrue.

    The first assertion is the anti-vacuity half: the bytes are genuinely there while the
    question stands, so their absence afterwards is the settlement's doing and not the
    needle's.
    """
    store = SqliteParkedReads(path=path)
    await store.park(_asked(repeats))
    store.close()
    assert _NEEDLE in path.read_bytes(), (  # noqa: ASYNC240 — a read of a temporary file this case owns, not an I/O path the loop can be starved by
        "the question is on disk while it stands"
    )

    reopened = SqliteParkedReads(path=path)
    await reopened.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
    reopened.close()

    assert _NEEDLE not in path.read_bytes()  # noqa: ASYNC240 — a synchronous read of a temporary file this case owns, not an I/O path the event loop can be starved by


@pytest.mark.parametrize("repeats", list(_SIZES.values()), ids=list(_SIZES))
async def test_a_conversations_deletion_leaves_no_trace_of_the_query_in_the_file(
    path: Path, repeats: int
) -> None:
    """The same rule at the other destructive member (ADR-0244 §3, ADR-0004 §6).

    ``drop_for_conversation`` is the conversation deletion sequence's route, so a user
    who asked for a conversation to be destroyed and was told it was is the person this
    assertion is about. A ``DELETE`` that merely unlinked the row would leave the query
    they had been asked about sitting in the file.
    """
    store = SqliteParkedReads(path=path)
    await store.park(_asked(repeats))
    store.close()
    assert _NEEDLE in path.read_bytes()  # noqa: ASYNC240 — a synchronous read of a temporary file this case owns, not an I/O path the event loop can be starved by

    reopened = SqliteParkedReads(path=path)
    assert await reopened.drop_for_conversation("conv-1") == 1
    reopened.close()

    assert _NEEDLE not in path.read_bytes()  # noqa: ASYNC240 — a synchronous read of a temporary file this case owns, not an I/O path the event loop can be starved by


async def test_the_store_asks_sqlite_to_overwrite_what_it_frees(path: Path) -> None:
    """The pragma itself, asserted where a lane could quietly drop it.

    The two cases above would keep passing on a build whose ``SQLITE_SECURE_DELETE`` is
    compiled **on** by default, so they are not on their own evidence that this store
    asks for it. This is: the connection says so, whatever the build's default.
    """
    store = SqliteParkedReads(path=path)
    try:
        assert store._conn.execute("PRAGMA secure_delete").fetchone() == (1,)
    finally:
        store.close()


# --- two connections genuinely contending (ADR-0244 §3) ----------------------


#: How long the contended cases hold the write lock while both calls are in flight. Long
#: enough that a store reaching SQLite would have finished, short enough to sit well
#: inside the driver's five-second busy timeout — so a conforming store waits rather than
#: raising, which is what the cases assert.
_CONTENTION_SECONDS: Final = 0.25


async def test_two_contending_connections_admit_exactly_one_park(path: Path) -> None:
    """ADR-0244 §3's "two engines over one data directory", with the two genuinely overlapping.

    ``test_two_handles_over_one_file_admit_exactly_one_park`` awaits each call before the
    next begins, so it says only that a second connection *sees* a committed park —
    which a deferred ``BEGIN`` would satisfy too. The property §3 actually states is
    about the read the write depends on, and it is only reachable with both calls in
    flight: two connections that each read no open park and then each inserted would
    leave the user holding two questions where the store promised one.

    **The overlap is arranged rather than hoped for.** A third, plain connection takes
    the write lock first; both calls are launched against it and are asserted to be
    *stuck* — which is what proves they are contending rather than passing one after the
    other — and the lock is released only then. What a conforming store does from there
    is wait out the contention and answer: exactly one ``True``, one ``False``, and
    **no raise**, because ADR-0244 §1's third clause is written over that answer.
    """
    first = SqliteParkedReads(path=path)
    second = SqliteParkedReads(path=path)
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        calls = [
            asyncio.ensure_future(first.park(park())),
            asyncio.ensure_future(second.park(park(park_id="park-2", decision_id="decision-2"))),
        ]
        # Waited *off* the loop, so both workers genuinely reach SQLite and stall there.
        await asyncio.to_thread(time.sleep, _CONTENTION_SECONDS)
        assert not any(call.done() for call in calls), (
            "neither call may complete while another connection holds the write lock"
        )

        blocker.rollback()
        outcomes = await asyncio.gather(*calls)

        assert sum(1 for outcome in outcomes if outcome) == 1
        held = [row for row in (await first.get("park-1"), await first.get("park-2")) if row]
        assert len(held) == 1
    finally:
        blocker.close()
        first.close()
        second.close()


async def test_two_contending_connections_settle_one_park_exactly_once(path: Path) -> None:
    """The resolve-once gate across two connections, arranged the same way.

    ADR-0244 §19's Arm 9 second clause is one of the three "this decision would be
    worthless without", and the shared suite reaches it only within one object — where
    an :class:`asyncio.Lock` is doing the work. Here the two callers share no lock at
    all, so what answers ``True`` to exactly one of them is the guarded ``UPDATE`` under
    ``BEGIN IMMEDIATE``, and the loser "dispatches nothing, sends nothing and reports the
    settled state" rather than raising.
    """
    first = SqliteParkedReads(path=path)
    second = SqliteParkedReads(path=path)
    await first.park(park())
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        calls = [
            asyncio.ensure_future(
                first.settle("park-1", disposition=ParkedReadDisposition.APPROVED, at=LATER)
            ),
            asyncio.ensure_future(
                second.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=LATER)
            ),
        ]
        await asyncio.to_thread(time.sleep, _CONTENTION_SECONDS)
        assert not any(call.done() for call in calls)

        blocker.rollback()
        outcomes = await asyncio.gather(*calls)

        assert sum(1 for outcome in outcomes if outcome) == 1
        held = await second.get("park-1")
        assert held is not None
        assert held.disposition in {
            ParkedReadDisposition.APPROVED,
            ParkedReadDisposition.DENIED,
        }
        assert all(getattr(held, field) is None for field in ("parameters", "goal", "plan"))
    finally:
        blocker.close()
        first.close()
        second.close()
