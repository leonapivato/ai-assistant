"""ADR-0326 §4:2's test, for ADR-0347 §5: a story store file the previous release wrote.

``tests/memory/legacy/stories-before-adr-0347.db`` was written by the previous release's
own ``SqliteStoryStore`` (the build at ``6668f2b65``, through its public API, at schema
version 5), never by hand-built SQL. It holds a camping trip whose summary was written
three times, the last with no line; a quiet weekend with a summary of its own, merged
into the trip; a story never summarised; and one split off the trip, carrying a note,
with a summary of its own. That release kept only each story's current summary, so the
file holds the text of four versions and none of the trip's first two.

Beside it, ``stories-before-adr-0347.json`` is what that release's
``scripts/upgrade_stores.py`` reader read back from the file, written by that code too.

The head opens a copy and must upgrade it in place: never refuse it (ADR-0326 §5:1),
drop nothing (§4:4), read back every record as that release did, and keep each story's
current summary as the text of the version that wrote it, no earlier version gaining
any (ADR-0347 §5:1).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_assistant.core.types import MAX_STORY_PAGE, StorySummaryDraft, StorySummaryLine
from ai_assistant.memory import SqliteStoryStore

pytestmark = pytest.mark.integration

_LEGACY = Path(__file__).parent / "legacy"
_FIXTURE = _LEGACY / "stories-before-adr-0347.db"
_READ_BACK = _LEGACY / "stories-before-adr-0347.json"

#: The instant the head opens the file at: a day after the previous release wrote it.
_NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)

_TRIP = "story:legacy-1"
_QUIET = "story:legacy-2"
_EMPTY = "story:legacy-3"
_SPLIT = "story:legacy-4"


def _opened(tmp_path: Path) -> tuple[Path, SqliteStoryStore]:
    path = tmp_path / "stories.db"
    shutil.copyfile(_FIXTURE, path)
    return path, SqliteStoryStore(path=path, now=lambda: _NOW)


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
    return int(version)


def _previous() -> dict[str, Any]:
    loaded = json.loads(_READ_BACK.read_text())
    assert isinstance(loaded, dict)
    return loaded


def test_the_fixture_is_the_previous_releases_file() -> None:
    assert _label(_FIXTURE) == 5
    with sqlite3.connect(_FIXTURE) as conn:
        kept = conn.execute("SELECT story_id, version FROM pages ORDER BY version").fetchall()
        versions = conn.execute(
            "SELECT story_id, version FROM versions ORDER BY version"
        ).fetchall()
    assert kept == [(_QUIET, 9), (_TRIP, 11), (_SPLIT, 17)]
    assert versions == [(_TRIP, 4), (_QUIET, 9), (_TRIP, 10), (_TRIP, 11), (_SPLIT, 17)]


async def test_every_record_the_previous_release_read_back_reads_back_the_same(
    tmp_path: Path,
) -> None:
    _, store = _opened(tmp_path)
    try:
        page = await store.stories(limit=MAX_STORY_PAGE)
        head: dict[str, Any] = {}
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
                head[f"{name}/{story}"] = value.model_dump(mode="json")
    finally:
        store.close()
    assert head == _previous()


async def test_each_current_summary_is_kept_as_its_versions_text_and_no_earlier_one_gains_any(
    tmp_path: Path,
) -> None:
    path, store = _opened(tmp_path)
    previous = _previous()
    try:
        for story in (_TRIP, _QUIET, _EMPTY, _SPLIT):
            current = previous[f"summary/{story}"]["summary"]
            versions = [one["version"] for one in previous[f"summaries/{story}"]["versions"]]
            for version in versions:
                kept = await store.summary_at(story, version)
                if current is not None and version == current["version"]:
                    assert kept is not None
                    assert kept.model_dump(mode="json") == current
                else:
                    assert kept is None, (story, version)
        trip = await store.summary_at(_TRIP, 11)
        assert trip is not None
        assert (trip.lines, trip.outside) == ((), True)
        # The merged story's summary is kept under its own id, and the trip's earlier
        # versions, whose text the previous release discarded, have none.
        quiet = await store.summary_at(_QUIET, 9)
        assert quiet is not None
        assert quiet.lines == (StorySummaryLine(text="A quiet weekend."),)
        assert await store.summary_at(_TRIP, 4) is None
        assert await store.summary_at(_TRIP, 10) is None
        assert await store.summary_at(_TRIP, 9) is None
        assert await store.position() == previous[f"summary/{_TRIP}"]["as_of"] == 17
    finally:
        store.close()
    assert _label(path) == 6
    with sqlite3.connect(path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "pages" not in tables
    assert "summaries" in tables


async def test_the_upgraded_file_keeps_every_summary_written_after_it(tmp_path: Path) -> None:
    path, store = _opened(tmp_path)
    try:
        state = await store.current_summary(_SPLIT)
        assert state is not None
        before = state.summary
        outcome = await store.write_summary(
            _SPLIT,
            StorySummaryDraft(
                lines=(StorySummaryLine(text="Sunday, then Monday."),), outside=False
            ),
            as_of=state.as_of,
        )
        assert outcome.version is not None, outcome
        assert outcome.version.version > 17
        assert await store.summary_at(_SPLIT, 17) == before
        after = await store.current_summary(_SPLIT)
        assert after is not None
        assert after.summary is not None
        assert after.summary.version == outcome.version.version
    finally:
        store.close()
    # Reopened at the new label, the file is opened as it stands, not upgraded again.
    again = SqliteStoryStore(path=path, now=lambda: _NOW)
    try:
        assert await again.summary_at(_SPLIT, 17) == before
    finally:
        again.close()
