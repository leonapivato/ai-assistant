"""The stage record each activation kind carries, end entry included (ADR-0280 §8).

Every case wires the understanding stage as the composition root does, except the one
that says it does not, and asserts the **exact** entries of the one captured episode's
processing record — which stage ran, the rule that made it due and how it ended — and
that no entry is the M38 loop guard's ``stage_repeated``. The rules and the controller
alone are in ``test_controller.py``.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from test_activation_state import _admitted
from test_engine import AT, Harness, NoStepPlanner
from understanding_support import STATED_PROPOSAL, recall_stage, understanding_stage

from ai_assistant.core.errors import ModelTimeoutError
from ai_assistant.core.types import (
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    NewConversation,
    StageOutcome,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import ActivationScope
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodeProcessingRecord


_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE


def _harness(**knobs: Any) -> Harness:
    memory = knobs.pop("memory", None) or FakeMemoryStore(now=lambda: AT)
    knobs.setdefault(
        "composing",
        ComposingStage(model=FakeModelProvider("Yes."), streaming=FakeStreamingCompleter()),
    )
    understanding = knobs.pop("understanding_model", FakeModelProvider(STATED_PROPOSAL))
    knobs.setdefault("recall", recall_stage(memory))
    return Harness(memory=memory, understanding=understanding_stage(model=understanding), **knobs)


def _text(text: str = "book the campsite") -> ChannelInput:
    return ChannelInput(target=NewConversation(), payload=TextChannelPayload(text=text))


async def _record(harness: Harness) -> EpisodeProcessingRecord:
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.processing_record is not None
    return episode.processing_record


def _stages(
    record: EpisodeProcessingRecord,
) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    """The record's entries as (stage, rule, outcome), asserting the guard never fired."""
    assert all(entry.due is not ControllerRule.STAGE_REPEATED for entry in record.stages)
    assert record.stages_elided == 0
    end = record.stages[-1]
    assert end.started_at == end.ended_at
    return [(entry.stage, entry.due, entry.outcome) for entry in record.stages]


async def _entries(harness: Harness) -> list[tuple[ControllerStage, ControllerRule, StageOutcome]]:
    return _stages(await _record(harness))


# --- typed turns --------------------------------------------------------------------


async def test_a_history_read_outlasting_the_deadline_times_the_stage_out() -> None:
    """§5: expiry during the windows stage's history read, before recall or the
    understanding model runs (ADR-0282 §3)."""
    model = FakeModelProvider(STATED_PROPOSAL)
    harness = _harness(planner=NoStepPlanner(), understanding_model=model)

    async def hangs(conversation_id: str) -> Any:
        await asyncio.sleep(10)

    harness.engine._conversations.history = hangs  # type: ignore[method-assign]  # a read that never returns in time
    with pytest.raises(ModelTimeoutError):
        await harness.engine.converse("book the campsite", timeout=timedelta(milliseconds=50))
    assert model.calls == []
    assert await _entries(harness) == [
        (_S.BEGIN_CONVERSATION, _R.CONVERSATION_UNRESOLVED, _DONE),
        (_S.WINDOWS, _R.WINDOWS_UNASSEMBLED, StageOutcome.TIMED_OUT),
        (_S.END, _R.STAGE_TIMED_OUT, _DONE),
    ]


# --- cancellation -------------------------------------------------------------------------


async def test_a_pass_cancelled_at_the_admission_barrier_ends_interrupted() -> None:
    harness = Harness()
    state = _admitted()

    async def work() -> str:
        raise AssertionError("processing never starts")

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    episode = await harness.memory.get(f"activation:{state.activation_id}")
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert _stages(episode.processing_record) == [(_S.END, _R.INTERRUPTED, _DONE)]
