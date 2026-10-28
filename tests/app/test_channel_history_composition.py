"""ADR-0283 §14:2 and ADR-0284 §11:2, through production composition.

A channel's history is its episodes (ADR-0283), and an episode is the experience of
processing its activation (ADR-0284): where its input came from, the verdict each
stage reached, and the search text one rule derives from the record.

Every case builds the engine with :func:`ai_assistant.app.build_engine` over a
fresh data directory, so the stores are the shipped ``sqlite`` ones, the
lifecycle and the activation writer are the ones the root wires, and the only
substitute is the model-facing seam: the provider's ``complete``. Nothing here
reaches past the engine into a store it does not hold, and the assertions read the
stores the engine itself reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from phases_composition_support import structured_through

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    EpisodicMemory,
    RecordedChannelTrigger,
    SupportHolder,
    TextChannelPayload,
    parties_are_outside,
)
from ai_assistant.models import PydanticAIProvider
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.orchestration.understanding import UNDERSTANDING_PROMPT
from ai_assistant.testing import (
    FakeModelProvider,
    default_renderings,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import Message
    from ai_assistant.orchestration import Engine

pytestmark = pytest.mark.integration
_BUDGET = timedelta(seconds=10)
#: Every system message understanding's shipped template renders, one per combination
#: of its flags: how the fake tells understanding's call from the rest without
#: matching the instruction's words (ADR-0334 §9:1).
_UNDERSTANDING_INSTRUCTIONS = default_renderings(UNDERSTANDING_PROMPT)
_UNDERSTOOD = json.dumps({"understanding": "The input means what it says."})


def _reply(messages: Sequence[Message]) -> str:
    """Answer the understanding stage with a stated reading, and every other stage alike."""
    return _UNDERSTOOD if messages[0].content in _UNDERSTANDING_INSTRUCTIONS else "Noted."


@dataclass
class Composed:
    """The engine the root built, and the handles its own stages hold."""

    engine: Engine
    #: The fake every model-facing call reaches, recording what each was handed.
    model: FakeModelProvider

    @property
    def memory(self) -> MemoryStore:
        """The memory store the lifecycle and the writer were handed."""
        return self.engine._conversations._memory

    @property
    def conversations(self) -> ConversationStore:
        """The conversation store the lifecycle was handed."""
        return self.engine._conversations._conversations

    async def held(self, conversation_id: str) -> list[str]:
        """Every id the store physically holds on the conversation's channel."""
        page = await self.memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1000
        )
        return [entry.episode_id for entry in page]


@pytest.fixture
async def composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Composed]:
    """Wire the production root, substituting only the model-facing seams.

    A case that needs a finite ``episode_retention`` passes it as an indirect
    parameter; every other case runs under the default, ``None`` since ADR-0287 §1.
    """
    window: timedelta | None = getattr(request, "param", None)
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING, episode_retention=window)
    model = FakeModelProvider(_reply)

    async def complete(
        _self: PydanticAIProvider, messages: Sequence[Message], *, model: str | None = None
    ) -> Message:
        return await controlled.complete(messages, model=model)

    controlled = model
    monkeypatch.setattr(PydanticAIProvider, "complete", complete)
    monkeypatch.setattr(PydanticAIProvider, "complete_structured", structured_through(complete))
    engine = build_engine(settings, data_dir=tmp_path)
    await engine.start()
    try:
        yield Composed(engine, model)
    finally:
        await engine.aclose()


# --- ADR-0284 §11:2: the experience of processing, through production composition -----

#: An informational event channel, which declares its input ``outside`` (ADR-0284 §2:2).
_SENSOR = ChannelIdentity(channel_type="informational_event", instance_id="sensor")
#: The understanding every pass in this module records, as the fake model states it.
_MEANING = "The input means what it says."
#: An event's raw text, which no episode's search text may carry (§7:1).
_REPORTED = "The thermostat entered eco mode."


async def _episode(composed: Composed, result: ChannelResult) -> EpisodicMemory:
    """The episode a pass recorded, with its processing record."""
    assert result.capture.episode_id is not None
    episode = await composed.memory.get(result.capture.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    return episode


def _parties(episode: EpisodicMemory) -> tuple[SupportHolder, ...] | None:
    """The parties the episode's trigger recorded (ADR-0351 §2:1)."""
    assert episode.processing_record is not None
    trigger = episode.processing_record.trigger
    assert isinstance(trigger, RecordedChannelTrigger)
    return trigger.parties


async def _event(composed: Composed) -> ChannelResult:
    """One informational event, admitted and processed by the root's own stages."""
    return await composed.engine.receive(
        ChannelInput(target=_SENSOR, payload=TextChannelPayload(text=_REPORTED)),
        reply=None,
        timeout=_BUDGET,
    )


async def test_an_event_episode_is_outside_and_its_content_the_meaning_alone(
    composed: Composed,
) -> None:
    """ADR-0284 §2:2 and §7:1: admission records outside parties; the words are not content."""
    episode = await _episode(composed, await _event(composed))

    assert parties_are_outside(_parties(episode))
    assert episode.content == _MEANING
    assert _REPORTED not in episode.content
