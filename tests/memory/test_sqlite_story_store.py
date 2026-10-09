"""``SqliteStoryStore`` passes the shared conformance suite, plus its own parts.

The suite is bound to the production store as well as to the canonical fake, because
a suite bound only to the double certifies the double while the real store drifts.
Beside the binding are the properties of this backend alone: the owner-only file
mode (ADR-0004 §4), durability across a reopen, the append-only log enforced by the
database itself, the schema version and its migrations — ADR-0303 §4:8's included,
which keeps every note and every summary while dropping what a line cited, the
safety-net notes a version added and its supersession marks — and a store fault
surfacing as ``StoryStoreError`` with nothing written — a decision's line included,
which lands with the change it records or not at all (ADR-0302 §3:4).
"""

from __future__ import annotations

import json
import sqlite3
import stat
from typing import TYPE_CHECKING

import pytest
from story_store_contract import (
    STORY_AT,
    StoryStoreContract,
    act,
    draft,
    everything,
    held,
    line,
    logged,
    made,
    noted,
    notes_of,
    raised,
    state_of,
    sub,
    versions_of,
    written,
)

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    StoryActor,
    StoryChange,
    StoryDecision,
    StoryFlag,
    StoryFlagKind,
    StoryFlagName,
    StoryNoteAuthor,
    StoryOutcome,
    StoryRefusalReason,
    StorySummaryLine,
    StorySummaryVersionName,
)
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


# --- the notes and the summary (ADR-0300 §3) ------------------------------------

#: ADR-0289's schema, version 1, as ``stories.db`` carried it before the notes and the summary, with
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
        assert state.summary is None
        note = await noted(store, "story:old", "After the migration.")
        assert note.note_id > state.as_of
        version = await written(
            store,
            "story:old",
            draft(line("The matter."), took_in_episodes=("a1",)),
            as_of=state.as_of,
        )
        assert version.took_in_episodes == ("a1",)
    finally:
        store.close()
    check = sqlite3.connect(path)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        check.close()


async def test_the_summary_survives_a_reopen_and_the_counter_keeps_rising(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    first = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(first, act("a1"))
    note = await noted(first, story_id, "Riverside.")
    read = await state_of(first, story_id)
    version = await written(
        first,
        story_id,
        draft(line("A camping trip."), outside=True, took_in_notes=(note.note_id,)),
        as_of=read.as_of,
    )
    summary = (await state_of(first, story_id)).summary
    notes = await notes_of(first, story_id)
    first.close()
    second = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        again = await state_of(second, story_id)
        assert again.summary == summary
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
            "UPDATE notes SET written_during = 'a2'",
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
    await noted(store, story_id, "Note.")
    await written(
        store,
        story_id,
        draft(line("Line.")),
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


async def test_a_replaced_summary_leaves_no_text_in_the_file(tmp_path: Path) -> None:
    """Only the summary is kept as text (ADR-0300 §3:6), in the file as well."""
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    old = "the-old-line-" + "q" * 64
    try:
        story_id = await made(store, act("a1"))
        await noted(store, story_id, "Note.")
        await written(
            store,
            story_id,
            draft(line(old)),
            as_of=(await state_of(store, story_id)).as_of,
        )
        await written(
            store,
            story_id,
            draft(line("A new line.")),
            as_of=(await state_of(store, story_id)).as_of,
        )
    finally:
        store.close()
    assert old.encode() not in path.read_bytes()


@pytest.mark.parametrize("operation", ["merge", "split", "move"])
async def test_a_backend_failure_carrying_notes_rolls_the_whole_operation_back(
    tmp_path: Path, operation: str
) -> None:
    """A fault on the second note carried leaves members, log, notes and pending as they were.

    The fault is injected by a trigger on the second note's move, so it fires inside
    the operation's transaction after the membership writes and the first note's
    move — the point a store carrying notes outside that transaction would leave the
    membership moved and one note with it.
    """
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        source = await made(store, act("a"), act("b"))
        target = await made(store, act("c"))
        first = await noted(store, source, "First on a.", on="a")
        second = await noted(store, source, "Second on a.", on="a")
        named = [first.note_id, second.note_id]
        before = await everything(store)
        injector = sqlite3.connect(path)
        injector.execute(
            "CREATE TRIGGER injected BEFORE UPDATE OF story_id ON notes "
            f"WHEN NEW.id = {second.note_id} "
            "BEGIN SELECT RAISE(ABORT, 'injected fault'); END"
        )
        injector.commit()
        attempts = {
            "merge": lambda: store.merge(source, target, actor=StoryActor.OWNER),
            "split": lambda: store.split(source, [act("a")], actor=StoryActor.OWNER, notes=named),
            "move": lambda: store.move(
                source, target, [act("a")], actor=StoryActor.OWNER, notes=named
            ),
        }
        with pytest.raises(StoryStoreError, match="injected fault"):
            await attempts[operation]()
        assert await everything(store) == before
        injector.execute("DROP TRIGGER injected")
        injector.commit()
        injector.close()
    finally:
        store.close()


async def test_a_backend_failure_mid_summary_write_writes_nothing(tmp_path: Path) -> None:
    """The take-in and the summary are undone when the version cannot be written."""
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
            await store.write_summary(
                story_id,
                draft(line("Line."), took_in_notes=(note.note_id,), took_in_episodes=("a1",)),
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
        ("UPDATE pages SET lines = 'not json'", "summary"),
        ("""UPDATE pages SET lines = '[{"text": "Line.", "cites": [2]}]'""", "summary"),
        ("UPDATE pages SET lines = 7", "summary"),
        ("UPDATE pages SET outside = 2", "summary"),
        ("UPDATE notes SET outside = 2", "notes"),
        ("UPDATE versions SET record = '[1]'", "versions"),
    ],
)
async def test_a_corrupt_summary_record_is_a_story_store_error(
    tmp_path: Path, statement: str, read: str
) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a1"))
    await noted(store, story_id, "Note.")
    await written(
        store,
        story_id,
        draft(line("Line.")),
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
        "summary": lambda: reopened.current_summary(story_id),
        "notes": lambda: reopened.notes(story_id),
        "versions": lambda: reopened.summary_versions(story_id),
    }
    try:
        with pytest.raises(StoryStoreError):
            await reads[read]()
    finally:
        reopened.close()


# --- decisions on flags (ADR-0302 §§3-4, §10) -----------------------------------

#: ADR-0300's schema, version 2, as ``stories.db`` carried it before the decision
#: lines: one story holding an activation, with a note and a summary version raising a
#: flag (the indexes and triggers this test does not need are left out).
_SCHEMA_2 = (
    "CREATE TABLE stories(id TEXT PRIMARY KEY, created_seq INTEGER NOT NULL UNIQUE, "
    "created_at INTEGER NOT NULL, merged_into TEXT)",
    "CREATE TABLE members(story_id TEXT NOT NULL, kind TEXT NOT NULL, "
    "member_id TEXT NOT NULL, position INTEGER NOT NULL UNIQUE, linked_at INTEGER NOT NULL, "
    "actor TEXT NOT NULL, pending_since INTEGER, PRIMARY KEY(story_id, kind, member_id))",
    "CREATE TABLE log(sequence INTEGER PRIMARY KEY AUTOINCREMENT, story_id TEXT NOT NULL, "
    "change TEXT NOT NULL, member_kind TEXT, member_id TEXT, other_story TEXT, "
    "actor TEXT NOT NULL, trigger_id TEXT, at INTEGER NOT NULL)",
    "CREATE TABLE ticks(only INTEGER PRIMARY KEY CHECK (only = 0), value INTEGER NOT NULL)",
    "INSERT INTO ticks(only, value) VALUES(0, 3)",
    "CREATE TABLE notes(id INTEGER PRIMARY KEY, story_id TEXT NOT NULL, text TEXT NOT NULL, "
    "author TEXT NOT NULL, rests_on TEXT, outside INTEGER NOT NULL, "
    "written_at INTEGER NOT NULL, pending_since INTEGER)",
    "CREATE TABLE pages(story_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
    "written_at INTEGER NOT NULL, lines TEXT NOT NULL)",
    "CREATE TABLE versions(version INTEGER PRIMARY KEY, story_id TEXT NOT NULL, "
    "written_at INTEGER NOT NULL, record TEXT NOT NULL)",
    "INSERT INTO stories VALUES('story:old', 1, 0, NULL)",
    "INSERT INTO log(sequence, story_id, change, actor, at) "
    "VALUES(1, 'story:old', 'created', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, member_kind, member_id, actor, at) "
    "VALUES(2, 'story:old', 'added', 'activation', 'a1', 'owner', 0)",
    "INSERT INTO members VALUES('story:old', 'activation', 'a1', 2, 0, 'owner', 1)",
    "INSERT INTO notes VALUES(2, 'story:old', 'Note.', 'planning', 'a1', 0, 0, NULL)",
    "INSERT INTO pages VALUES('story:old', 3, 0, "
    """'[{"text": "Line.", "cites": [2], "outside": false}]')""",
    "INSERT INTO versions VALUES(3, 'story:old', 0, "
    """'{"lines": [[2]], "took_in_notes": [2], "flags": [{"kind": "two_matters"}]}')""",
    "PRAGMA user_version = 2",
)


async def test_a_schema_two_file_is_migrated_and_its_lines_stand_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stories.db"
    conn = sqlite3.connect(path)
    for statement in _SCHEMA_2:
        conn.execute(statement)
    conn.commit()
    conn.close()
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        lines = await logged(store, "story:old")
        assert [(line.change, line.answers, line.outcome) for line in lines] == [
            (StoryChange.CREATED, None, None),
            (StoryChange.ADDED, None, None),
        ]
        flag = StoryFlagName(
            story="story:old", version=3, flag=StoryFlag(kind=StoryFlagKind.TWO_MATTERS)
        )
        outcome = await store.leave_flag(flag, actor=StoryActor.MATTERS_PASS)
        assert outcome == StoryOutcome(story_id="story:old", logged=1)
        after = await logged(store, "story:old")
        assert after[:2] == lines
        assert (after[-1].answers, after[-1].outcome) == (flag, StoryDecision.LEFT)
        state = await state_of(store, "story:old")
        assert state.summary is not None
        assert (state.summary.lines, state.summary.outside) == (
            (StorySummaryLine(text="Line."),),
            False,
        )
        assert [note.written_during for note in await notes_of(store, "story:old")] == ["a1"]
    finally:
        store.close()
    check = sqlite3.connect(path)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 4
    finally:
        check.close()


# --- ADR-0303 §4:8: the notes' and the summary's records migrated ---------------

#: ADR-0302's schema, version 3, as ``stories.db`` carried it before ADR-0303, with
#: its indexes and triggers, which the migration must carry through a column renamed.
_SCHEMA_3_LAYOUT = (
    "CREATE TABLE stories(id TEXT PRIMARY KEY, created_seq INTEGER NOT NULL UNIQUE, "
    "created_at INTEGER NOT NULL, merged_into TEXT)",
    "CREATE TABLE members(story_id TEXT NOT NULL, kind TEXT NOT NULL, "
    "member_id TEXT NOT NULL, position INTEGER NOT NULL UNIQUE, linked_at INTEGER NOT NULL, "
    "actor TEXT NOT NULL, pending_since INTEGER, PRIMARY KEY(story_id, kind, member_id))",
    "CREATE INDEX members_order ON members(story_id, position)",
    "CREATE INDEX members_reverse ON members(kind, member_id)",
    "CREATE TABLE log(sequence INTEGER PRIMARY KEY AUTOINCREMENT, story_id TEXT NOT NULL, "
    "change TEXT NOT NULL, member_kind TEXT, member_id TEXT, other_story TEXT, "
    "actor TEXT NOT NULL, trigger_id TEXT, at INTEGER NOT NULL, answers TEXT, outcome TEXT)",
    "CREATE INDEX log_story ON log(story_id, sequence)",
    "CREATE INDEX log_member ON log(member_kind, member_id)",
    "CREATE INDEX log_answers ON log(answers) WHERE answers IS NOT NULL",
    "CREATE TRIGGER log_never_rewritten BEFORE UPDATE ON log "
    "BEGIN SELECT RAISE(ABORT, 'the story change log is append-only'); END",
    "CREATE TRIGGER log_never_removed BEFORE DELETE ON log "
    "BEGIN SELECT RAISE(ABORT, 'the story change log is append-only'); END",
    "CREATE TABLE ticks(only INTEGER PRIMARY KEY CHECK (only = 0), value INTEGER NOT NULL)",
    "INSERT INTO ticks(only, value) VALUES(0, 9)",
    "CREATE TABLE notes(id INTEGER PRIMARY KEY, story_id TEXT NOT NULL, text TEXT NOT NULL, "
    "author TEXT NOT NULL, rests_on TEXT, outside INTEGER NOT NULL, "
    "written_at INTEGER NOT NULL, pending_since INTEGER)",
    "CREATE INDEX notes_story ON notes(story_id, id)",
    "CREATE INDEX notes_resting ON notes(story_id, rests_on)",
    "CREATE TRIGGER notes_never_rewritten "
    "BEFORE UPDATE OF id, text, author, rests_on, outside, written_at ON notes "
    "BEGIN SELECT RAISE(ABORT, 'a story note is never rewritten'); END",
    "CREATE TRIGGER notes_never_removed BEFORE DELETE ON notes "
    "BEGIN SELECT RAISE(ABORT, 'a story note is never removed'); END",
    "CREATE TABLE pages(story_id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
    "written_at INTEGER NOT NULL, lines TEXT NOT NULL)",
    "CREATE TABLE versions(version INTEGER PRIMARY KEY, story_id TEXT NOT NULL, "
    "written_at INTEGER NOT NULL, record TEXT NOT NULL)",
    "CREATE INDEX versions_story ON versions(story_id, version)",
    "CREATE TRIGGER versions_never_rewritten BEFORE UPDATE ON versions "
    "BEGIN SELECT RAISE(ABORT, 'the page version log is append-only'); END",
    "CREATE TRIGGER versions_never_removed BEFORE DELETE ON versions "
    "BEGIN SELECT RAISE(ABORT, 'the page version log is append-only'); END",
)

#: Two stories under that layout. ``story:old`` holds a planning note marked as
#: outside content, the user's own note and a tidy-up's safety-net note; version 5
#: cited the planning note, added the safety net and marked the user's note
#: superseded; version 8, the summary's, cited the user's note and the safety net,
#: and its second line was marked. ``story:quiet`` has one version citing an unmarked
#: note, whose summary no line marks.
_SCHEMA_3_RECORDS = (
    "INSERT INTO stories VALUES('story:old', 1, 0, NULL)",
    "INSERT INTO stories VALUES('story:quiet', 3, 0, NULL)",
    "INSERT INTO log(sequence, story_id, change, actor, at) "
    "VALUES(1, 'story:old', 'created', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, member_kind, member_id, actor, at) "
    "VALUES(2, 'story:old', 'added', 'activation', 'a1', 'owner', 0)",
    "INSERT INTO log(sequence, story_id, change, actor, at) "
    "VALUES(3, 'story:quiet', 'created', 'owner', 0)",
    "INSERT INTO members VALUES('story:old', 'activation', 'a1', 2, 0, 'owner', NULL)",
    "INSERT INTO notes VALUES(1, 'story:old', 'Lower loop closes.', 'planning', 'a1', 1, 0, NULL)",
    "INSERT INTO notes VALUES(2, 'story:old', 'No Saturdays.', 'owner', NULL, 0, 0, NULL)",
    "INSERT INTO notes VALUES(4, 'story:old', 'Booked Sunday.', 'tidy_up', 'a1', 0, 0, NULL)",
    "INSERT INTO notes VALUES(6, 'story:quiet', 'Quiet.', 'planning', 'a9', 0, 0, NULL)",
    "INSERT INTO versions VALUES(5, 'story:old', 0, "
    """'{"lines": [[1]], "safety_net": [4], "took_in_notes": [1, 2], """
    """"took_in_episodes": ["a1"], "supersessions": [{"note": 2, "episode": "a1"}], """
    """"flags": [{"kind": "two_matters"}]}')""",
    "INSERT INTO versions VALUES(7, 'story:quiet', 0, "
    """'{"lines": [[6]], "safety_net": [], "took_in_notes": [6], "took_in_episodes": [], """
    """"supersessions": [], "flags": []}')""",
    "INSERT INTO versions VALUES(8, 'story:old', 0, "
    """'{"lines": [[2], [4]], "safety_net": [], "took_in_notes": [], """
    """"took_in_episodes": [], "supersessions": [], "flags": []}')""",
    "INSERT INTO pages VALUES('story:old', 8, 0, "
    """'[{"text": "Camping.", "cites": [2], "outside": false}, """
    """{"text": "Booked Sunday.", "cites": [4], "outside": true}]')""",
    "INSERT INTO pages VALUES('story:quiet', 7, 0, "
    """'[{"text": "Quiet.", "cites": [6], "outside": false}]')""",
    "PRAGMA user_version = 3",
)


def _schema_3(path: Path) -> None:
    conn = sqlite3.connect(path)
    for statement in (*_SCHEMA_3_LAYOUT, *_SCHEMA_3_RECORDS):
        conn.execute(statement)
    conn.commit()
    conn.close()


async def test_a_schema_three_file_keeps_every_note_and_summary_and_drops_what_adr_0303_retires(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stories.db"
    _schema_3(path)
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        notes = await notes_of(store, "story:old")
        assert [
            (note.note_id, note.author, note.written_during, note.outside) for note in notes
        ] == [
            (1, StoryNoteAuthor.PLANNING, "a1", True),
            (2, StoryNoteAuthor.OWNER, None, False),
            (4, StoryNoteAuthor.TIDY_UP, "a1", False),
        ]
        versions = await versions_of(store, "story:old")
        assert [
            (v.version, v.took_in_notes, v.took_in_episodes, v.read_pages, v.flags, v.outside)
            for v in versions
        ] == [
            (5, (1, 2), ("a1",), (), (StoryFlag(kind=StoryFlagKind.TWO_MATTERS),), True),
            (8, (), (), (), (), True),
        ]
        summary = (await state_of(store, "story:old")).summary
        assert summary is not None
        assert (summary.version, summary.outside) == (8, True)
        assert summary.lines == (
            StorySummaryLine(text="Camping."),
            StorySummaryLine(text="Booked Sunday."),
        )
        quiet = (await state_of(store, "story:quiet")).summary
        assert quiet is not None
        assert (quiet.lines, quiet.outside) == ((StorySummaryLine(text="Quiet."),), False)
        assert [v.outside for v in await versions_of(store, "story:quiet")] == [False]
        # The migrated file is written as a fresh one is: a summary may be read by its
        # version, and a version after the counter's last reading follows it.
        read = await state_of(store, "story:quiet")
        later = await written(
            store,
            "story:quiet",
            draft(
                line("Quieter."),
                read_pages=(StorySummaryVersionName(story="story:old", version=8),),
            ),
            as_of=read.as_of,
        )
        assert later.version > 9
    finally:
        store.close()
    check = sqlite3.connect(path)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 4
        indexes = {row[0] for row in check.execute("SELECT name FROM sqlite_master")}
        assert {"notes_resting", "log_member"}.isdisjoint(indexes)
        with pytest.raises(sqlite3.DatabaseError, match="never rewritten"):
            check.execute("UPDATE notes SET written_during = 'a2'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            check.execute("UPDATE versions SET record = '{}'")
        for (record,) in check.execute("SELECT record FROM versions"):
            assert {"lines", "safety_net", "supersessions"}.isdisjoint(json.loads(record))
    finally:
        check.close()


@pytest.mark.parametrize(
    "statement",
    [
        """UPDATE versions SET record = '{"lines": 7}' WHERE version = 5""",
        """UPDATE versions SET record = '{"lines": [[{}]]}' WHERE version = 5""",
        """UPDATE versions SET record = '{"lines": [], "safety_net": [[4]]}' WHERE version = 5""",
        """UPDATE versions SET record = '[5]' WHERE version = 5""",
        """UPDATE versions SET record = 'not json' WHERE version = 5""",
        """UPDATE pages SET lines = '[7]' WHERE story_id = 'story:old'""",
        """UPDATE pages SET lines = '{"text": "x"}' WHERE story_id = 'story:old'""",
    ],
)
async def test_a_schema_three_file_whose_records_are_not_its_own_is_refused(
    tmp_path: Path, statement: str
) -> None:
    """A record the migration cannot read, of any shape, is a store error and nothing else.

    The file is left as it was: the migration's transaction rolls back whole.
    """
    path = tmp_path / "stories.db"
    _schema_3(path)
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER versions_never_rewritten")
    conn.execute(statement)
    conn.commit()
    conn.close()
    with pytest.raises(StoryStoreError):
        SqliteStoryStore(path=path, now=lambda: STORY_AT)
    check = sqlite3.connect(path)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        check.close()


async def test_a_decision_survives_a_reopen(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    first = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(first, act("a1"), act("a2"))
    flag = await raised(first, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    await first.leave_flag(flag, actor=StoryActor.MATTERS_PASS)
    lines = await logged(first, story_id)
    first.close()
    second = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        assert await logged(second, story_id) == lines
        outcome = await second.leave_flag(flag, actor=StoryActor.MATTERS_PASS)
        assert outcome.refusal is not None
        assert outcome.refusal.reason is StoryRefusalReason.ALREADY_DECIDED
    finally:
        second.close()


@pytest.mark.parametrize("operation", ["create", "link", "merge", "split", "move", "leave"])
async def test_a_decision_and_its_change_land_together_or_not_at_all(
    tmp_path: Path, operation: str
) -> None:
    """A fault on the ``decided`` line rolls the change it records back with it.

    The fault is injected by a trigger another connection installs on the log, firing
    only on a ``decided`` line, so it fires inside the operation's transaction after
    every line and row of the change itself is written — the point a store writing
    the decision in a transaction of its own would leave the change made and the flag
    open (ADR-0302 §3:4).
    """
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    pass_ = StoryActor.MATTERS_PASS
    try:
        other = await made(store, act("b1"))
        story_id = await made(store, act("a1"), act("a2"))
        larger = await made(store, act("z"))
        await noted(store, story_id, "On a2.", on="a2")
        flag = await raised(
            store, story_id, StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
        )
        before = await everything(store)
        injector = sqlite3.connect(path)
        injector.execute(
            "CREATE TRIGGER injected BEFORE INSERT ON log WHEN NEW.change = 'decided' "
            "BEGIN SELECT RAISE(ABORT, 'injected fault'); END"
        )
        injector.commit()
        attempts: dict[str, Callable[[], Awaitable[StoryOutcome]]] = {
            "create": lambda: store.create([sub(story_id), sub(other)], actor=pass_, answers=flag),
            "link": lambda: store.link(
                larger, [sub(story_id), sub(other)], actor=pass_, answers=flag
            ),
            "merge": lambda: store.merge(story_id, other, actor=pass_, answers=flag),
            "split": lambda: store.split(story_id, [act("a2")], actor=pass_, answers=flag),
            "move": lambda: store.move(story_id, other, [act("a2")], actor=pass_, answers=flag),
            "leave": lambda: store.leave_flag(flag, actor=pass_),
        }
        with pytest.raises(StoryStoreError, match="injected fault"):
            await attempts[operation]()
        assert await everything(store) == before
        injector.execute("DROP TRIGGER injected")
        injector.commit()
        injector.close()
        outcome = await attempts[operation]()
        assert outcome.refusal is None
    finally:
        store.close()


async def test_a_corrupt_decision_is_a_story_store_error(tmp_path: Path) -> None:
    path = tmp_path / "stories.db"
    store = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    story_id = await made(store, act("a1"))
    flag = await raised(store, story_id, StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    await store.leave_flag(flag, actor=StoryActor.MATTERS_PASS)
    store.close()
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER log_never_rewritten")
    conn.execute("UPDATE log SET answers = '{\"story\": \"story:x\"}' WHERE change = 'decided'")
    conn.commit()
    conn.close()
    reopened = SqliteStoryStore(path=path, now=lambda: STORY_AT)
    try:
        with pytest.raises(StoryStoreError, match="does not validate"):
            await reopened.log(story_id)
    finally:
        reopened.close()
