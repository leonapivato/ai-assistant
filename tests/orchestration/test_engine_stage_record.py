"""The stage record each activation kind carries, end entry included (ADR-0280 §8).

Every case wires the understanding stage as the composition root does, except the one
that says it does not, and asserts the **exact** entries of the one captured episode's
processing record — which stage ran, the rule that made it due and how it ended — and
that no entry is the M38 loop guard's ``stage_repeated``. The rules and the controller
alone are in ``test_controller.py``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from test_activation_state import _admitted
from test_engine import Harness

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

if TYPE_CHECKING:
    from ai_assistant.core.types import EpisodeProcessingRecord


_S = ControllerStage
_R = ControllerRule
_DONE = StageOutcome.DONE


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
