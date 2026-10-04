"""``SqliteStoryStore`` passes the shared conformance suite, plus its own parts.

The suite is bound to the production store as well as to the canonical fake, because
a suite bound only to the double certifies the double while the real store drifts.
Beside the binding are the properties of this backend alone: the owner-only file
mode (ADR-0004 §4), durability across a reopen, the append-only log enforced by the
database itself, the schema version, and a store fault surfacing as
``StoryStoreError`` with nothing written.
"""

from __future__ import annotations

import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest
from story_store_contract import STORY_AT, StoryStoreContract, act, held, logged, made

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import StoryActor
from ai_assistant.memory import SqliteStoryStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ai_assistant.core.protocols import StoryStore


class TestSqliteStoryStoreContract(StoryStoreContract):
    """Runs SqliteStoryStore through the shared StoryStore conformance suite."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> Iterator[StoryStore]:
        built = SqliteStoryStore(path=tmp_path / "stories.db", now=lambda: STORY_AT)
        try:
            yield built
        finally:
            built.close()


def test_the_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    SqliteStoryStore(path=path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_stories_survive_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    first = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(first, act("a"), act("b"))
    lines = await logged(first, story_id)
    first.close()
    second = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        assert await held(second, story_id) == [act("a"), act("b")]
        assert await logged(second, story_id) == lines
        later = await made(second, act("c"))
        assert (await logged(second, later))[0].sequence > lines[-1].sequence
    finally:
        second.close()


async def test_the_log_refuses_a_rewrite_or_a_removal(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    await made(store, act("a"))
    store.close()
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE log SET change = 'removed'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM log")
    finally:
        conn.close()


def test_a_file_of_another_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(StoryStoreError, match="schema version 99"):
        SqliteStoryStore(path=path)


def test_an_unopenable_path_is_a_story_store_error(tmp_path: Path) -> None:
    with pytest.raises(StoryStoreError):
        SqliteStoryStore(path=tmp_path / "absent" / "stories.db")


async def test_a_fault_mid_write_writes_nothing(tmp_path: Path) -> None:
    """A minted id the store already holds faults the create, which leaves no trace."""
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT, new_id=lambda: "fixed")
    try:
        story_id = await made(store, act("a"))
        before = await logged(store, story_id)
        with pytest.raises(StoryStoreError, match="already holds"):
            await store.create([act("b")], actor=StoryActor.OWNER)
        assert await logged(store, story_id) == before
        assert [h.story_id for h in (await store.stories()).stories] == [story_id]
    finally:
        store.close()


@pytest.mark.parametrize("operation", ["create", "link", "merge", "split"])
async def test_a_backend_failure_mid_write_rolls_the_whole_operation_back(
    tmp_path: Path, operation: str
) -> None:
    """A member insert failing after its log line is appended leaves neither behind.

    The fault is injected by a trigger another connection installs, so it fires inside
    the store's own transaction after ``_add`` has written the ``added`` line — the
    point a store writing the view and the log separately would leave an orphan line.
    """
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        source = await made(store, act("a"), act("b"))
        target = await made(store, act("c"))
        before = {
            story_id: (await held(store, story_id), await logged(store, story_id))
            for story_id in (source, target)
        }
        injector = sqlite3.connect(path)
        injector.execute(
            "CREATE TRIGGER injected BEFORE INSERT ON members "
            "BEGIN SELECT RAISE(ABORT, 'injected fault'); END"
        )
        injector.commit()
        attempts = {
            "create": lambda: store.create([act("d")], actor=StoryActor.OWNER),
            "link": lambda: store.link(source, [act("d")], actor=StoryActor.OWNER),
            "merge": lambda: store.merge(source, target, actor=StoryActor.OWNER),
            "split": lambda: store.split(source, [act("a")], actor=StoryActor.OWNER),
        }
        with pytest.raises(StoryStoreError, match="injected fault"):
            await attempts[operation]()
        after = {
            story_id: (await held(store, story_id), await logged(store, story_id))
            for story_id in (source, target)
        }
        assert after == before
        assert len((await store.stories()).stories) == 2
        injector.execute("DROP TRIGGER injected")
        injector.commit()
        injector.close()
        outcome = await store.link(source, [act("d")], actor=StoryActor.OWNER)
        assert outcome.logged == 1
        lines = await logged(store, source)
        assert lines[-1].sequence > max(line.sequence for line in before[target][1])
    finally:
        store.close()


async def test_a_corrupt_row_is_a_story_store_error(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a"))
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("UPDATE members SET actor = 'stranger'")
    conn.commit()
    conn.close()
    reopened = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        with pytest.raises(StoryStoreError, match="does not validate"):
            await reopened.view(story_id)
    finally:
        reopened.close()
