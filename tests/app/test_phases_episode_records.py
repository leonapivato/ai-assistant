"""What a conversational activation's episode carries, through the root, on the phases.

``test_episode_retention_default`` and ``test_transcript_archive_retired`` drive these
cases through ``converse``'s admission and today's table, which the cutover retires
(ADR-0309 §2:6, §5:1). Each case here is one of them with the root's phases wired and
the activation started by a message the chat's reader takes in: the episode's expiry
follows ``episode_retention`` (ADR-0287 §1, §6), and capture, forgetting and deleting a
conversation need no transcript archive (ADR-0287 §2).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from phases_composition_support import Phased, build_phased, phased

from ai_assistant.app import composition as composition_module
from ai_assistant.orchestration.conversations import conversation_channel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from ai_assistant.core.types import EpisodicMemory

pytestmark = pytest.mark.integration

_WINDOW: Final = timedelta(days=7)
#: The file ADR-0225 §10 gave the archive, under the data directory.
_ARCHIVE_FILE: Final = "transcripts.db"


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Phased]:
    """The production root with the phases, over a fresh data directory, started."""
    built = build_phased(tmp_path, monkeypatch)
    await built.engine.start()
    try:
        yield built
    finally:
        await built.engine.aclose()


async def _captured(composed: Phased) -> EpisodicMemory:
    """One message on a new conversation, and the episode its activation recorded."""
    turn = await composed.say("hello")
    return phased(await composed.stored(turn.address))


# --- ADR-0287 §1, §6: retention -------------------------------------------------------


async def test_an_episode_written_under_the_default_settings_carries_no_expires_at(
    composed: Phased,
) -> None:
    """§1, §6: the default keeps an episode until it is forgotten."""
    assert composed.engine._conversations._retention is None, "the default, not a choice"

    episode = await _captured(composed)

    assert episode.expires_at is None


async def test_an_episode_written_under_a_finite_window_expires_that_far_after_it_occurred(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1, §6: a finite ``episode_retention`` still stamps ``occurred_at`` advanced by it."""
    composed = build_phased(tmp_path, monkeypatch, episode_retention=_WINDOW)
    await composed.engine.start()
    try:
        episode = await _captured(composed)
    finally:
        await composed.engine.aclose()

    assert episode.expires_at == episode.occurred_at + _WINDOW


# --- ADR-0287 §2: no transcript archive -------------------------------------------------


def _composes_no_archive(composed: Phased) -> None:
    """Neither the root nor any capture or deletion seam it wired holds an archive."""
    assert not hasattr(composition_module, "SqliteTranscriptArchive")
    assert not hasattr(composed.engine, "_archive")
    lifecycle = composed.engine._conversations
    assert not hasattr(lifecycle, "_archive")
    assert not hasattr(lifecycle.activation_writer, "_archive")


async def test_a_conversational_activation_leaves_no_archive_database_file(
    composed: Phased, tmp_path: Path
) -> None:
    """§2, §6: a captured conversational activation, and no archive file beside its stores."""
    await _captured(composed)

    # The listing is a synchronous read of a temporary directory this test owns.
    names = {path.name for path in tmp_path.iterdir()}  # noqa: ASYNC240
    assert "memory.db" in names, "the data directory is the one the activation wrote into"
    assert not any(name.startswith(_ARCHIVE_FILE) for name in names), sorted(names)
    _composes_no_archive(composed)


async def test_forgetting_an_episode_succeeds_with_no_archive_composed(composed: Phased) -> None:
    """§2, §4, §6: ``forget`` deletes the episode, and that is the whole of it."""
    address = (await composed.say("forget this one")).address
    _composes_no_archive(composed)

    assert await composed.engine.forget(address) is True

    assert await composed.stored(address) is None
    assert await composed.engine.forget(address) is False, "nothing is left at the id"


async def test_deleting_a_conversation_succeeds_with_no_archive_composed(composed: Phased) -> None:
    """§2, §4, §6: forgetting and deleting need no archive (ADR-0293 §2:3, §2:4)."""
    first = await composed.say("hello")
    await composed.say("and again", first.conversation_id)
    channel = conversation_channel(first.conversation_id)
    assert len(await composed.memory.channel_episode_ids(channel, limit=10)) == 2
    _composes_no_archive(composed)

    assert await composed.engine.forget_conversation(first.conversation_id) is True

    assert await composed.memory.channel_episode_ids(channel, limit=10) == ()
    assert await composed.engine.conversation(first.conversation_id) is not None
    assert await composed.engine.delete_conversation(first.conversation_id) is True
    assert await composed.engine.conversation(first.conversation_id) is None
