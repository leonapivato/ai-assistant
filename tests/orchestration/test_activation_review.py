"""Verified regressions from ADR-0275 capture's first paired review."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from test_activation_writer import CommitThenFail, Wiring
from test_engine import AT, PATIENT, Harness
from test_engine_routing import _parked, _routed_harness, _seed_belief, _token

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    EpisodicMemory,
    RecordedResumeTrigger,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import ActivationScope
from ai_assistant.orchestration.engine import DrainPhase
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from ai_assistant.core.types import Conversation


async def _hold(entered: asyncio.Event, release: asyncio.Event, cancelled: asyncio.Event) -> None:
    entered.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        cancelled.set()
        raise


@pytest.mark.parametrize("stage", ["verify", "archive"])
async def test_shutdown_does_not_cancel_safety_work_already_in_its_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    memory = CommitThenFail()
    wiring = Wiring(memory=memory)
    state = await wiring.state()
    assert state.conversation_id is not None
    entered, release, cancelled, closed = (asyncio.Event() for _ in range(4))

    async def deleted() -> None:
        assert state.conversation_id is not None
        await wiring.conversations.stamp_deleted(state.conversation_id)

    memory.after = deleted
    original_get = wiring.conversations.get
    original_discard = wiring.archive.discard

    async def get(conversation_id: str) -> Conversation | None:
        if stage == "verify":
            await _hold(entered, release, cancelled)
        return await original_get(conversation_id)

    async def discard(address: str) -> None:
        if stage == "archive":
            await _hold(entered, release, cancelled)
        await original_discard(address)

    async def close() -> None:
        closed.set()

    monkeypatch.setattr(wiring.conversations, "get", get)
    monkeypatch.setattr(wiring.archive, "discard", discard)
    harness = Harness(closers=(close,), drain_timeout=timedelta(0))
    harness.engine._activation_coordinator._writer = wiring.writer

    async def work() -> str:
        return "answer"

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    await entered.wait()
    assert len(wiring.archive.recorded) == 1
    assert len(await memory.export()) == 1
    closing = asyncio.create_task(harness.engine.aclose())
    try:
        for _ in range(10):
            await asyncio.sleep(0)
        assert harness.engine._drain_phase is DrainPhase.CANCELLED
        assert not cancelled.is_set(), "shutdown directly cancelled deletion safety work"
        assert not closed.is_set()
        assert not closing.done()
    finally:
        release.set()
        await asyncio.gather(task, closing, return_exceptions=True)
    assert await memory.export() == []
    assert wiring.archive.recorded == {}
    assert closed.is_set()


async def test_declined_routed_confirmation_preserves_the_supplied_timestamp() -> None:
    harness = _routed_harness()
    await _seed_belief(harness.memory)
    parked = await _parked(harness)
    until = AT + timedelta(days=2)
    result = await harness.engine.resume(
        _token(parked), approved=False, timeout=PATIENT, remember_recipients_until=until
    )
    assert not result.capture_degraded
    controls = [
        record
        for record in await harness.memory.export()
        if isinstance(record, EpisodicMemory)
        and record.processing_record is not None
        and isinstance(record.processing_record.trigger, RecordedResumeTrigger)
    ]
    (control,) = controls
    assert control.processing_record is not None
    assert isinstance(control.processing_record.trigger, RecordedResumeTrigger)
    assert control.processing_record.trigger.remember_recipients_until == until
    assert not control.processing_record.trigger.approved


async def test_fake_metadata_failure_does_not_bypass_the_event_output_bound() -> None:
    engine = FakeAssistantEngine(max_payload_bytes=512)
    engine.activation_id_factory = lambda: "bad"
    with pytest.raises(OversizedValueError):
        await engine.receive(
            ChannelInput(
                target=ChannelIdentity(channel_type="informational_event", instance_id="e" * 270),
                payload=TextChannelPayload(text=""),
            ),
            reply=None,
            timeout=timedelta(seconds=1),
        )
    assert await engine.episode_memory.export() == []
