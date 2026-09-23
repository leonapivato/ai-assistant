"""Shared wiring for suites that drive ADR-0276's understanding stage end to end."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from ai_assistant.orchestration.understanding import RecentEpisodes, UnderstandingStage
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore, ModelProvider

#: The composition root's three values (ADR-0276 §4, §7), restated for the suites that
#: build an engine without it; ``tests/app`` pins that the root wires these same ones.
EPISODE_LIMIT: Final = 10
EXCERPT_CHARS: Final = 2000
VERSION_LIMIT: Final = 8

#: The smallest well-formed proposal: a meaning grounded in the input alone.
STATED_PROPOSAL: Final = json.dumps(
    {"meaning": "The input means what it says.", "meaning_ground": "stated"}
)


def understanding_stage(
    memory: MemoryStore, *, model: ModelProvider | None = None
) -> UnderstandingStage:
    """The stage the composition root builds, over ``memory`` and a scripted model."""
    return UnderstandingStage(
        model=model if model is not None else FakeModelProvider(reply=STATED_PROPOSAL),
        episodes=RecentEpisodes(memory=memory, limit=EPISODE_LIMIT),
        excerpt_chars=EXCERPT_CHARS,
    )
