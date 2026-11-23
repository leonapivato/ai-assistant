"""SqliteIdentityStore: the shared conformance suite, plus what only it owes.

The suite holds the contract (ADR-0366 §2, §3, §5:5); this module holds what belongs to
a *persistent* store: that the file is owner-only (ADR-0004 §4); that the owner's
identity is written when the store is first created, and the configured accounts linked
on every open, so an account configured later is linked on the next start and one no
longer configured stays linked (#3642, §3:2); that what it wrote survives a reopen; that
a file of another schema is refused before anything is written (ADR-0326 §5:3); that a
broken backend or a corrupt row surfaces as the seam's own error; that two handles on
one file share one store; that §5:5's rules naming a second identity hold on disk; and
that a cancelled call keeps the connection until its worker is done (ADR-0054).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from datetime import datetime
from typing import TYPE_CHECKING

import pytest
from identity_store_contract import (
    BY_THE_OWNER,
    LAPTOP,
    LINE,
    PHONE,
    START,
    IdentityStoreContract,
    IdentityStoreFactory,
    IdentityStoreReopener,
    ticking,
    written_id,
)

from ai_assistant.core.errors import IdentityStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    Account,
    LinkAct,
    LinkActHow,
    LinkRefusal,
    LinkWrite,
    LinkWriteKind,
    Sureness,
)
from ai_assistant.memory import SqliteIdentityStore
from ai_assistant.memory.identity_store import IDENTITY_SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import IdentityStore

pytestmark = pytest.mark.anyio

#: A second identity, which only a later decision adds; written here by hand to reach
#: §5:5's rules on disk.
SAM = "person:sam"
SAMS_PHONE = Account(kind="conversation", identifier="sams-phone.tailnet.example")


class TestSqliteIdentityStoreContract(IdentityStoreContract):
    """Runs SqliteIdentityStore through the shared IdentityStore suite."""

    @pytest.fixture
    def opened(self) -> Iterator[dict[SqliteIdentityStore, tuple[Path, Callable[[], datetime]]]]:
        held: dict[SqliteIdentityStore, tuple[Path, Callable[[], datetime]]] = {}
        yield held
        for store in held:
            store.close()

    @pytest.fixture
    def factory(
        self,
        tmp_path: Path,
        opened: dict[SqliteIdentityStore, tuple[Path, Callable[[], datetime]]],
    ) -> IdentityStoreFactory:
        def build(
            *, configured: Sequence[Account] = (), now: Callable[[], datetime] | None = None
        ) -> IdentityStore:
            path = tmp_path / f"identities-{len(opened)}.db"
            clock = now or ticking()
            store = SqliteIdentityStore(path=path, configured=configured, now=clock)
            opened[store] = (path, clock)
            return store

        return build

    @pytest.fixture
    def reopen(
        self, opened: dict[SqliteIdentityStore, tuple[Path, Callable[[], datetime]]]
    ) -> IdentityStoreReopener:
        def again(store: IdentityStore, *, configured: Sequence[Account] = ()) -> IdentityStore:
            assert isinstance(store, SqliteIdentityStore)
            path, clock = opened[store]
            store.close()
            reopened = SqliteIdentityStore(path=path, configured=configured, now=clock)
            opened[reopened] = (path, clock)
            return reopened

        return again


def _open(
    path: Path | str,
    *,
    configured: Sequence[Account] | None = None,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[str], str] | None = None,
) -> SqliteIdentityStore:
    """The store at ``path``, on a ticking clock from ``START`` where none is named.

    With no ``configured``, the opening follows no configuration, as a tool reading the
    file would open it.
    """
    if new_id is None:
        return SqliteIdentityStore(path=path, configured=configured, now=now or ticking())
    return SqliteIdentityStore(
        path=path, configured=configured, now=now or ticking(), new_id=new_id
    )


def _sql(path: Path, *statements: str) -> None:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()


# --- the owner and the configured accounts (§2:5, #3642) --------------------------


async def test_a_configured_account_already_linked_keeps_its_link_and_lowerings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    first = _open(path)
    try:
        link_id = written_id(await first.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await first.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
        before = await first.export()
    finally:
        first.close()

    again = _open(path, configured=(LINE,))
    try:
        assert await again.export() == before
    finally:
        again.close()


async def test_an_opening_handed_no_configuration_follows_nothing(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    first = _open(path, configured=(PHONE, LINE))
    try:
        before = await first.export()
    finally:
        first.close()

    reading = _open(path)
    try:
        assert await reading.export() == before
    finally:
        reading.close()


async def test_the_owner_is_created_once_when_the_store_is_first_created(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    _open(path).close()

    later = _open(path, now=ticking())
    try:
        exported = await later.export()
    finally:
        later.close()

    assert [(one.id, one.created_at) for one in exported.identities] == [(OWNER_PERSON_ID, START)]


async def test_a_creation_whose_clock_reading_fails_leaves_no_store(tmp_path: Path) -> None:
    """The schema, the owner and the configured links are one step."""
    path = tmp_path / "identities.db"

    with pytest.raises(IdentityStoreError, match="clock"):
        _open(path, configured=(LINE,), now=lambda: datetime(2026, 11, 23, 9, 0))  # noqa: DTZ001 — the naive reading under test

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0


async def test_an_open_whose_clock_fails_while_linking_leaves_the_file_as_it_was(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    first = _open(path, configured=(PHONE,))
    try:
        before = await first.export()
    finally:
        first.close()

    with pytest.raises(IdentityStoreError, match="clock"):
        _open(path, configured=(PHONE, LINE), now=lambda: datetime(2026, 11, 23, 9, 0))  # noqa: DTZ001 — the naive reading under test

    again = _open(path)
    try:
        assert await again.export() == before
    finally:
        again.close()


def test_a_malformed_configured_account_is_refused_before_any_file(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"

    with pytest.raises(ValueError, match="configured account"):
        _open(path, configured=("424242",))  # type: ignore[arg-type]  # the malformed argument under test

    assert not path.exists()


# --- persistence -------------------------------------------------------------------


async def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    journal = tmp_path / "identities.db-journal"
    journal.write_bytes(b"")
    journal.chmod(0o644)

    store = _open(path, configured=(LINE,))
    try:
        written_id(await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with contextlib.suppress(FileNotFoundError):
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600


async def test_everything_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    first = _open(path, configured=(PHONE,))
    try:
        link_id = written_id(await first.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        withdrawn = written_id(await first.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
        written_id(await first.withdraw_lowering(withdrawn, by=OWNER_PERSON_ID))
        written_id(await first.lower(link_id, Sureness.WEAK, by=OWNER_PERSON_ID))
        before = await first.export()
    finally:
        first.close()

    again = _open(path, configured=(PHONE,))
    try:
        assert await again.export() == before
        # What the reopened store holds still decides.
        repeat = await again.withdraw_lowering(withdrawn, by=OWNER_PERSON_ID)
        assert repeat == LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=withdrawn)
    finally:
        again.close()


async def test_two_handles_on_one_file_share_one_store(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    one = _open(path)
    other = _open(path)
    try:
        first = await one.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)
        again = await other.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)
        lowering_id = written_id(
            await other.lower(written_id(first), Sureness.WEAK, by=OWNER_PERSON_ID)
        )

        assert first.kind is LinkWriteKind.WRITTEN
        assert again == LinkWrite(kind=LinkWriteKind.UNCHANGED, record_id=first.record_id)
        found = await one.find_link(PHONE)
        assert found is not None
        assert [lowering.id for lowering in found.lowerings] == [lowering_id]
    finally:
        one.close()
        other.close()


@pytest.mark.parametrize("version", [0, IDENTITY_SCHEMA_VERSION + 1, 7])
async def test_a_file_of_another_schema_is_refused_untouched(tmp_path: Path, version: int) -> None:
    path = tmp_path / "identities.db"
    _sql(path, "CREATE TABLE identities(id TEXT PRIMARY KEY)", f"PRAGMA user_version = {version}")

    with pytest.raises(IdentityStoreError, match=f"schema version {version}"):
        _open(path, configured=(LINE,))

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables == {"identities"}
        assert conn.execute("SELECT count(*) FROM identities").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


@pytest.mark.parametrize("version", [1, IDENTITY_SCHEMA_VERSION + 1, 7])
def test_a_labelled_file_with_no_tables_is_refused_untouched(tmp_path: Path, version: int) -> None:
    """ADR-0326 §5:3: a newer label is refused whether or not the file holds a table."""
    path = tmp_path / "identities.db"
    _sql(path, f"PRAGMA user_version = {version}")

    with pytest.raises(IdentityStoreError, match=f"schema version {version}"):
        _open(path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_a_new_store_writes_its_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "identities.db"
    _open(path).close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == IDENTITY_SCHEMA_VERSION == 1


def test_a_path_that_cannot_be_opened_is_the_seams_error(tmp_path: Path) -> None:
    with pytest.raises(IdentityStoreError):
        _open(str(tmp_path / "bad\0name.db"))
    with pytest.raises(IdentityStoreError):
        _open(tmp_path / "missing" / "identities.db")


async def test_a_closed_backend_is_the_seams_error() -> None:
    store = SqliteIdentityStore(path=":memory:")
    store.close()

    with pytest.raises(IdentityStoreError):
        await store.identity(OWNER_PERSON_ID)
    with pytest.raises(IdentityStoreError):
        await store.find_link(PHONE)
    with pytest.raises(IdentityStoreError):
        await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)
    with pytest.raises(IdentityStoreError):
        await store.export()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE identities SET created_at = 'not-an-instant'",
        "INSERT INTO links(id, person_id, kind, account, act, made_at) VALUES "
        "('link:x', 'person:owner', 'telegram', '1', 'not json', '2026-11-23T09:00:00+00:00')",
        "INSERT INTO links(id, person_id, kind, account, act, made_at) VALUES "
        "('link:x', 'person:gone', 'telegram', '1', "
        '\'{"how": "device", "by": "person:owner"}\', \'2026-11-23T09:00:00+00:00\')',
        "INSERT INTO lowerings(id, link_id, level, made_by, made_at) VALUES "
        "('lowering:x', 'link:gone', 'none', 'person:owner', '2026-11-23T09:00:00+00:00')",
    ],
    ids=["identity-instant", "link-act", "link-of-no-identity", "lowering-of-no-link"],
)
async def test_a_corrupt_row_is_the_seams_error(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "identities.db"
    _open(path).close()
    _sql(path, statement)

    store = _open(path)
    try:
        with pytest.raises(IdentityStoreError, match="corrupt"):
            await store.export()
    finally:
        store.close()


@pytest.mark.parametrize(
    "level", ["'faint'", "'NORMAL'"], ids=["unknown-level", "a-level-in-other-case"]
)
async def test_a_lowering_row_of_no_level_is_the_seams_error(tmp_path: Path, level: str) -> None:
    path = tmp_path / "identities.db"
    store = _open(path)
    try:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
    finally:
        store.close()
    _sql(path, f"UPDATE lowerings SET level = {level}")  # noqa: S608 — the test's own constant

    again = _open(path)
    try:
        with pytest.raises(IdentityStoreError, match="corrupt"):
            await again.find_link(LINE)
        with pytest.raises(IdentityStoreError, match="corrupt"):
            await again.identity(OWNER_PERSON_ID)
    finally:
        again.close()


# --- §5:5's rules naming a second identity, on disk ---------------------------------


def _with_sam(path: Path) -> tuple[str, str]:
    """A file holding Sam beside the owner, each with one link: what a later lane adds."""
    _open(path).close()
    at = "2026-11-23T09:00:00+00:00"
    act = LinkAct(how=LinkActHow.DEVICE, by=SAM).model_dump_json()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT INTO identities(id, created_at) VALUES (?, ?)", (SAM, at))
        conn.execute(
            "INSERT INTO links(id, person_id, kind, account, act, made_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("link:sam", SAM, SAMS_PHONE.kind, SAMS_PHONE.identifier, act, at),
        )
        conn.commit()
    return "link:sam", SAM


async def test_the_person_a_link_identifies_may_lower_it_and_so_may_the_owner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    sams, sam = _with_sam(path)
    store = _open(path)
    try:
        assert (await store.lower(sams, Sureness.WEAK, by=sam)).kind is LinkWriteKind.WRITTEN
        by_owner = await store.lower(sams, Sureness.NONE, by=OWNER_PERSON_ID)
        assert by_owner.kind is LinkWriteKind.WRITTEN
    finally:
        store.close()


async def test_only_the_owner_or_the_links_person_lowers_and_only_the_maker_withdraws(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    sams, sam = _with_sam(path)
    store = _open(path)
    try:
        owners = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        sams_lowering = written_id(await store.lower(sams, Sureness.WEAK, by=sam))
        owners_lowering = written_id(await store.lower(sams, Sureness.NONE, by=OWNER_PERSON_ID))
        before = await store.export()

        lowering_the_owners = await store.lower(owners, Sureness.NONE, by=sam)
        owner_withdrawing_sams = await store.withdraw_lowering(sams_lowering, by=OWNER_PERSON_ID)
        sam_withdrawing_the_owners = await store.withdraw_lowering(owners_lowering, by=sam)

        not_allowed = LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.NOT_ALLOWED)
        assert lowering_the_owners == not_allowed
        assert owner_withdrawing_sams == not_allowed
        assert sam_withdrawing_the_owners == not_allowed
        assert await store.export() == before
    finally:
        store.close()


async def test_an_account_linked_to_one_identity_is_not_linked_to_another(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    _, sam = _with_sam(path)
    store = _open(path)
    try:
        before = await store.export()

        refused = await store.link(
            OWNER_PERSON_ID, SAMS_PHONE, act=LinkAct(how=LinkActHow.DEVICE, by=OWNER_PERSON_ID)
        )

        assert refused == LinkWrite(kind=LinkWriteKind.REFUSED, refusal=LinkRefusal.ALREADY_LINKED)
        assert await store.export() == before
        found = await store.find_link(SAMS_PHONE)
        assert found is not None
        assert found.person_id == sam
    finally:
        store.close()


async def test_a_configured_account_another_identity_holds_is_left_as_it_is(
    tmp_path: Path,
) -> None:
    path = tmp_path / "identities.db"
    _, sam = _with_sam(path)

    store = _open(path, configured=(SAMS_PHONE, LAPTOP))
    try:
        found = await store.find_link(SAMS_PHONE)
        laptop = await store.find_link(LAPTOP)
    finally:
        store.close()

    assert found is not None
    assert found.person_id == sam
    assert laptop is not None
    assert laptop.person_id == OWNER_PERSON_ID


# --- ids and cancellation ----------------------------------------------------------


class _Minting:
    """A ``new_id`` that mints the ids given in turn, then fresh ones of each kind."""

    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)
        self._fresh = 0

    def __call__(self, kind: str) -> str:
        if self._ids:
            return self._ids.pop(0)
        self._fresh += 1
        return f"{kind}:fresh-{self._fresh}"


async def test_an_id_a_held_record_carries_is_minted_again(tmp_path: Path) -> None:
    """No two records answer to one id, across links and lowerings."""
    store = _open(tmp_path / "identities.db", new_id=_Minting("record:one", "record:one"))
    try:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        lowering_id = written_id(await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID))
    finally:
        store.close()

    assert link_id == "record:one"
    assert lowering_id == "lowering:fresh-1"


async def test_a_factory_that_keeps_minting_a_held_id_fails_the_write_untouched(
    tmp_path: Path,
) -> None:
    store = _open(tmp_path / "identities.db", new_id=lambda _kind: "record:one")
    try:
        link_id = written_id(await store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        before = await store.export()

        with pytest.raises(IdentityStoreError, match="minted"):
            await store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER)
        with pytest.raises(IdentityStoreError, match="minted"):
            await store.lower(link_id, Sureness.NONE, by=OWNER_PERSON_ID)

        assert await store.export() == before
    finally:
        store.close()


async def test_a_cancelled_call_keeps_the_connection_until_its_worker_is_done(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    minted = iter(["link:slow", "link:second"])

    def slow_id(_kind: str) -> str:
        attempt = next(minted)
        if attempt == "link:slow":
            entered.set()
            release.wait(timeout=5)
        return attempt

    store = _open(tmp_path / "identities.db", new_id=slow_id)
    try:
        first = asyncio.create_task(store.link(OWNER_PERSON_ID, LINE, act=BY_THE_OWNER))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(store.link(OWNER_PERSON_ID, PHONE, act=BY_THE_OWNER))
        await asyncio.sleep(0.05)
        assert not second.done()  # the lock is still held for the running worker

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert (await second).record_id == "link:second"
        owner = await store.identity(OWNER_PERSON_ID)
        assert owner is not None
        assert [one.id for one in owner.links] == ["link:slow", "link:second"]
    finally:
        release.set()
        store.close()
