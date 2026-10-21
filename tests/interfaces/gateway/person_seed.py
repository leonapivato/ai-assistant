"""A canonical fake engine with the person model switched on, seeded for a case.

A plain module beside ``browser_drive``, for its reason: ``mypy`` refuses a second
``conftest.py`` where the test tree carries no packages. The stores and the records are
the shared suite's own (``tests/orchestration/person_model_contract.py``), so what the
gateway and the page are driven over is what the engine's contract holds the fake to.

**The belief listing is seeded beside the memory store**, from the same memories: the
canonical fake lists ``beliefs_held``, while the person model reads the memory store
its assembly is wired to, and a page that pins from the listing needs both to name one
memory.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orchestration"))

from person_model_contract import (
    PERSON_AT,
    ended,
    fact,
    field_suggestion,
    outside,
    person_model_stores,
    pin_suggestion,
)

from ai_assistant.core.types import belief_view
from ai_assistant.orchestration.person_block import PersonBlocks

if TYPE_CHECKING:
    from ai_assistant.core.types import Memory
    from ai_assistant.testing import FakeAssistantEngine, FakeMemoryStore, FakePersonModelStore

__all__ = [
    "PERSON_AT",
    "ended",
    "fact",
    "field_suggestion",
    "hold",
    "outside",
    "pin_suggestion",
    "switch_on",
]


def switch_on(
    engine: FakeAssistantEngine, *, budget_chars: int = 1600
) -> tuple[FakePersonModelStore, FakeMemoryStore]:
    """Wire ``engine``'s person model over a fresh pair of the suite's stores.

    Args:
        engine: The fake to switch on.
        budget_chars: The kept-in-mind slot's budget (ADR-0338 §6:1).

    Returns:
        The person-model store and the memory store, for the case to seed.
    """
    people, memory = person_model_stores()
    engine.episode_memory = memory
    engine.person_blocks = PersonBlocks(store=people, memory=memory, budget_chars=budget_chars)
    return people, memory


async def hold(engine: FakeAssistantEngine, memory: FakeMemoryStore, *records: Memory) -> None:
    """Hold each memory in the store and in the belief listing, as one memory.

    Args:
        engine: The fake whose listing shows them.
        memory: The store the person model reads.
        records: The memories.
    """
    for record in records:
        await memory.add(record)
        engine.beliefs_held[record.id] = belief_view(record, now=PERSON_AT, contents={})
