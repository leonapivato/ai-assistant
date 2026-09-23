"""Activation identity, exact source material, and ordered terminal classification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import (
    ChannelProcessingError,
    ModelError,
    ModelTimeoutError,
    OversizedValueError,
    TranscriptionFailedError,
    UnderstandingError,
)
from ai_assistant.core.types import (
    ActivationUnderstanding,
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
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    active_state,
    admit_channel,
    admit_resume,
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


# --- ADR-0276 §5 and §7: the understanding the carrier accumulates -------------------


def _version(version: int) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=f"reading {version}",
        meaning_ground=UnderstandingGround.STATED,
    )


def test_one_version_is_captured_with_no_omission() -> None:
    state = _admitted()
    assert state.next_understanding_version() == 1
    state.understood(_version(1), limit=8)
    record = state.processing(_AT, None)
    assert [u.version for u in record.understanding] == [1]
    assert record.understanding_omitted is None
    assert record.understanding_elided == 0


def test_the_history_keeps_version_one_and_the_latest_and_counts_what_it_elides() -> None:
    """§7: ten versions at a bound of eight keep 1 and 4 to 10, and record two elided."""
    state = _admitted()
    for version in range(1, 11):
        state.understood(_version(state.next_understanding_version()), limit=8)
        assert state.understanding[-1].version == version
        assert state.understanding[0].version == 1
    record = state.processing(_AT, None)
    assert [u.version for u in record.understanding] == [1, 4, 5, 6, 7, 8, 9, 10]
    assert record.understanding_elided == 2


def test_a_version_out_of_sequence_is_refused() -> None:
    state = _admitted()
    with pytest.raises(ValueError, match="one greater"):
        state.understood(_version(2), limit=8)
    state.understood(_version(1), limit=8)
    with pytest.raises(ValueError, match="one greater"):
        state.understood(_version(1), limit=8)


def test_a_bound_below_two_is_refused() -> None:
    with pytest.raises(ValueError, match="version 1 and the latest"):
        _admitted().understood(_version(1), limit=1)


def test_a_pass_that_ends_ahead_of_the_stage_records_not_reached() -> None:
    record = _admitted().processing(_AT, RuntimeError("before the stage"))
    assert record.understanding == ()
    assert record.understanding_omitted is UnderstandingOmission.NOT_REACHED


def test_the_first_branch_taken_is_the_one_recorded() -> None:
    state = _admitted()
    state.omit(UnderstandingOmission.ROUTED)
    state.omit(UnderstandingOmission.FAILED)
    assert state.processing(_AT, None).understanding_omitted is UnderstandingOmission.ROUTED


def test_a_recorded_version_outranks_a_later_failure() -> None:
    """A pass that recorded a version records no omission, whatever ended it."""
    state = _admitted()
    state.understood(_version(1), limit=8)
    state.understanding_failed(ModelError("later"))
    record = state.processing(_AT, ModelError("later"))
    assert record.understanding_omitted is None
    assert record.reason is ProcessingReason.PROCESSING_FAILED


def test_a_resume_records_no_input() -> None:
    state = admit_resume(
        approved=True, remember_recipients_until=None, clock=lambda: _AT, id_factory=lambda: _ID
    )
    assert state.processing(_AT, None).understanding_omitted is UnderstandingOmission.NO_INPUT


@pytest.mark.parametrize("transcript", [None, "", " \n"])
def test_speech_without_words_records_no_text(transcript: str | None) -> None:
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
    assert state.processing(_AT, None).understanding_omitted is UnderstandingOmission.NO_TEXT


def test_an_understanding_error_is_its_own_terminal_reason_and_carries_no_text() -> None:
    """§6: below transcription failure, above output oversize."""
    state = _admitted()
    failure = UnderstandingError("private output")
    state.understanding_failed(failure)
    record = state.processing(_AT, failure)
    assert (record.status, record.reason) == (
        ProcessingStatus.FAILED,
        ProcessingReason.UNDERSTANDING_FAILED,
    )
    assert record.understanding_omitted is UnderstandingOmission.FAILED
    assert "private output" not in record.model_dump_json()
    transcription = TranscriptionFailedError("t", failure=SpeechFailure.UNCLASSIFIED)
    assert terminal_status(state, transcription)[1] is ProcessingReason.TRANSCRIPTION_FAILED
    assert terminal_status(_admitted(), OversizedValueError("o", limit=1, size=2))[1] is (
        ProcessingReason.OUTPUT_OVERSIZED
    )
    assert terminal_status(state, OversizedValueError("o", limit=1, size=2))[1] is (
        ProcessingReason.UNDERSTANDING_FAILED
    )


def test_the_reason_survives_the_event_paths_outward_mapping() -> None:
    """The event path raises `ChannelProcessingError`; the record still says why."""
    state = _admitted()
    state.understanding_failed(UnderstandingError("x"))
    assert terminal_status(state, ChannelProcessingError("mapped"))[1] is (
        ProcessingReason.UNDERSTANDING_FAILED
    )
    other = _admitted()
    other.understanding_failed(ModelError("x"))
    assert terminal_status(other, ChannelProcessingError("mapped"))[1] is not (
        ProcessingReason.UNDERSTANDING_FAILED
    )
    assert other.processing(_AT, ModelError("x")).understanding_omitted is (
        UnderstandingOmission.FAILED
    )
