"""The episode a test memory's support points into, for the orchestration tests.

A memory writer refuses a proposal whose supports point at an episode its store does
not hold (ADR-0328 §4:7), so a test that writes a memory through a writer seeds the
episode first. :data:`~ai_assistant.testing.memories.HELD_EPISODE` is the id every
builder in :mod:`ai_assistant.testing.memories` points at unless told otherwise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.types import EpisodicMemory, MemorySource, Provenance
from ai_assistant.testing.memories import AT, HELD_EPISODE

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["held_episode"]


def held_episode(
    episode_id: str = HELD_EPISODE,
    *,
    at: datetime = AT,
    content: str = "an exchange a memory rests on",
) -> EpisodicMemory:
    """A bare episode at ``episode_id``, occurring at ``at``.

    Args:
        episode_id: The episode's id, as a support's part names it.
        at: When it occurred.
        content: Its content.

    Returns:
        The episode.
    """
    return EpisodicMemory(
        id=episode_id,
        content=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=at),
        occurred_at=at,
    )
