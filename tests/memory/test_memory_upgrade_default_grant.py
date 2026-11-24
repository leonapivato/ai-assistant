"""ADR-0326 §4:2's test, for ADR-0380 §3:2: episodes the release before the default grant wrote.

``tests/memory/legacy/memory-before-adr-0380.db`` was written by the previous release's
own ``SqliteMemoryStore`` (the build at ``522da83f3``, at the label ``25``), through its
public ``add`` alone, never by hand-built SQL, with an eight-dimension hashing embedder
and invented data. It holds one ended episode, ``mem-asked``, whose processing record
has one planning round asking about two calls (ADR-0321 §2:8), a ``send_email`` and a
``pin_memory``, each holding by value the declaration that build declared, which had no
default grant. No round records an asked call since ADR-0361 §8:5, but stored rounds
still hold them, which is why this store holds a ``ToolDefinition`` at all.

A declaration with no default grant leaves the field out of its dump, so the stored
episode validates unchanged: the upgrade is the empty one ADR-0326 §4's note names, and
the label stayed ``25``. The head opens a copy and reads the episode back as it was, each
asked call's declaration with no default grant (ADR-0380 §3:1), and writes the label it
writes, which a later change moved by the label alone (ADR-0379 §3:2's record of the
check).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core.types import EpisodicMemory
from ai_assistant.memory import SqliteMemoryStore
from ai_assistant.memory._episode_format import MEMORY_RECORD_FORMAT
from ai_assistant.models import HashingEmbedder
from ai_assistant.orchestration.person_calls import PIN
from ai_assistant.testing import FakeTraceSink
from ai_assistant.tools.send_email import EMAIL

pytestmark = pytest.mark.integration

_FIXTURE: Final = Path(__file__).parent / "legacy" / "memory-before-adr-0380.db"

#: The instant the head opens the file at: an hour after the previous release wrote it.
_NOW: Final = datetime(2026, 11, 24, 13, 2, tzinfo=UTC)

_EPISODE: Final = "mem-asked"


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    """A copy of the file the previous release wrote, so the fixture itself never changes."""
    target = tmp_path / "memory.db"
    shutil.copyfile(_FIXTURE, target)
    return target


def _label(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        (version,) = conn.execute("SELECT version FROM episode_record_format").fetchone()
    return int(version)


def _stored(path: Path) -> dict[str, str]:
    """Every row's stored blob, read out of band."""
    with sqlite3.connect(path) as conn:
        return {str(one): str(data) for one, data in conn.execute("SELECT id, data FROM records")}


def _open(path: Path) -> SqliteMemoryStore:
    return SqliteMemoryStore(
        traces_sink=FakeTraceSink(),
        path=path,
        embedder=HashingEmbedder(dimensions=8),
        now=lambda: _NOW,
    )


def test_the_fixture_is_the_previous_releases_file() -> None:
    """Labelled 25, the one episode, two asked calls, and no declaration with a grant."""
    assert _label(_FIXTURE) == 25
    stored = _stored(_FIXTURE)
    assert list(stored) == [_EPISODE]
    (round_,) = json.loads(stored[_EPISODE])["processing_record"]["rounds"]
    assert [one["tool"]["capability"] for one in round_["asked"]] == ["send_email", "pin_memory"]
    assert '"default_grant"' not in stored[_EPISODE]


async def test_the_episode_reads_back_as_the_previous_release_wrote_it(legacy: Path) -> None:
    """ADR-0326 §4:2, §4:4, ADR-0380 §3:1: whole, each asked declaration with no grant."""
    store = _open(legacy)
    try:
        exported = {record.id: record for record in await store.export()}
        fetched = await store.get(_EPISODE)
    finally:
        store.close()

    assert list(exported) == [_EPISODE]
    episode = exported[_EPISODE]
    assert isinstance(episode, EpisodicMemory)
    assert fetched == episode
    assert episode.processing_record is not None
    (round_,) = episode.processing_record.rounds
    assert [one.tool.default_grant for one in round_.asked] == [None, None]
    for asked, current in zip(round_.asked, (EMAIL, PIN), strict=True):
        assert asked.tool == current.model_copy(update={"default_grant": None})
    assert episode.model_dump_json(exclude={"revision"}) == _stored(legacy)[_EPISODE]
    assert _label(legacy) == MEMORY_RECORD_FORMAT
