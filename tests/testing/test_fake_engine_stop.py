"""The canonical fake's stop, held to the engine's semantics (ADR-0297 §3-§5).

The shared suite holds the fake to the two answers that write nothing; these cases
hold the half no shared arm can reach in the fake — a stop landing on an activation it
is running — by placing the activation where its own admission puts it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from ai_assistant.core.errors import ActivationStoppedError, ChannelProcessingError
from ai_assistant.core.types import (
    ActivationStop,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.testing import FakeAssistantEngine
from ai_assistant.testing.activation import FakeActivation
from ai_assistant.testing.engine import _stopped_failure

_AT = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
_BUDGET = timedelta(seconds=10)


def _running(engine: FakeAssistantEngine) -> FakeActivation:
    """An activation the fake has admitted and not finalized, as its admission holds one."""
    activation = FakeActivation.channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
        WholeTextReply(),
        _AT,
    )
    activation.identify(engine.activation_id_factory)
    # Where the fake's own admission puts it.
    engine._running_activations.append(activation)
    return activation


async def test_a_stop_marks_a_running_activation() -> None:
    engine = FakeAssistantEngine()
    activation = _running(engine)
    assert activation.activation_id is not None

    assert await engine.stop_activation(activation.activation_id) is ActivationStop.STOPPED
    assert activation.stopped
    # A repeated stop while it still runs finds it set (§3:7).
    assert await engine.stop_activation(activation.activation_id) is ActivationStop.STOPPED


async def test_a_stop_after_the_finalization_reading_answers_already_ended() -> None:
    engine = FakeAssistantEngine()
    activation = _running(engine)
    assert activation.activation_id is not None
    activation.ended = True

    assert await engine.stop_activation(activation.activation_id) is ActivationStop.ALREADY_ENDED
    assert not activation.stopped


def test_a_marked_fake_activation_records_the_stops_classification_and_end_entry() -> None:
    activation = FakeActivation.channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
        WholeTextReply(),
        _AT,
    )
    assert activation.stop()
    for failure in (None, asyncio.CancelledError(), ChannelProcessingError("x")):
        assert activation.status(failure) == (
            ProcessingStatus.INTERRUPTED,
            ProcessingReason.STOPPED,
        )
        end = activation.stages(failure)[-1]
        assert (end.stage, end.due) == (ControllerStage.END, ControllerRule.STOPPED)


@pytest.mark.parametrize("failure", [None, ChannelProcessingError("x")])
def test_a_turn_call_awaiting_a_stopped_fake_pass_raises_the_stop(
    failure: BaseException | None,
) -> None:
    activation = FakeActivation.channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hi")),
        WholeTextReply(),
        _AT,
    )
    activation.stop()
    assert isinstance(_stopped_failure(activation, failure), ActivationStoppedError)
    cancelled = asyncio.CancelledError()
    assert _stopped_failure(activation, cancelled) is cancelled


async def test_an_unmarked_pass_is_answered_as_it_ended() -> None:
    engine = FakeAssistantEngine()
    result = await engine.receive(
        ChannelInput(
            target=NewConversation(),
            payload=SpeechChannelPayload(
                audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
            ),
        ),
        reply=SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        timeout=_BUDGET,
    )
    assert result.capture.state == "recorded"
