"""The composition root's person model, behind its switch (ADR-0338 §10, §11:2).

With ``Settings.person_model`` off, the default, the root builds and opens no
person-model store and hands the engine no person block, so nothing of the person model
reaches a model and the data directory gains no file: every deploy stays inert until the
person model's last lane has merged (§11:2, ADR-0342 §6:3). With it on, the root opens
the store on its own file, holding the owner and the hub's seed of their zone (§2:1,
§3:7), and hands the engine the person block's assembly over it and the one memory
store, with lane 1's two bounds (§7:1, §6:1, §7:3). The file lies in the data directory
that deleting the owner's data destroys whole (ADR-0126 §1, ADR-0338 §10:5).

**Nothing here opens a socket.** Every case builds over the hashing embedder and closes
what it built.
"""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING

import pytest
from phases_composition_support import build_phased

from ai_assistant.app import build_engine
from ai_assistant.app.composition import (
    PERSON_MODEL_FILENAME,
    PROFILE_FIELD_CHARS,
    seeded_time_zone,
)
from ai_assistant.core.config import EmbedderKind, Settings, load_settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    PersonModelAct,
    PersonModelWriteKind,
    ProfileField,
)
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.orchestration.person_block import (
    KEPT_IN_MIND_CHARS,
    PLANNING_SUGGESTIONS,
    PersonBlocks,
)
from ai_assistant.service.purge import _destroy

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import PersonModel
    from ai_assistant.orchestration.engine import Engine

pytestmark = pytest.mark.anyio

_PANEL = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)


def _blocks(engine: Engine) -> PersonBlocks:
    """The person block's assembly the root built into ``engine``: a deliberate reach-in."""
    blocks = engine._person_blocks
    assert isinstance(blocks, PersonBlocks), "the switch is on, so the root wires the block"
    return blocks


def _store(engine: Engine) -> SqlitePersonModelStore:
    store = _blocks(engine)._store
    assert isinstance(store, SqlitePersonModelStore)
    return store


async def _owner(engine: Engine) -> PersonModel:
    model = await _store(engine).read(OWNER_PERSON_ID)
    assert model is not None, "the store holds the owner from its creation (§2:1)"
    return model


# --- the switch (§11:2) ---------------------------------------------------------------


async def test_with_the_switch_off_no_store_is_built_or_opened(tmp_path: Path) -> None:
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert engine._person_blocks is None, "no activation is given a person block"
        assert not (tmp_path / PERSON_MODEL_FILENAME).exists()
    finally:
        await engine.aclose()
    assert not (tmp_path / PERSON_MODEL_FILENAME).exists()


async def test_with_the_switch_on_the_store_is_wired_with_the_roots_bounds(
    tmp_path: Path,
) -> None:
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True), data_dir=tmp_path
    )
    try:
        blocks = _blocks(engine)
        assert blocks._memory is engine._memory, "the slot reads the one memory store"
        assert (blocks._budget, blocks._suggestions) == (KEPT_IN_MIND_CHARS, PLANNING_SUGGESTIONS)
        assert (KEPT_IN_MIND_CHARS, PLANNING_SUGGESTIONS) == (1600, 5)
        store = _store(engine)
        assert store._chars == PROFILE_FIELD_CHARS
        path = tmp_path / PERSON_MODEL_FILENAME
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        await engine.aclose()


async def test_the_switch_reaches_planning_only_where_it_is_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:3 where it is on; nothing of the person model where it is off (§11:2)."""
    on = build_phased(tmp_path / "on", monkeypatch, person_model=True)
    try:
        written = await _store(on.engine).set_field(
            OWNER_PERSON_ID, ProfileField.NAME, "Robin Vale", act=_PANEL
        )
        assert written.kind is PersonModelWriteKind.WRITTEN
        await on.say("hello")
        sent_on = "\n".join(
            message.content for call in on.completer.calls for message in call.messages
        )
    finally:
        await on.engine.aclose()

    off = build_phased(tmp_path / "off", monkeypatch)
    try:
        await off.say("hello")
        sent_off = "\n".join(
            message.content for call in off.completer.calls for message in call.messages
        )
    finally:
        await off.engine.aclose()

    assert "Robin Vale" in sent_on
    assert "kept_in_mind" in sent_on
    assert "kept_in_mind" not in sent_off
    assert not (tmp_path / "off" / PERSON_MODEL_FILENAME).exists()


# --- the owner and the seed (§2:1, §3:7) ------------------------------------------


async def test_the_owners_zone_is_seeded_from_a_timezone_that_was_set(tmp_path: Path) -> None:
    settings = Settings(
        embedder=EmbedderKind.HASHING, person_model=True, timezone="America/New_York"
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        model = await _owner(engine)
    finally:
        await engine.aclose()

    assert model.profile.time_zone == "America/New_York"
    [change] = model.changes
    assert (change.field, change.new, change.act) == (
        ProfileField.TIME_ZONE,
        "America/New_York",
        PersonModelAct(how=PersonActHow.SEED),
    )


async def test_an_unset_timezone_seeds_nothing(tmp_path: Path) -> None:
    """§3:7: the UTC fallback is the hub's default, never the owner's own choice."""
    settings = Settings(embedder=EmbedderKind.HASHING, person_model=True)
    assert settings.timezone == "UTC"
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        model = await _owner(engine)
    finally:
        await engine.aclose()

    assert model.profile.time_zone is None
    assert model.changes == ()


async def test_a_later_start_with_another_timezone_does_not_seed_again(tmp_path: Path) -> None:
    first = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True, timezone="Europe/Lisbon"),
        data_dir=tmp_path,
    )
    await first.aclose()

    again = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True, timezone="Asia/Tokyo"),
        data_dir=tmp_path,
    )
    try:
        model = await _owner(again)
    finally:
        await again.aclose()

    assert model.profile.time_zone == "Europe/Lisbon"
    assert len(model.changes) == 1


def test_the_seed_reads_the_variable_through_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ASSISTANT_TIMEZONE", raising=False)
    assert seeded_time_zone(load_settings()) is None

    monkeypatch.setenv("ASSISTANT_TIMEZONE", "UTC")
    assert seeded_time_zone(load_settings()) == "UTC", "a zone the owner chose, even UTC"

    monkeypatch.setenv("ASSISTANT_TIMEZONE", "Europe/Lisbon")
    assert seeded_time_zone(load_settings()) == "Europe/Lisbon"


# --- deleting the owner's data (ADR-0126 §1, §10:5) --------------------------------


async def test_deleting_the_owners_data_destroys_the_store_with_the_directory(
    tmp_path: Path,
) -> None:
    """The file lies in the data directory, which the delete destroys whole."""
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=True, timezone="Europe/Lisbon"),
        data_dir=tmp_path,
    )
    try:
        await _store(engine).set_field(OWNER_PERSON_ID, ProfileField.NAME, "Robin", act=_PANEL)
    finally:
        await engine.aclose()
    assert (tmp_path / PERSON_MODEL_FILENAME).is_file()

    survivors = _destroy(tmp_path)

    assert survivors == []
    assert list(tmp_path.iterdir()) == []  # noqa: ASYNC240 — a test's own temporary directory
