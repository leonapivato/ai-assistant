"""ADR-0287 §6's lane 2 tests, through production composition.

The transcript archive is retired (ADR-0287 §2): no capture writes an entry, no forget
or conversation deletion discards one, and the composition root builds no archive and
gives no data directory an archive database file. The seven ``AssistantEngine``
members that read and destroyed it are gone, and with them their wire operations
(§3).

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a fresh
data directory, so the stores, the lifecycle and the activation writer are the ones
the root wires. Only the model-facing seams are substituted: the provider's
``complete``, the planner, the associator and the streaming completer.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import (
    ActionPlan,
    AssociationVerdict,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    GoalAssociation,
    NewConversation,
    PlannerOutput,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing import (
    FakeGoalAssociator,
    FakeModelProvider,
    FakeStreamingCompleter,
    StreamAttempt,
)
from ai_assistant.wire import surface

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.types import GoalBrief, Message
    from ai_assistant.orchestration import Engine

pytestmark = pytest.mark.integration

_BUDGET: Final = timedelta(seconds=10)
_AT: Final = datetime(2026, 10, 4, tzinfo=UTC)
_UNDERSTANDING_PROMPT: Final = "You read one incoming input and state what it means."
_UNDERSTOOD: Final = json.dumps(
    {"meaning": "The input means what it says.", "meaning_ground": "stated"}
)

#: The seven members ADR-0287 §3 removes, by name.
_RETIRED: Final = frozenset(
    {
        "transcript_search",
        "transcript_conversation",
        "transcript_entry",
        "transcript_entries",
        "forget_transcript_entry",
        "forget_transcript_conversation",
        "transcript_archive_size",
    }
)

#: The file ADR-0225 §10 gave the archive, under the data directory.
_ARCHIVE_FILE: Final = "transcripts.db"


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if _UNDERSTANDING_PROMPT in messages[0].content else "Noted."


@pytest.fixture
async def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Engine]:
    """Wire the production root, substituting only the model-facing seams."""
    model = FakeModelProvider(_reply)

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    built = build_engine(
        Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING), data_dir=tmp_path
    )
    built._associator = FakeGoalAssociator(answer=GoalAssociation(verdict=AssociationVerdict.FRESH))
    built._routing = None
    built._composing._streaming = FakeStreamingCompleter(
        script=tuple(StreamAttempt(deltas=("Channel reply.",)) for _ in range(8))
    )

    plan_ids = count(1)

    async def plan(goal: GoalBrief, **_kwargs: object) -> PlannerOutput:
        return PlannerOutput(
            plan=ActionPlan(
                id=f"retired-plan-{next(plan_ids)}", goal_id=goal.goal_id, steps=(), created_at=_AT
            )
        )

    monkeypatch.setattr(built._loop._planner, "plan", plan)
    await built.start()
    try:
        yield built
    finally:
        await built.aclose()


async def _say(engine: Engine, text: str, conversation_id: str | None = None) -> ChannelResult:
    """One text activation on a new conversation, or on the one named."""
    target = (
        NewConversation()
        if conversation_id is None
        else ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
    )
    return await engine.receive(
        ChannelInput(target=target, payload=TextChannelPayload(text=text)),
        reply=WholeTextReply(),
        timeout=_BUDGET,
    )


def _composes_no_archive(engine: Engine) -> None:
    """Neither the root nor any capture or deletion seam it wired holds an archive."""
    assert not hasattr(composition_module, "SqliteTranscriptArchive")
    assert not hasattr(engine, "_archive")
    lifecycle = engine._conversations
    assert not hasattr(lifecycle, "_archive")
    assert not hasattr(lifecycle.activation_writer, "_archive")


async def test_a_conversational_turn_leaves_no_archive_database_file(
    engine: Engine, tmp_path: Path
) -> None:
    """§2, §6: a captured conversational turn, and no archive file beside its stores."""
    result = await _say(engine, "hello")

    assert result.capture.state == "recorded"
    assert result.capture.episode_id is not None
    assert await engine._conversations._memory.get(result.capture.episode_id) is not None
    # The listing is a synchronous read of a temporary directory this test owns.
    names = {path.name for path in tmp_path.iterdir()}  # noqa: ASYNC240
    assert "memory.db" in names, "the data directory is the one the turn wrote into"
    assert not any(name.startswith(_ARCHIVE_FILE) for name in names), sorted(names)
    _composes_no_archive(engine)


async def test_forgetting_an_episode_succeeds_with_no_archive_composed(engine: Engine) -> None:
    """§2, §4, §6: ``forget`` deletes the episode, and that is the whole of it."""
    result = await _say(engine, "forget this one")
    address = result.capture.episode_id
    assert address is not None
    _composes_no_archive(engine)

    assert await engine.forget(address) is True

    assert await engine._conversations._memory.get(address) is None
    assert await engine.forget(address) is False, "nothing is left at the id"


async def test_deleting_a_conversation_succeeds_with_no_archive_composed(engine: Engine) -> None:
    """§2, §4, §6: deletion stamps, deletes the channel's episodes, and needs no archive."""
    result = await _say(engine, "hello")
    assert result.channel is not None
    conversation_id = result.channel.instance_id
    await _say(engine, "and again", conversation_id)
    memory = engine._conversations._memory
    channel = conversation_channel(conversation_id)
    assert len(await memory.channel_episode_ids(channel, limit=10)) == 2
    _composes_no_archive(engine)

    assert await engine.forget_conversation(conversation_id) is True

    assert await memory.channel_episode_ids(channel, limit=10) == ()
    assert await engine.conversation(conversation_id) is None


async def test_the_wire_surface_carries_none_of_the_retired_operations(engine: Engine) -> None:
    """§3, §6: ``wire.surface.METHODS`` carries none of the seven, nor does the engine.

    ``METHODS`` is derived from ``AssistantEngine``, so the Protocol, the derived set
    and the engine the root built are asserted together: a member left on any one of
    them would be an operation some peer could still name.
    """
    assert surface.METHODS, "the derived set is not empty, so the absence means something"
    assert not _RETIRED & surface.METHODS
    assert not any(hasattr(AssistantEngine, name) for name in _RETIRED)
    assert not any(hasattr(engine, name) for name in _RETIRED)
