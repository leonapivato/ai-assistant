"""Shared wiring for suites that drive ADR-0276's understanding stage end to end."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.orchestration.understanding import RecentEpisodes, UnderstandingStage
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore, ModelProvider

#: The composition root's three values (ADR-0276 §4, §7), restated for the suites that
#: build an engine without it; ``tests/app`` pins that the root wires these same ones.
EPISODE_LIMIT: Final = 10
EXCERPT_CHARS: Final = 2000
VERSION_LIMIT: Final = 8

#: ADR-0281's item limit and budget, restated as above; ``tests/app`` pins the root's.
RECALL_LIMIT: Final = 3
RECALL_BUDGET: Final = timedelta(seconds=2)

#: A threshold for the canonical fake, whose score is the share of the query's terms a
#: record's content holds (ADR-0281 §3: tests set their own for what they search).
FAKE_RECALL_THRESHOLD: Final = 0.5

#: The root's threshold for the vendored on-device embedder, restated for the suite that
#: recalls over it; ``tests/app`` pins that the root wires this same one.
ON_DEVICE_RECALL_THRESHOLD: Final = 0.65

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


def recall_stage(memory: MemoryStore, *, threshold: float = FAKE_RECALL_THRESHOLD) -> RecallStage:
    """The recall stage the composition root builds, over ``memory``."""
    return RecallStage(memory=memory, threshold=threshold, limit=RECALL_LIMIT, budget=RECALL_BUDGET)
