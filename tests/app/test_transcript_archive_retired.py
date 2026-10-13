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
from datetime import UTC, datetime
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.protocols import AssistantEngine
from ai_assistant.core.types import ActionPlan, AssociationVerdict, GoalAssociation, PlannerOutput
from ai_assistant.models import PydanticAIProvider
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
