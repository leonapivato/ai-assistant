"""ADR-0326 §4:2's test, for ADR-0383 §5:1's home: a story store file the previous release wrote.

``tests/memory/legacy/stories-before-adr-0383.db`` was written by the previous release's
own ``SqliteStoryStore`` (the build at ``3741e3773``, at schema version 6), through its
public API and never by hand-built SQL, with invented data: a camping trip that
understanding started and planning linked into, with a note by planning, a note by the
owner and a summary; a quiet weekend the owner started, with a note of its own, which the
matters pass merged into the trip; a story split off the trip, carrying planning's note;
a larger story planning started holding the trip; and a story never summarised. Beside
it, ``stories-before-adr-0383.json`` is what that build read back from the file, written
by that code too.

No story that build wrote holds a home, which every story this build writes does
(ADR-0386 §2:1), so the label moves. The head opens a copy and upgrades it in place:
never refuse it (ADR-0326 §5:1), drop nothing (§4:4), read back every record as that
release did, and write the owner's domain into every story the file holds, whoever its
members' works were for (ADR-0383 §5:1), moving no other byte. A note, a summary, a
version and a log line take their story's home and gain none of their own (§3:2).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    RecordHome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
)
from ai_assistant.memory import SqliteStoryStore

pytestmark = pytest.mark.integration

_LEGACY: Final = Path(__file__).parent / "legacy"
_FIXTURE: Final = _LEGACY / "stories-before-adr-0383.db"
_READ_BACK: Final = _LEGACY / "stories-before-adr-0383.json"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)

_TRIP: Final = "story:legacy-1"
_QUIET: Final = "story:legacy-2"
_SPLIT: Final = "story:legacy-3"
_LARGER: Final = "story:legacy-4"
_NEVER: Final = "story:legacy-5"
_STORIES: Final = (_TRIP, _QUIET, _SPLIT, _LARGER, _NEVER)

#: Every member whose stories that build read back.
_MEMBERS: Final = ("act-1", "act-2", "act-3", "act-4", "act-6")

#: The columns the upgrade adds to the stories' rows, and no other table's.
_HOME_COLUMNS: Final = ("home_kind", "home_id")
_OWNERS: Final = (RecordHome.owners().kind.value, RecordHome.owners().id)


def _act(activation: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _tables(path: Path) -> dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]]:
    """Every table's columns and rows, in rowid order, read out of band."""
    with sqlite3.connect(path) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        held: dict[str, tuple[tuple[str, ...], list[tuple[Any, ...]]]] = {}
        for name in names:
            cursor = conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')  # noqa: S608 — names read from the file's own catalogue
            columns = tuple(one[0] for one in cursor.description)
            held[name] = (columns, cursor.fetchall())
    return held


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "stories.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _open(path: Path) -> SqliteStoryStore:
    return SqliteStoryStore(path=path, now=lambda: _NOW, new_id=lambda: "head-1")


def _homeless(value: Any) -> Any:
    """``value`` with each story header's home taken out, each held to be the owner's."""
    if isinstance(value, dict):
        if {"story_id", "created_at", "merged_into"} <= value.keys():
            assert value.get("home") == RecordHome.owners().model_dump(mode="json"), value
            value = {key: one for key, one in value.items() if key != "home"}
        return {key: _homeless(one) for key, one in value.items()}
    if isinstance(value, list):
        return [_homeless(one) for one in value]
    return value


async def _read_back(path: Path) -> dict[str, Any]:
    """Every record the previous release read back, read the same way by the head."""
    store = _open(path)
    try:
        read: dict[str, Any] = {}
        page = await store.stories(limit=MAX_STORY_PAGE)
        for header in page.stories:
            story = header.story_id
            reads = {
                "story": header,
                "view": await store.view(story, limit=MAX_STORY_PAGE),
                "log": await store.log(story, limit=MAX_STORY_PAGE),
                "notes": await store.notes(story, limit=MAX_STORY_PAGE),
                "summaries": await store.summary_versions(story, limit=MAX_STORY_PAGE),
                "summary": await store.current_summary(story),
            }
            for name, value in reads.items():
                assert value is not None
                read[f"{name}/{story}"] = value.model_dump(mode="json")
            for member in _MEMBERS:
                read[f"stories_of/{member}"] = [
                    one.model_dump(mode="json") for one in await store.stories_of(_act(member))
                ]
        read["position"] = await store.position()
        return read
    finally:
        store.close()


def test_the_fixture_is_the_previous_releases_file() -> None:
    """The file is at the previous label, and no story in it holds a home."""
    assert _label(_FIXTURE) == 6
    columns, rows = _tables(_FIXTURE)["stories"]
    assert not set(_HOME_COLUMNS) & set(columns)
    assert sorted(row[0] for row in rows) == sorted(_STORIES)
    merged = {row[0]: row[3] for row in rows}
    assert merged[_QUIET] == _TRIP


async def test_every_record_reads_back_as_the_previous_release_read_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4: nothing dropped, and every header now the owner's."""
    head = await _read_back(legacy)

    assert _label(legacy) == 7
    assert _homeless(head) == json.loads(_READ_BACK.read_text())


async def test_every_story_takes_the_owners_domain(legacy: Path) -> None:
    """ADR-0383 §5:1: every story, merged, split off or never summarised, is the owner's."""
    store = _open(legacy)
    try:
        for story in _STORIES:
            header = await store.header(story)
            assert header is not None
            assert header.home == RecordHome.owners(), story
    finally:
        store.close()


async def test_the_upgrade_writes_the_home_and_moves_nothing_else(legacy: Path) -> None:
    """ADR-0326 §4:4: only the stories' rows change, each gaining the owner's domain."""
    before = _tables(legacy)
    store = _open(legacy)
    store.close()
    after = _tables(legacy)

    assert set(after) == set(before)
    for name, (columns, rows) in before.items():
        if name == "stories":
            continue
        assert after[name] == (columns, rows), name
    columns, rows = before["stories"]
    assert after["stories"] == (
        (*columns, *_HOME_COLUMNS),
        [(*row, *_OWNERS) for row in rows],
    )


async def test_a_second_open_changes_nothing(legacy: Path) -> None:
    """ADR-0326 §4:3: the upgrade ran once, and the upgraded file is opened as it stands."""
    _open(legacy).close()
    once = _tables(legacy)
    _open(legacy).close()

    assert _tables(legacy) == once
    assert _label(legacy) == 7


async def test_writes_after_the_upgrade_carry_their_homes(legacy: Path) -> None:
    """ADR-0386 §2:2, §2:3: a create writes the home handed it; a split takes its source's."""
    store = _open(legacy)
    try:
        split = await store.split(_TRIP, [_act("act-3")], actor=StoryActor.OWNER)
        assert split.story_id == "story:head-1"
        made = await store.header(split.story_id)
        assert made is not None
        assert made.home == RecordHome.owners()
        trip = await store.header(_TRIP)
        assert trip is not None
        assert trip.home == RecordHome.owners()
    finally:
        store.close()
