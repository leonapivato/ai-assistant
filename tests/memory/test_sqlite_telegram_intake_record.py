"""SqliteTelegramIntakeRecord: the shared conformance suite, plus what only it owes.

The suite holds the contract; this module holds what belongs to a *persistent* store:
that the file is owner-only (ADR-0004 §4), that what it wrote survives a reopen — a
claim with no outcome above all, which is what a crash leaves (§13:2) — that a file
of another schema is refused before anything is written, that a broken backend or a
corrupt row surfaces as the seam's own error, that two handles on one file share one
record, and that a cancelled call keeps the connection until its worker is done
(ADR-0054).
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
import stat
import threading
from typing import TYPE_CHECKING

import pytest
from telegram_intake_record_contract import (
    ACTIVATION,
    POLLED,
    SENT,
    TelegramIntakeRecordContract,
    TelegramIntakeRecordFactory,
)

from ai_assistant.core.errors import TelegramIntakeRecordError
from ai_assistant.core.types import TelegramCallOutcome, TelegramIntakeKind
from ai_assistant.memory import SqliteTelegramIntakeRecord
from ai_assistant.memory.telegram_intake import DEFAULT_KEPT_CALLS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import TelegramIntakeRecord

pytestmark = pytest.mark.anyio

#: The store's default bound, restated rather than imported for the contract binding:
#: the fake restates the same figure, so the two cannot drift apart unnoticed.
_KEPT_CALLS_DEFAULT = 1000


class TestSqliteTelegramIntakeRecordContract(TelegramIntakeRecordContract):
    """Runs SqliteTelegramIntakeRecord through the shared TelegramIntakeRecord suite."""

    @pytest.fixture
    def record(self, tmp_path: Path) -> Iterator[TelegramIntakeRecord]:
        store = SqliteTelegramIntakeRecord(path=tmp_path / "telegram.db")
        yield store
        store.close()

    @pytest.fixture
    def factory(self, tmp_path: Path) -> Iterator[TelegramIntakeRecordFactory]:
        opened: list[SqliteTelegramIntakeRecord] = []

        def build(
            *, kept_calls: int = _KEPT_CALLS_DEFAULT, new_id: Callable[[], str] | None = None
        ) -> TelegramIntakeRecord:
            path = tmp_path / f"telegram-{len(opened)}.db"
            if new_id is None:
                store = SqliteTelegramIntakeRecord(path=path, kept_calls=kept_calls)
            else:
                store = SqliteTelegramIntakeRecord(path=path, kept_calls=kept_calls, new_id=new_id)
            opened.append(store)
            return store

        yield build
        for store in opened:
            store.close()


def test_the_default_bound_is_the_fakes() -> None:
    assert DEFAULT_KEPT_CALLS == _KEPT_CALLS_DEFAULT


async def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    journal = tmp_path / "telegram.db-journal"
    journal.write_bytes(b"")
    journal.chmod(0o644)

    store = SqliteTelegramIntakeRecord(path=path)
    try:
        await store.take_in([1], activation_id=ACTIVATION)
    finally:
        store.close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with contextlib.suppress(FileNotFoundError):
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600


async def test_everything_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    first = SqliteTelegramIntakeRecord(path=path)
    try:
        await first.take_in([10], activation_id=ACTIVATION)
        reply = await first.claim_reply(11)
        assert reply is not None
        await first.finish(reply, SENT)
        await first.confirm_through(11)
        open_poll = await first.claim_poll()
    finally:
        first.close()

    again = SqliteTelegramIntakeRecord(path=path)
    try:
        held = await again.recorded([10, 11])
        assert held[10].activation_id == ACTIVATION
        assert held[11].kind is TelegramIntakeKind.ANSWERED
        assert await again.take_in([10], activation_id="activation-0002") == ()
        assert await again.claim_reply(11) is None
        assert (await again.claim_poll()).offset == 12
        # What a crash leaves: a claim with no outcome, never resolved by the reopen.
        crashed = await again.call(open_poll.attempt)
        assert crashed is not None
        assert crashed.outcome is None
    finally:
        again.close()


async def test_a_reply_claimed_before_a_crash_is_not_sent_again(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    first = SqliteTelegramIntakeRecord(path=path)
    try:
        assert await first.claim_reply(11) is not None
    finally:
        first.close()

    again = SqliteTelegramIntakeRecord(path=path)
    try:
        assert await again.claim_reply(11) is None
    finally:
        again.close()


async def test_two_handles_on_one_file_share_one_record(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    one = SqliteTelegramIntakeRecord(path=path)
    other = SqliteTelegramIntakeRecord(path=path)
    try:
        assert await one.claim_reply(11) is not None
        assert await other.claim_reply(11) is None
        assert await other.take_in([11, 12], activation_id=ACTIVATION) == (12,)
        assert await one.take_in([12], activation_id=ACTIVATION) == ()
    finally:
        one.close()
        other.close()


async def test_a_file_of_another_schema_is_refused_untouched(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE intake(update_id INTEGER PRIMARY KEY)")
        conn.execute("PRAGMA user_version = 7")
        conn.commit()

    with pytest.raises(TelegramIntakeRecordError, match="schema version 7"):
        SqliteTelegramIntakeRecord(path=path)

    with contextlib.closing(sqlite3.connect(path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert tables == {"intake"}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 7


def test_a_path_that_cannot_be_opened_is_the_seams_error(tmp_path: Path) -> None:
    with pytest.raises(TelegramIntakeRecordError):
        SqliteTelegramIntakeRecord(path=str(tmp_path / "bad\0name.db"))
    with pytest.raises(TelegramIntakeRecordError):
        SqliteTelegramIntakeRecord(path=tmp_path / "missing" / "telegram.db")


@pytest.mark.parametrize("kept_calls", [0, -1, 2**63, True, 1.5], ids=repr)
def test_a_bound_below_one_is_refused(tmp_path: Path, kept_calls: object) -> None:
    with pytest.raises(ValueError, match="kept_calls"):
        SqliteTelegramIntakeRecord(path=tmp_path / "telegram.db", kept_calls=kept_calls)  # type: ignore[arg-type]


async def test_a_closed_backend_is_the_seams_error() -> None:
    store = SqliteTelegramIntakeRecord(path=":memory:")
    store.close()

    with pytest.raises(TelegramIntakeRecordError):
        await store.take_in([1], activation_id=ACTIVATION)
    with pytest.raises(TelegramIntakeRecordError):
        await store.export()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO intake(update_id, kind, activation_id) VALUES (5, 'mystery', NULL)",
        "INSERT INTO intake(update_id, kind, activation_id) VALUES (5, 'taken_in', NULL)",
        "INSERT INTO calls(attempt, kind, finished) VALUES ('a', 'poll', 2)",
        "INSERT INTO calls(attempt, kind, update_id) VALUES ('a', 'poll', 5)",
        "INSERT INTO calls(attempt, kind, finished, failure) VALUES ('a', 'poll', 1, 'odd')",
        "UPDATE owed SET offset_owed = 'x' WHERE id = 1",
    ],
    ids=[
        "unknown-kind",
        "taken-in-by-nobody",
        "finished-not-a-flag",
        "poll-with-an-update",
        "unknown-failure",
        "offset-not-an-int",
    ],
)
async def test_a_corrupt_row_is_the_seams_error(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "telegram.db"
    SqliteTelegramIntakeRecord(path=path).close()
    with contextlib.closing(sqlite3.connect(path)) as conn:
        conn.execute(statement)
        conn.commit()

    store = SqliteTelegramIntakeRecord(path=path)
    try:
        with pytest.raises(TelegramIntakeRecordError, match="corrupt"):
            await store.export()
    finally:
        store.close()


async def test_a_cancelled_call_keeps_the_connection_until_its_worker_is_done(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    minted = iter(["slow", "second"])

    def slow_id() -> str:
        attempt = next(minted)
        if attempt == "slow":
            entered.set()
            release.wait(timeout=5)
        return attempt

    store = SqliteTelegramIntakeRecord(path=tmp_path / "telegram.db", new_id=slow_id)
    try:
        first = asyncio.create_task(store.claim_typing(ACTIVATION))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        second = asyncio.create_task(store.claim_typing(ACTIVATION))
        await asyncio.sleep(0.05)
        assert not second.done()  # the lock is still held for the running worker

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert await second == "second"
        claimed = [one.attempt for one in (await store.export()).calls]
        assert claimed == ["slow", "second"]
    finally:
        release.set()
        store.close()


async def test_a_done_poll_lets_go_of_what_it_confirmed_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "telegram.db"
    store = SqliteTelegramIntakeRecord(path=path)
    try:
        await store.take_in([3], activation_id=ACTIVATION)
        await store.confirm_through(3)
        claim = await store.claim_poll()
        await store.finish(claim.attempt, POLLED)
        held = await store.call(claim.attempt)
        assert held is not None
        assert held.outcome is TelegramCallOutcome.DONE
    finally:
        store.close()

    with contextlib.closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT count(*) FROM intake").fetchone()[0] == 0
        assert conn.execute("SELECT offset_owed FROM owed").fetchone()[0] is None
