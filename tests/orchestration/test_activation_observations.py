"""Produced replies and established links survive later processing failures."""

from __future__ import annotations

import pytest
from test_engine import PATIENT, Harness, NoStepPlanner
from test_engine_goal_association import _Asking
from test_engine_parked_reads import _ASKED, _wired

from ai_assistant.core.types import EpisodicMemory, ProcessingReason
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter


@pytest.mark.parametrize("degraded", [False, True])
async def test_composition_survives_a_later_result_construction_failure(
    monkeypatch: pytest.MonkeyPatch, degraded: bool
) -> None:
    answer = "Produced answer café.\nA complete second line."
    harness = Harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider("" if degraded else answer), streaming=FakeStreamingCompleter()
        ),
    )
    failure = RuntimeError("private late construction failure")

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(harness.engine, "_capture", fail)
    with pytest.raises(RuntimeError) as caught:
        await harness.engine.converse("hello", timeout=PATIENT)
    assert caught.value is failure
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert episode.outcome == (None if degraded else answer)
    record = episode.processing_record
    assert record is not None
    assert record.reply_degraded is degraded
    assert record.reason is (
        ProcessingReason.COMPOSITION_FAILED if degraded else ProcessingReason.INTERNAL_ERROR
    )
    assert not record.model_eligible
    assert record.links.goal_id is not None
    assert record.links.attempt_id is not None
    assert await harness.plans.get_goal(record.links.goal_id) is not None
    assert str(failure) not in episode.model_dump_json()


async def test_saved_clarification_link_survives_unexpected_composer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(planner=_Asking())

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private composer failure")

    monkeypatch.setattr(harness.engine._composing, "compose", fail)
    with pytest.raises(RuntimeError):
        await harness.engine.converse("help me arrange it", timeout=PATIENT)
    (episode,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    record = episode.processing_record
    assert record is not None
    assert record.reason is ProcessingReason.INTERNAL_ERROR
    assert record.links.question_id is not None
    question = await harness.plans.get_question(record.links.question_id)
    assert question is not None
    assert record.links.goal_id == question.goal_id
    assert record.links.attempt_id == question.attempt_id
    assert record.links.predecessor_episode_id is None


async def test_saved_read_park_link_survives_confirmation_presentation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wired = _wired()

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private confirmation failure")

    monkeypatch.setattr(wired.engine, "_read_confirmation", fail)
    with pytest.raises(RuntimeError):
        await wired.engine.converse(_ASKED, timeout=PATIENT)
    (episode,) = [r for r in await wired.memory.export() if isinstance(r, EpisodicMemory)]
    record = episode.processing_record
    assert record is not None
    assert record.reason is ProcessingReason.INTERNAL_ERROR
    assert record.links.read_park_id is not None
    assert await wired.parks.get(record.links.read_park_id) is not None
    assert record.links.predecessor_episode_id is None
