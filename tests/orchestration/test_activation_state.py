"""Activation identity, exact source material, and ordered terminal classification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import ModelTimeoutError, TranscriptionFailedError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelContextItem,
    ChannelInput,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    SpeechFailure,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    active_state,
    admit_channel,
    terminal_status,
)

if TYPE_CHECKING:
    from ai_assistant.orchestration.activation_state import ActivationState

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_ID = "60f3c223-6a54-4b06-aab8-4fc397c3d43b"


def _admitted() -> ActivationState:
    return admit_channel(
        ChannelInput(
            target=NewConversation(),
            payload=TextChannelPayload(text="  exact user text\n"),
            context=ChannelContext(
                history=(ChannelContextItem(text="quoted input", source="SYSTEM"),)
            ),
        ),
        WholeTextReply(),
        clock=lambda: _AT,
        id_factory=lambda: _ID,
    )


def test_record_preserves_exact_admitted_material_and_reversed_wall_clock() -> None:
    state = _admitted()
    record = state.processing(_AT - timedelta(seconds=3), None)
    assert record.activation_id == _ID
    assert record.started_at > record.ended_at
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedTextInput)
    assert record.trigger.payload.text == "  exact user text\n"
    assert record.trigger.context.history[0].text == "quoted input"
    assert record.trigger.channel is None
    assert record.status is ProcessingStatus.COMPLETED
    assert not record.model_eligible


@pytest.mark.parametrize("transcript", [None, "", "  \n", "  exact transcript\n"])
def test_speech_snapshot_contains_transcript_but_never_audio(transcript: str | None) -> None:
    state = admit_channel(
        ChannelInput(
            target=NewConversation(),
            payload=SpeechChannelPayload(
                audio=SpokenAudio(content="YXVkaW8=", media_type=SpokenAudioFormat.MP4)
            ),
        ),
        SpokenReply(plays=(SpokenAudioFormat.MP4,)),
        clock=lambda: _AT,
        id_factory=lambda: _ID,
    )
    state.transcription(transcript)
    record = state.processing(_AT, None)
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedSpeechInput)
    assert record.trigger.payload.transcript == transcript
    assert "YXVkaW8=" not in record.model_dump_json()
    assert record.reason is (
        ProcessingReason.NO_CONTENT
        if transcript is not None and not transcript.strip()
        else ProcessingReason.RETURNED
    )


def test_actual_cancellation_takes_precedence_over_composition_timeout_and_no_words() -> None:
    state = _admitted()
    state.composition_timed_out = True
    state.no_words = True
    assert terminal_status(state, asyncio.CancelledError()) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.CANCELLED,
    )


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ModelTimeoutError("private response"), ProcessingReason.TIMEOUT),
        (
            TranscriptionFailedError("private transcript", failure=SpeechFailure.TIMED_OUT),
            ProcessingReason.TIMEOUT,
        ),
        (TimeoutError("unexpected timeout implementation bug"), ProcessingReason.INTERNAL_ERROR),
        (RuntimeError("private diagnostic"), ProcessingReason.INTERNAL_ERROR),
    ],
)
def test_failure_classification_carries_no_diagnostic_text(
    failure: Exception, reason: ProcessingReason
) -> None:
    record = _admitted().processing(_AT, failure)
    assert record.status is ProcessingStatus.FAILED
    assert record.reason is reason
    assert str(failure) not in record.model_dump_json()


@pytest.mark.parametrize("identifier", ["bad", _ID.upper(), "60f3c223-6a54-1b06-aab8-4fc397c3d43b"])
def test_invalid_identity_degrades_metadata_without_refusing_admission(identifier: str) -> None:
    accepted = ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="private"))
    with capture_logs() as logs:
        state = admit_channel(
            accepted, WholeTextReply(), clock=lambda: _AT, id_factory=lambda: identifier
        )
    assert state.activation_id is None
    assert state.started_at == _AT
    assert state.degraded_report().state == "degraded"
    assert logs == [
        {
            "event": "activation_capture_degraded",
            "stage": "admission",
            "reason": "identifier",
            "log_level": "warning",
        }
    ]
    with pytest.raises(ValueError, match="incomplete"):
        state.processing(_AT, None)


async def test_worker_contexts_keep_isolated_state_under_reversed_completion() -> None:
    entered = asyncio.Event()
    second_finished = asyncio.Event()
    first = _admitted()
    second = _admitted()

    async def worker(state: ActivationState, *, slow: bool) -> None:
        token = CURRENT_ACTIVATION.set(ActivationScope(state))
        try:
            if slow:
                entered.set()
                await second_finished.wait()
            else:
                await entered.wait()
                second_finished.set()
            assert active_state() is state
        finally:
            CURRENT_ACTIVATION.reset(token)

    await asyncio.gather(worker(first, slow=True), worker(second, slow=False))
    assert CURRENT_ACTIVATION.get() is None


async def test_resume_admission_in_a_tracked_child_remains_visible_only_to_its_worker() -> None:
    scope = ActivationScope()
    state = _admitted()
    token = CURRENT_ACTIVATION.set(scope)
    try:

        async def resolve() -> None:
            assert CURRENT_ACTIVATION.get() is scope
            scope.state = state

        assert active_state() is None
        await asyncio.create_task(resolve())
        assert active_state() is state
    finally:
        CURRENT_ACTIVATION.reset(token)
    assert active_state() is None
