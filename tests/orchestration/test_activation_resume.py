"""Only validated unsettled control resolutions acquire activation lifetimes."""

from __future__ import annotations

import pytest
from test_engine import PATIENT, Harness, confirmable
from test_engine_parked_reads import _ASKED, _wired

from ai_assistant.core.errors import UnknownContinuationError
from ai_assistant.core.types import (
    ContinuationToken,
    EpisodicMemory,
    ProcessingReason,
    ProcessingStatus,
    RecordedResumeTrigger,
)


@pytest.mark.parametrize("approved", [False, True])
async def test_step_resolution_records_new_control_and_replay_preserves_both(
    approved: bool,
) -> None:
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    token = parked.step.confirmation.token
    (first,) = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert first.processing_record is not None
    assert first.processing_record.status is ProcessingStatus.WAITING

    result = await harness.engine.resume(token, approved=approved, timeout=PATIENT)
    assert not result.capture_degraded
    episodes = [r for r in await harness.memory.export() if isinstance(r, EpisodicMemory)]
    assert len(episodes) == 2
    assert await harness.memory.get(first.id) == first
    resumed = next(r for r in episodes if r.id != first.id)
    processing = resumed.processing_record
    assert processing is not None
    assert processing.activation_id != first.processing_record.activation_id
    assert isinstance(processing.trigger, RecordedResumeTrigger)
    assert processing.trigger.approved is approved
    assert processing.trigger.channel is not None
    assert processing.trigger.channel.instance_id == parked.conversation_id
    assert processing.links.predecessor_episode_id == first.id
    assert processing.links.parked is not None
    assert processing.links.goal_id is not None
    assert processing.links.attempt_id is not None
    assert token.handle not in processing.model_dump_json()
    assert "send it" not in processing.model_dump_json()
    assert processing.model_eligible

    before = await harness.memory.export()
    await harness.engine.resume(token, approved=not approved, timeout=PATIENT)
    assert await harness.memory.export() == before


async def test_unknown_control_token_records_nothing() -> None:
    harness = Harness()
    with pytest.raises(UnknownContinuationError):
        await harness.engine.resume(
            ContinuationToken(handle="unknown"), approved=True, timeout=PATIENT
        )
    assert await harness.memory.export() == []


async def test_denied_read_records_inspection_only_control_without_replaying_utterance() -> None:
    wired = _wired()
    parked = await wired.engine.converse(_ASKED, timeout=PATIENT)
    assert parked.read_confirmation is not None
    token = parked.read_confirmation.token
    before = await wired.memory.export()

    result = await wired.engine.resume(token, approved=False, timeout=PATIENT)
    assert not result.capture_degraded
    assert result.reply is None
    controls = [
        r
        for r in await wired.memory.export()
        if isinstance(r, EpisodicMemory)
        and r.processing_record is not None
        and isinstance(r.processing_record.trigger, RecordedResumeTrigger)
    ]
    assert len(controls) == 1
    control = controls[0]
    processing = control.processing_record
    assert processing is not None
    assert not processing.model_eligible
    assert processing.reason is ProcessingReason.RETURNED
    assert processing.links.read_park_id is not None
    assert control.outcome is None
    assert _ASKED not in control.model_dump_json()
    for record in before:
        assert await wired.memory.get(record.id) == record
    after = await wired.memory.export()
    await wired.engine.resume(token, approved=True, timeout=PATIENT)
    assert await wired.memory.export() == after


async def test_policy_failure_after_control_admission_preserves_original_and_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(tools=(confirmable(),))
    parked = await harness.engine.converse("send it", timeout=PATIENT)
    assert parked.step is not None
    assert parked.step.confirmation is not None
    failure = RuntimeError("private resolution diagnostic")

    async def fail(*_args: object, **_kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(harness.engine._runner._policy, "resolve", fail)
    with pytest.raises(RuntimeError) as caught:
        await harness.engine.resume(parked.step.confirmation.token, approved=True, timeout=PATIENT)
    assert caught.value is failure
    controls = [
        r
        for r in await harness.memory.export()
        if isinstance(r, EpisodicMemory)
        and r.processing_record is not None
        and isinstance(r.processing_record.trigger, RecordedResumeTrigger)
    ]
    assert len(controls) == 1
    assert controls[0].processing_record is not None
    assert controls[0].processing_record.reason is ProcessingReason.INTERNAL_ERROR
    assert not controls[0].processing_record.model_eligible
    assert str(failure) not in controls[0].model_dump_json()
