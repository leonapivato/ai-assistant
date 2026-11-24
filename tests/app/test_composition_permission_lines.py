"""The composition root's line store (ADR-0367 §3:6, ADR-0376 §4:8).

The store of the lines people make is opened on every hub, on its own file in the data
directory, owner-only (ADR-0004 §4). It starts empty and no start seeds a line: a tool's
default line is its declaration's, never the store's (ADR-0376 §3:3). Nothing reads it
yet, so nothing the engine does changes, and a line written between two starts is still
there on the second.

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app.composition import PERMISSION_LINES_FILENAME
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LineMakingKind,
    LineParts,
    PermissionLineKind,
)
from ai_assistant.permissions import SqlitePermissionLineStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

_LIMIT = LineParts(
    kind=PermissionLineKind.LIMIT,
    who=OWNER_PERSON_ID,
    action="send_email",
    thing="account:conn-mail",
)


async def test_the_store_is_opened_on_every_hub_empty_and_owner_only(tmp_path: Path) -> None:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await engine.aclose()

    path = tmp_path / PERMISSION_LINES_FILENAME
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    store = SqlitePermissionLineStore(path=path)
    try:
        assert await store.standing() == ()
    finally:
        store.close()


async def test_a_line_made_between_starts_is_kept_and_none_is_seeded(tmp_path: Path) -> None:
    first = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await first.aclose()
    store = SqlitePermissionLineStore(path=tmp_path / PERMISSION_LINES_FILENAME)
    try:
        making = await store.record_making(_LIMIT, by=OWNER_PERSON_ID)
    finally:
        store.close()
    assert making.kind is LineMakingKind.MADE

    again = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await again.aclose()

    store = SqlitePermissionLineStore(path=tmp_path / PERMISSION_LINES_FILENAME)
    try:
        assert await store.standing() == (making.line,)
    finally:
        store.close()
