"""Verified regressions from ADR-0275 capture's first paired review."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from test_activation_writer import Wiring
from test_engine import AT, PATIENT, Harness
from test_engine_routing import _parked, _routed_harness, _seed_belief, _token

from ai_assistant.core.errors import ConversationStoreError, OversizedValueError
from ai_assistant.core.types import (
    ChannelIdentity,
    ChannelInput,
    EpisodicMemory,
    RecordedResumeTrigger,
    TextChannelPayload,
)
from ai_assistant.orchestration.activation_state import ActivationScope
from ai_assistant.orchestration.engine import DrainPhase
from ai_assistant.testing import FakeAssistantEngine, FakeConversationStore

if TYPE_CHECKING:
    from datetime import datetime

    from ai_assistant.core.types import Conversation, SpokenDelivery


class StampedThenUnknown(FakeConversationStore):
    """``record_turn`` meets a conversation deleted meanwhile, and its outcome is unknown.

    The episode is frozen by then (ADR-0286 §4), so the writer's compensation re-reads
    the conversation, finds it gone, and destroys the episode through the drain (§7:4,
    ADR-0275 §8:11).
    """

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
        delivery: SpokenDelivery | None = None,
    ) -> Conversation | None:
        await self.stamp_deleted(conversation_id)
        raise ConversationStoreError("private provider diagnostics")


async def _hold(entered: asyncio.Event, release: asyncio.Event, cancelled: asyncio.Event) -> None:
    entered.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        cancelled.set()
        raise


@pytest.mark.parametrize("stage", ["verify", "delete"])
async def test_shutdown_does_not_cancel_safety_work_already_in_its_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    wiring = Wiring(conversations=StampedThenUnknown(now=lambda: AT))
    memory = wiring.memory
    state = await wiring.state()
    assert state.conversation_id is not None
    entered, release, cancelled, closed = (asyncio.Event() for _ in range(4))
    original_get = wiring.conversations.get
    original_delete = memory.delete

    async def get(conversation_id: str) -> Conversation | None:
        if stage == "verify":
            await _hold(entered, release, cancelled)
        return await original_get(conversation_id)

    async def delete(record_id: str) -> bool:
        if stage == "delete":
            await _hold(entered, release, cancelled)
        return await original_delete(record_id)

    async def close() -> None:
        closed.set()

    monkeypatch.setattr(wiring.conversations, "get", get)
    monkeypatch.setattr(memory, "delete", delete)
    harness = Harness(closers=(close,), drain_timeout=timedelta(0))
    harness.engine._activation_coordinator._writer = wiring.writer

    async def work() -> str:
        return "answer"

    task = harness.engine._activation_task(
        ActivationScope(state), work, seam="receive", check_output=lambda _: None
    )
    async with asyncio.timeout(5):
        await entered.wait()
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
