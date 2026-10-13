"""Verified regressions from ADR-0275 capture's first paired review."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from test_activation_writer import Wiring
from test_engine import Harness

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import ChannelIdentity, ChannelInput, TextChannelPayload
from ai_assistant.orchestration.activation_state import ActivationScope
from ai_assistant.orchestration.channels import ChannelProjection
from ai_assistant.orchestration.engine import DrainPhase
from ai_assistant.testing import FakeAssistantEngine


async def _hold(entered: asyncio.Event, release: asyncio.Event, cancelled: asyncio.Event) -> None:
    entered.set()
    try:
        await release.wait()
    except asyncio.CancelledError:
        cancelled.set()
        raise


async def test_shutdown_does_not_cancel_safety_work_already_in_its_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0275 §8:11: the drained deletion of a forgotten capture outlives shutdown.

    The user forgets the episode while its activation runs (ADR-0286 §8), so capture's
    next write deletes it through the drain; shutdown arriving while that deletion is
    held must not cancel it. Before ADR-0293 §2:7 a deleted conversation's fence was
    the other such work; deleting a conversation now forgets nothing, so forgetting is
    what is left to drain.
    """
    wiring = Wiring()
    memory = wiring.memory
    state = await wiring.state()
    assert state.conversation_id is not None
    entered, release, cancelled, closed = (asyncio.Event() for _ in range(4))
    original_delete = memory.delete

    async def delete(record_id: str) -> bool:
        await _hold(entered, release, cancelled)
        return await original_delete(record_id)

    async def close() -> None:
        closed.set()

    monkeypatch.setattr(memory, "delete", delete)
    harness = Harness(closers=(close,), drain_timeout=timedelta(0))
    harness.engine._activation_coordinator._writer = wiring.writer

    async def work() -> str:
        assert state.episode_address is not None
        wiring.writer.forgetting(state.episode_address)
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


async def test_the_fakes_unfinished_event_result_is_held_to_the_output_bound() -> None:
    """ADR-0085 §8c: the *couldn't finish* result built for an end is measured too."""
    engine = FakeAssistantEngine(max_payload_bytes=512)
    with pytest.raises(OversizedValueError, match="the result of receive"):
        await engine.receive(
            ChannelInput(
                target=ChannelIdentity(channel_type="informational_event", instance_id="e" * 250),
                payload=TextChannelPayload(text="x"),
            ),
            reply=None,
            timeout=timedelta(0),
        )


async def test_fake_metadata_failure_does_not_bypass_the_event_output_bound() -> None:
    """The fake measures an event's result against the bound with no capture to reserve.

    ADR-0313 §4:4 leaves an event's result no free text, so an input inside the bound
    can no longer carry a result past it through ``receive``; the check that would
    refuse one is held to the bound directly, and the call itself records nothing.
    """
    engine = FakeAssistantEngine(max_payload_bytes=512)
    engine.activation_id_factory = lambda: "bad"
    target = ChannelIdentity(channel_type="informational_event", instance_id="e" * 270)
    result = await engine.receive(
        ChannelInput(target=target, payload=TextChannelPayload(text="")),
        reply=None,
        timeout=timedelta(seconds=1),
    )
    assert result.capture.state == "degraded"
    assert await engine.episode_memory.export() == []
    oversized = result.model_copy(
        update={"channel": target.model_copy(update={"instance_id": "e" * 600})}
    )
    with pytest.raises(OversizedValueError):
        engine._check_channel_result(oversized, ChannelProjection("receive"))
