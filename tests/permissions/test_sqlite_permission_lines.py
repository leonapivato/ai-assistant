"""SqlitePermissionLineStore passes the shared suite, and what only a file owes (ADR-0367 §3:6).

The binding runs the store through
:class:`~permission_line_store_contract.PermissionLineStoreContract`. Below it, what only
a persistent store has: an owner-only file that starts empty and stays so across
openings, lines and removals that survive a reopen, two handles on one file deciding a
repeated making as one store (ADR-0376 §4:5), the schema label ADR-0326 §5:3 reads, the
seam's error for a backend fault and a corrupt row, identifiers minted again rather than
reused, and a cancelled call that keeps the connection until its worker is done.
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
from permission_line_store_contract import (
    FULL_GRANT,
    LOOKUP_GRANT,
    MAIL_LIMIT,
    START,
    PermissionLineStoreContract,
    PermissionLineStoreFactory,
    made,
    removed,
    ticking,
)

from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LineMaking,
    LineMakingKind,
    LineRemoval,
    LineRemovalKind,
)
from ai_assistant.permissions import SqlitePermissionLineStore
from ai_assistant.permissions.lines import PERMISSION_LINES_SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import PermissionLineStore

pytestmark = pytest.mark.anyio


class TestSqlitePermissionLineStoreContract(PermissionLineStoreContract):
    """Runs SqlitePermissionLineStore through the shared PermissionLineStore suite."""

    @pytest.fixture
    def opened(self) -> Iterator[list[SqlitePermissionLineStore]]:
        held: list[SqlitePermissionLineStore] = []
        yield held
        for store in held:
            store.close()

    @pytest.fixture
    def factory(
        self, tmp_path: Path, opened: list[SqlitePermissionLineStore]
    ) -> PermissionLineStoreFactory:
        def build(*, now: Callable[[], datetime]) -> PermissionLineStore:
            store = SqlitePermissionLineStore(
                path=tmp_path / f"permission_lines-{len(opened)}.db", now=now
            )
            opened.append(store)
            return store

        return build


def _open(
    path: Path | str,
    *,
    now: Callable[[], datetime] | None = None,
    new_id: Callable[[], str] | None = None,
) -> SqlitePermissionLineStore:
    """The store at ``path``, on a ticking clock from ``START`` where none is named."""
    if new_id is None:
        return SqlitePermissionLineStore(path=path, now=now or ticking())
    return SqlitePermissionLineStore(path=path, now=now or ticking(), new_id=new_id)


def _sql(path: Path, *statements: str) -> None:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()


def _rows(path: Path) -> int:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        count: int = conn.execute("SELECT count(*) FROM lines").fetchone()[0]
        return count


# --- persistence -------------------------------------------------------------------


async def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "permission_lines.db"
    journal = tmp_path / "permission_lines.db-journal"
    journal.write_bytes(b"")
    journal.chmod(0o644)

    store = _open(path)
    try:
        made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with contextlib.suppress(FileNotFoundError):
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600


async def test_no_opening_seeds_a_line(tmp_path: Path) -> None:
    """ADR-0376 §3:3: a default line is its tool's declaration's, never the store's."""
    path = tmp_path / "permission_lines.db"
    _open(path).close()
    _open(path).close()

    assert _rows(path) == 0


async def test_every_line_and_removal_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "permission_lines.db"
    first = _open(path)
    try:
        kept = made(await first.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        limit = made(await first.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        gone = removed(await first.record_removal(limit.id, by=OWNER_PERSON_ID))
        lookup = made(await first.record_making(LOOKUP_GRANT, by=OWNER_PERSON_ID))
    finally:
        first.close()

    again = _open(path)
    try:
        assert await again.standing() == (kept, lookup)
        assert await again.line(gone.id) == gone
        # What the reopened store holds still decides.
        repeat = await again.record_making(FULL_GRANT, by=OWNER_PERSON_ID)
        assert repeat == LineMaking(kind=LineMakingKind.UNCHANGED, line=kept)
        removal = await again.record_removal(gone.id, by=OWNER_PERSON_ID)
        assert removal == LineRemoval(kind=LineRemovalKind.NOT_STANDING)
    finally:
        again.close()


async def test_two_handles_on_one_file_share_one_store(tmp_path: Path) -> None:
    """The repeat rule holds across handles, as across processes: the write step decides."""
    path = tmp_path / "permission_lines.db"
    one = _open(path)
    other = _open(path)
    try:
        first = made(await one.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        again = await other.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID)
        gone = removed(await other.record_removal(first.id, by=OWNER_PERSON_ID))

        assert again == LineMaking(kind=LineMakingKind.UNCHANGED, line=first)
        assert await one.standing() == ()
        assert await one.line(first.id) == gone
    finally:
        one.close()
        other.close()


@pytest.mark.parametrize("version", [0, PERMISSION_LINES_SCHEMA_VERSION + 1, 7])
async def test_a_file_of_another_schema_is_refused_untouched(tmp_path: Path, version: int) -> None:
    path = tmp_path / "permission_lines.db"
    _sql(path, "CREATE TABLE lines(id TEXT PRIMARY KEY)", f"PRAGMA user_version = {version}")

    with pytest.raises(PermissionLineStoreError, match=f"schema version {version}"):
        _open(path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert tables == {"lines"}
        assert conn.execute("SELECT count(*) FROM lines").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


@pytest.mark.parametrize("version", [1, PERMISSION_LINES_SCHEMA_VERSION + 1, 7])
def test_a_labelled_file_with_no_tables_is_refused_untouched(tmp_path: Path, version: int) -> None:
    """ADR-0326 §5:3: a newer label is refused whether or not the file holds a table."""
    path = tmp_path / "permission_lines.db"
    _sql(path, f"PRAGMA user_version = {version}")

    with pytest.raises(PermissionLineStoreError, match=f"schema version {version}"):
        _open(path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_a_new_store_writes_its_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "permission_lines.db"
    _open(path).close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == PERMISSION_LINES_SCHEMA_VERSION
            == 1
        )


def test_a_path_that_cannot_be_opened_is_the_seams_error(tmp_path: Path) -> None:
    with pytest.raises(PermissionLineStoreError):
        _open(str(tmp_path / "bad\0name.db"))
    with pytest.raises(PermissionLineStoreError):
        _open(tmp_path / "missing" / "permission_lines.db")


async def test_a_closed_backend_is_the_seams_error() -> None:
    store = SqlitePermissionLineStore(path=":memory:")
    store.close()

    with pytest.raises(PermissionLineStoreError):
        await store.standing()
    with pytest.raises(PermissionLineStoreError):
        await store.line("line:1")
    with pytest.raises(PermissionLineStoreError):
        await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID)
    with pytest.raises(PermissionLineStoreError):
        await store.record_removal("line:1", by=OWNER_PERSON_ID)


_A_LINE = (
    "INSERT INTO lines(id, kind, who, action, thing, how, bar, condition, made_by, made_at) "
    "VALUES ('line:x', {kind}, {who}, 'send_email', {thing}, {how}, {bar}, NULL, "
    "'person:owner', {made_at})"
)


def _row(**values: str) -> str:
    fields = {
        "kind": "'limit'",
        "who": "'person:owner'",
        "thing": "NULL",
        "how": "NULL",
        "bar": "NULL",
        "made_at": "'2026-11-24T09:00:00+00:00'",
    }
    return _A_LINE.format(**(fields | values))


@pytest.mark.parametrize(
    "statement",
    [
        _row(kind="'veto'"),
        _row(who="'person:sam'"),
        _row(thing="'conversation:chat-1'"),
        _row(how="'allowed'"),
        _row(kind="'grant'", how="'allowed'"),
        _row(kind="'grant'", how="'allowed'", bar="'certain'"),
        _row(made_at="'not-an-instant'"),
    ],
    ids=[
        "kind",
        "who",
        "thing",
        "how-on-a-limit",
        "grant-with-no-bar",
        "bar",
        "instant",
    ],
)
async def test_a_corrupt_row_is_the_seams_error(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "permission_lines.db"
    _open(path).close()
    _sql(path, statement)

    store = _open(path)
    try:
        with pytest.raises(PermissionLineStoreError, match="corrupt"):
            await store.standing()
        with pytest.raises(PermissionLineStoreError, match="corrupt"):
            await store.line("line:x")
        with pytest.raises(PermissionLineStoreError, match="corrupt"):
            await store.record_removal("line:x", by=OWNER_PERSON_ID)
    finally:
        store.close()
    assert _rows(path) == 1


async def test_a_making_whose_clock_fails_writes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "permission_lines.db"
    store = _open(path, now=lambda: datetime(2026, 11, 24))  # noqa: DTZ001  # the naive reading under test
    try:
        with pytest.raises(PermissionLineStoreError, match="clock"):
            await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID)

        assert await store.standing() == ()
    finally:
        store.close()
    assert _rows(path) == 0


async def test_a_removal_whose_clock_fails_writes_nothing(tmp_path: Path) -> None:
    readings = iter([START, datetime(2026, 11, 24)])  # noqa: DTZ001  # the naive reading under test
    path = tmp_path / "permission_lines.db"
    store = _open(path, now=lambda: next(readings))
    try:
        line = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        with pytest.raises(PermissionLineStoreError, match="clock"):
            await store.record_removal(line.id, by=OWNER_PERSON_ID)

        assert await store.standing() == (line,)
        assert await store.line(line.id) == line
    finally:
        store.close()


# --- identifiers and cancellation --------------------------------------------------


class _Minting:
    """A ``new_id`` that mints the identifiers given in turn, then fresh ones."""

    def __init__(self, *ids: str) -> None:
        self._ids = list(ids)
        self._fresh = 0

    def __call__(self) -> str:
        if self._ids:
            return self._ids.pop(0)
        self._fresh += 1
        return f"line:fresh-{self._fresh}"


async def test_an_identifier_a_removed_line_carries_is_minted_again(tmp_path: Path) -> None:
    """ADR-0367 §3:6: an identifier is never reused, a removed line's included."""
    store = _open(tmp_path / "permission_lines.db", new_id=_Minting("line:one", "line:one"))
    try:
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        removed(await store.record_removal(first.id, by=OWNER_PERSON_ID))
        second = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
    finally:
        store.close()

    assert first.id == "line:one"
    assert second.id == "line:fresh-1"


async def test_a_factory_that_keeps_minting_a_held_identifier_fails_untouched(
    tmp_path: Path,
) -> None:
    path = tmp_path / "permission_lines.db"
    store = _open(path, new_id=lambda: "line:one")
    try:
        first = made(await store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))

        with pytest.raises(PermissionLineStoreError, match="minted"):
            await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

        assert await store.standing() == (first,)
    finally:
        store.close()
    assert _rows(path) == 1


@pytest.mark.parametrize("minted", ["", "  ", 7])
async def test_a_minted_identifier_that_is_not_one_is_the_seams_error(
    tmp_path: Path, minted: object
) -> None:
    store = _open(tmp_path / "permission_lines.db", new_id=lambda: minted)  # type: ignore[arg-type, return-value]  # the malformed factory under test
    try:
        with pytest.raises(PermissionLineStoreError, match="not one"):
            await store.record_making(FULL_GRANT, by=OWNER_PERSON_ID)

        assert await store.standing() == ()
    finally:
        store.close()


async def test_a_cancelled_call_keeps_the_connection_until_its_worker_is_done(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    minted = iter(["line:slow", "line:second"])

    def slow_id() -> str:
        attempt = next(minted)
        if attempt == "line:slow":
            entered.set()
            release.wait(timeout=5)
        return attempt

    store = _open(tmp_path / "permission_lines.db", new_id=slow_id)
    try:
        first = asyncio.create_task(store.record_making(MAIL_LIMIT, by=OWNER_PERSON_ID))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(store.record_making(FULL_GRANT, by=OWNER_PERSON_ID))
        await asyncio.sleep(0.05)
        assert not second.done()  # the lock is still held for the running worker

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert made(await second).id == "line:second"
        assert [one.id for one in await store.standing()] == ["line:slow", "line:second"]
    finally:
        release.set()
        store.close()
