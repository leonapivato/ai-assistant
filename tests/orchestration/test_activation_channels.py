"""Public channel calls finalize one truthful receipt after processing ends."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from channel_receiver_contract import event_input
from test_channel_receiver import ControlledModel
from test_engine import Harness, NoStepPlanner

from ai_assistant.core.errors import ChannelProcessingError, ModelError, OversizedValueError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelContextItem,
    ChannelInput,
    EpisodeResponseKind,
    EpisodicMemory,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
    TextChannelPayload,
    TextChannelResult,
    WholeTextReply,
)
from ai_assistant.orchestration.composing import ComposingStage
from ai_assistant.orchestration.informational_events import InformationalEventStage
from ai_assistant.testing import FakeModelProvider, FakeStreamingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.types import ChannelResult

_BUDGET = timedelta(seconds=10)


async def test_text_receipt_names_the_only_record_with_exact_input_context_and_response() -> None:
    text = "  exact user café\n"
    answer = "complete answer café\nsecond line"
    harness = Harness(
        planner=NoStepPlanner(),
        composing=ComposingStage(
            model=FakeModelProvider(answer), streaming=FakeStreamingCompleter()
        ),
    )
    context = ChannelContext(history=(ChannelContextItem(text="quoted", source="SYSTEM"),))
    supplied = ChannelInput(
        target=NewConversation(), payload=TextChannelPayload(text=text), context=context
    )
    result = await harness.engine.receive(supplied, reply=WholeTextReply(), timeout=_BUDGET)
    assert isinstance(result.result, TextChannelResult)
    assert result.capture.state == "recorded"
    assert not result.result.outcome.capture_degraded
    (episode,) = await harness.memory.export()
    assert isinstance(episode, EpisodicMemory)
    assert episode.id == result.capture.episode_id
    assert episode.outcome == result.result.outcome.reply == answer
    processing = episode.processing_record
    assert processing is not None
    assert processing.activation_id == result.capture.activation_id
    assert processing.status is ProcessingStatus.COMPLETED
    assert processing.model_eligible
    assert processing.response_kind is EpisodeResponseKind.CONVERSATION_REPLY
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    assert processing.trigger.target == supplied.target
    assert processing.trigger.channel == result.channel
    assert processing.trigger.context == context
    assert isinstance(processing.trigger.payload, RecordedTextInput)
    assert processing.trigger.payload.text == text


@pytest.mark.parametrize("cancelled", [False, True])
async def test_event_failure_or_cancellation_records_once_after_model_cleanup(
    cancelled: bool,
) -> None:
    model = ControlledModel()
    harness = Harness(informational_events=InformationalEventStage(model))
    task = asyncio.create_task(harness.engine.receive(event_input(), reply=None, timeout=_BUDGET))
    await model.entered.wait()
    assert await harness.memory.export() == []
    if cancelled:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        model.error = ModelError("private diagnostic")
        model.release.set()
        with pytest.raises(ChannelProcessingError):
            await task
    assert model.cleaned.is_set()
    (episode,) = await harness.memory.export()
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.status is (
        ProcessingStatus.INTERRUPTED if cancelled else ProcessingStatus.FAILED
    )
    assert episode.outcome is None
    assert not episode.processing_record.model_eligible
    assert "private diagnostic" not in episode.model_dump_json()


async def test_oversized_event_keeps_the_complete_summary_and_output_failure() -> None:
    answer = "long summary " * 100
    harness = Harness(
        informational_events=InformationalEventStage(FakeModelProvider(answer)),
        max_payload_bytes=1024,
    )
    with pytest.raises(OversizedValueError):
        await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    (episode,) = await harness.memory.export()
    assert isinstance(episode, EpisodicMemory)
    assert episode.outcome == answer
    assert episode.processing_record is not None
    assert episode.processing_record.reason is ProcessingReason.OUTPUT_OVERSIZED
    assert episode.processing_record.response_kind is EpisodeResponseKind.INFORMATIONAL_SUMMARY


async def test_invalid_activation_metadata_degrades_capture_without_losing_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(informational_events=InformationalEventStage(FakeModelProvider("summary")))
    monkeypatch.setattr(harness.engine, "_activation_id_factory", lambda: "not-a-uuid")
    result = await harness.engine.receive(event_input(), reply=None, timeout=_BUDGET)
    assert result.capture.state == "degraded"
    assert result.capture.activation_id is None
    assert result.capture.episode_id is None
    assert await harness.memory.export() == []


async def test_overlapping_events_keep_separate_identity_context_and_receipts() -> None:
    model = ControlledModel()
    harness = Harness(informational_events=InformationalEventStage(model))

    async def receive(text: str) -> ChannelResult:
        supplied = event_input().model_copy(
            update={
                "payload": TextChannelPayload(text=text),
                "context": ChannelContext(history=(ChannelContextItem(text=text),)),
            }
        )
        return await harness.engine.receive(supplied, reply=None, timeout=_BUDGET)

    first = asyncio.create_task(receive("first"))
    second = asyncio.create_task(receive("second"))
    await model.entered.wait()
    model.release.set()
    results = await asyncio.gather(first, second)
    assert len({result.capture.activation_id for result in results}) == 2
    for result, expected in zip(results, ("first", "second"), strict=True):
        assert result.capture.episode_id is not None
        episode = await harness.memory.get(result.capture.episode_id)
        assert isinstance(episode, EpisodicMemory)
        assert episode.processing_record is not None
        trigger = episode.processing_record.trigger
        assert isinstance(trigger, RecordedChannelTrigger)
        assert isinstance(trigger.payload, RecordedTextInput)
        assert trigger.payload.text == trigger.context.history[0].text == expected
