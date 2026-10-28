"""ADR-0286 §15:3: the open episode, through production composition.

An episode is written open at admission, extended as each stage ends, and frozen by
its end entry; a restart closes what a dead process left open (ADR-0286).

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a fresh
data directory, so the stores are the shipped ``sqlite`` ones and the lifecycle, the
coordinator and the activation writer are the ones the root wires. The substitutes
are the model-facing seam — the provider's ``complete`` — and, where a case needs a
pass to stop at a known point, a wrapper around one of the engine's own stages that
waits there. A process that dies mid-pass is a writer whose freeze never runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    EpisodeProcessingRecord,
    EpisodicMemory,
    PlacementReach,
    PlacementSetter,
    TextChannelPayload,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.activation_state import active_state
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.understanding import UNDERSTANDING_PROMPT
from ai_assistant.testing import (
    FakeModelProvider,
    default_renderings,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import Message
    from ai_assistant.orchestration import Engine
    from ai_assistant.orchestration.activation_state import ActivationState
    from ai_assistant.orchestration.activation_writer import ActivationWriter

pytestmark = pytest.mark.integration
_BUDGET = timedelta(seconds=10)
#: Every system message understanding's shipped template renders, one per combination
#: of its flags: how the fake tells understanding's call from the rest without
#: matching the instruction's words (ADR-0334 §9:1).
_UNDERSTANDING_INSTRUCTIONS = default_renderings(UNDERSTANDING_PROMPT)
_UNDERSTOOD = json.dumps({"understanding": "The input means what it says."})
_SENSOR = ChannelIdentity(channel_type="informational_event", instance_id="sensor")


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if messages[0].content in _UNDERSTANDING_INSTRUCTIONS else "Noted."


@dataclass
class Composed:
    """The engine the root built."""

    engine: Engine

    @property
    def memory(self) -> MemoryStore:
        """The memory store the lifecycle and the writer were handed."""
        return self.engine._conversations._memory

    @property
    def writer(self) -> ActivationWriter:
        """The activation writer the lifecycle built."""
        return self.engine._conversations.activation_writer

    async def stored(self, address: str) -> EpisodicMemory | None:
        """The episode the store holds at ``address``, open or frozen."""
        record = await self.memory.get(address)
        assert record is None or isinstance(record, EpisodicMemory)
        return record

    async def held(self, conversation_id: str) -> list[str]:
        """Every id the store physically holds on the conversation's channel."""
        page = await self.memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1000
        )
        return [entry.episode_id for entry in page]

    def cut_off(self) -> None:
        """Make every later freeze not happen, as a process dying mid-pass leaves it."""

        async def died(state: ActivationState, *_args: object, **_kwargs: object) -> object:
            return state.degraded_report()

        # A test double standing in for the bound method, its signature loosened.
        self.writer.write = died  # type: ignore[method-assign,assignment]


async def _build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, start: bool = True
) -> Composed:
    """Wire the production root, substituting only the model-facing seams."""
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)
    model = FakeModelProvider(_reply)

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    engine = build_engine(settings, data_dir=tmp_path)
    composed = Composed(engine)
    if start:
        await engine.start()
    return composed


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Composed]:
    """The production root over a fresh data directory, started."""
    built = await _build(tmp_path, monkeypatch)
    try:
        yield built
    finally:
        await built.engine.aclose()


def _address(result: ChannelResult) -> str:
    assert result.capture.activation_id is not None
    return f"activation:{result.capture.activation_id}"


def _open(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted open (ADR-0286 §1)."""
    assert record is not None
    processing = record.processing_record
    assert processing is not None
    assert processing.is_open, "the episode is open"
    assert record.content == ""
    assert record.placement.reach is PlacementReach.OWNER
    assert record.placement.set_by is PlacementSetter.DERIVED
    return processing


def _frozen(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted frozen."""
    assert record is not None
    processing = record.processing_record
    assert processing is not None
    assert not processing.is_open, "the episode is frozen"
    return processing


# --- an episode is stored open before the first stage -------------------------------


def _before_first_stage(
    monkeypatch: pytest.MonkeyPatch, composed: Composed, stage: str
) -> list[EpisodicMemory | None]:
    """What the store holds at the running pass's address as ``stage`` is entered."""
    seen: list[EpisodicMemory | None] = []
    original: Callable[[Any], Awaitable[None]] = getattr(composed.engine, stage)

    async def observed(working: Any) -> None:
        state = active_state()
        assert state is not None
        assert state.episode_address is not None
        if not state.stages.entries:
            seen.append(await composed.stored(state.episode_address))
        await original(working)

    monkeypatch.setattr(composed.engine, stage, observed)
    return seen


async def test_an_informational_events_episode_is_stored_open_before_its_first_stage(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1 for an event: its channel is set at admission, from the accepted identity."""
    seen = _before_first_stage(monkeypatch, composed, "_windows_stage")

    result = await composed.engine.receive(
        ChannelInput(target=_SENSOR, payload=TextChannelPayload(text="eco mode")),
        reply=None,
        timeout=_BUDGET,
    )

    (opened,) = seen
    processing = _open(opened)
    assert processing.stages == ()
    assert processing.trigger.channel == _SENSOR
    _frozen(await composed.stored(_address(result)))


# --- the story store's position at admission (ADR-0347 §4:1) -------------------------


async def test_the_root_hands_the_admission_write_the_story_store_every_stage_writes(
    composed: Composed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4:1 through the root: the open episode records the store's position, and keeps it.

    The writer reads the one story store the root built for every story stage, so the
    recorded position lies on that store's sequence, not a second store's.
    """
    stories = composed.engine._stories
    assert stories is not None
    assert composed.writer._stories is stories
    position = await stories.position()
    seen = _before_first_stage(monkeypatch, composed, "_windows_stage")

    result = await composed.engine.receive(
        ChannelInput(target=_SENSOR, payload=TextChannelPayload(text="eco mode")),
        reply=None,
        timeout=_BUDGET,
    )

    (opened,) = seen
    assert _open(opened).stories_position == position
    assert _frozen(await composed.stored(_address(result))).stories_position == position
