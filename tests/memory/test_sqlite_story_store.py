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
from story_store_contract import (
    STORY_AT,
    StoryStoreContract,
    act,
    draft,
    held,
    line,
    logged,
    made,
    noted,
    notes_of,
    state_of,
    sub,
    versions_of,
    written,
)

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import StoryActor, StorySafetyNetNote
from ai_assistant.memory import SqliteStoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
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


@pytest.mark.parametrize("operation", ["create", "link", "merge", "split", "move"])
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
            "move": lambda: store.move(source, target, [act("a")], actor=StoryActor.OWNER),
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


# --- the page (ADR-0300 §3) -----------------------------------------------------

#: ADR-0289's schema, version 1, as ``stories.db`` carried it before the page, with
#: one story holding an activation and a story.
_SCHEMA_1 = (
    "CREATE TABLE stories(id TEXT PRIMARY KEY, created_seq INTEGER NOT NULL UNIQUE, "
    "created_at INTEGER NOT NULL, merged_into TEXT)",
    "CREATE TABLE members(story_id TEXT NOT NULL, kind TEXT NOT NULL, "
    "member_id TEXT NOT NULL, position INTEGER NOT NULL UNIQUE, linked_at INTEGER NOT NULL, "
    "actor TEXT NOT NULL, PRIMARY KEY(story_id, kind, member_id))",
    "CREATE TABLE log(sequence INTEGER PRIMARY KEY AUTOINCREMENT, story_id TEXT NOT NULL, "
    "change TEXT NOT NULL, member_kind TEXT, member_id TEXT, other_story TEXT, "
    "actor TEXT NOT NULL, trigger_id TEXT, at INTEGER NOT NULL)",
    "INSERT INTO stories VALUES('story:inner', 1, 0, NULL)",
    "INSERT INTO stories VALUES('story:old', 2, 0, NULL)",
    "INSERT INTO log(sequence, story_id, change, actor, at) "
    "VALUES(1, 'story:inner', 'created', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, actor, at) "
    "VALUES(2, 'story:old', 'created', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, member_kind, member_id, actor, at) "
    "VALUES(3, 'story:old', 'added', 'activation', 'a1', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, member_kind, member_id, actor, at) "
    "VALUES(4, 'story:old', 'added', 'story', 'story:inner', 'owner', 0)",
    "INSERT INTO members VALUES('story:old', 'activation', 'a1', 3, 0, 'owner')",
    "INSERT INTO members VALUES('story:old', 'story', 'story:inner', 4, 0, 'owner')",
    "PRAGMA user_version = 1",
)


async def test_a_schema_one_file_is_migrated_with_every_activation_member_pending(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stories.db"
    conn = sqlite3.connect(path)
    for statement in _SCHEMA_1:
        conn.execute(statement)
    conn.commit()
    conn.close()
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        assert await held(store, "story:old") == [act("a1"), sub("story:inner")]
        state = await state_of(store, "story:old")
        assert state.pending_episodes == ("a1",)
        assert state.pending_notes == ()
        assert state.page is None
        note = await noted(store, "story:old", "After the migration.")
        assert note.note_id > state.as_of
        version = await written(
            store,
            "story:old",
            draft(line("The matter.", note.note_id), took_in_episodes=("a1",)),
            as_of=state.as_of,
        )
        assert version.took_in_episodes == ("a1",)
    finally:
        store.close()
    check = sqlite3.connect(path)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        check.close()


async def test_the_page_survives_a_reopen_and_the_counter_keeps_rising(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    first = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(first, act("a1"))
    note = await noted(first, story_id, "Riverside.")
    read = await state_of(first, story_id)
    version = await written(
        first,
        story_id,
        draft(
            line("A camping trip.", note.note_id, new=(0,)),
            safety_net=(StorySafetyNetNote(text="Booked.", rests_on="a1", outside=True),),
            took_in_notes=(note.note_id,),
        ),
        as_of=read.as_of,
    )
    page = (await state_of(first, story_id)).page
    notes = await notes_of(first, story_id)
    first.close()
    second = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        again = await state_of(second, story_id)
        assert again.page == page
        assert again.pending_episodes == ("a1",)
        assert await notes_of(second, story_id) == notes
        assert await versions_of(second, story_id) == [version]
        later = await noted(second, story_id, "Later.")
        assert later.note_id > version.version
    finally:
        second.close()


async def test_a_note_is_never_rewritten_or_removed_by_the_database(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a1"))
    await noted(store, story_id, "Kept as written.")
    store.close()
    conn = sqlite3.connect(path)
    try:
        for statement in (
            "UPDATE notes SET text = 'rewritten'",
            "UPDATE notes SET author = 'owner'",
            "UPDATE notes SET rests_on = 'a2'",
            "UPDATE notes SET outside = 1",
            "UPDATE notes SET written_at = 0",
        ):
            with pytest.raises(sqlite3.DatabaseError, match="never rewritten"):
                conn.execute(statement)
        with pytest.raises(sqlite3.DatabaseError, match="never removed"):
            conn.execute("DELETE FROM notes")
        conn.execute("UPDATE notes SET story_id = 'story:elsewhere', pending_since = NULL")
    finally:
        conn.close()


async def test_the_version_log_refuses_a_rewrite_or_a_removal(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a1"))
    note = await noted(store, story_id, "Note.")
    await written(
        store,
        story_id,
        draft(line("Line.", note.note_id)),
        as_of=(await state_of(store, story_id)).as_of,
    )
    store.close()
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE versions SET record = '{}'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM versions")
    finally:
        conn.close()


async def test_a_replaced_page_leaves_no_text_in_the_file(tmp_path: Path) -> None:
    """Only the current page is kept as text (ADR-0300 §3:6), in the file as well."""
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    old = "the-old-line-" + "q" * 64
    try:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        await written(
            store,
            story_id,
            draft(line(old, note.note_id)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        await written(
            store,
            story_id,
            draft(line("A new line.", note.note_id)),
            as_of=(await state_of(store, story_id)).as_of,
        )
    finally:
        store.close()
    assert old.encode() not in path.read_bytes()


async def test_a_backend_failure_mid_page_write_writes_nothing(tmp_path: Path) -> None:
    """The safety-net notes and the take-in are undone when the version cannot be written."""
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        story_id = await made(store, act("a1"))
        note = await noted(store, story_id, "Note.")
        before = (await state_of(store, story_id), await notes_of(store, story_id))
        injector = sqlite3.connect(path)
        injector.execute(
            "CREATE TRIGGER injected BEFORE INSERT ON versions "
            "BEGIN SELECT RAISE(ABORT, 'injected fault'); END"
        )
        injector.commit()
        with pytest.raises(StoryStoreError, match="injected fault"):
            await store.write_page(
                story_id,
                draft(
                    line("Line.", note.note_id, new=(0,)),
                    safety_net=(StorySafetyNetNote(text="Net.", rests_on="a1", outside=False),),
                    took_in_notes=(note.note_id,),
                    took_in_episodes=("a1",),
                ),
                as_of=before[0].as_of,
            )
        assert (await state_of(store, story_id), await notes_of(store, story_id)) == before
        assert await versions_of(store, story_id) == []
        injector.execute("DROP TRIGGER injected")
        injector.commit()
        injector.close()
    finally:
        store.close()


@pytest.mark.parametrize(
    ("statement", "read"),
    [
        ("UPDATE pages SET lines = 'not json'", "page"),
        ("UPDATE pages SET lines = '[]'", "page"),
        ("UPDATE pages SET lines = 7", "page"),
        ("UPDATE notes SET outside = 2", "notes"),
        ("UPDATE versions SET record = '[1]'", "versions"),
    ],
)
async def test_a_corrupt_page_record_is_a_story_store_error(
    tmp_path: Path, statement: str, read: str
) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a1"))
    note = await noted(store, story_id, "Note.")
    await written(
        store,
        story_id,
        draft(line("Line.", note.note_id)),
        as_of=(await state_of(store, story_id)).as_of,
    )
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER notes_never_rewritten")
    conn.execute("DROP TRIGGER versions_never_rewritten")
    conn.execute(statement)
    conn.commit()
    conn.close()
    reopened = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    reads: dict[str, Callable[[], Awaitable[object]]] = {
        "page": lambda: reopened.current_page(story_id),
        "notes": lambda: reopened.notes(story_id),
        "versions": lambda: reopened.page_versions(story_id),
    }
    try:
        with pytest.raises(StoryStoreError):
            await reads[read]()
    finally:
        reopened.close()
