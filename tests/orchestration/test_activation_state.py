"""Activation identity, exact source material, and ordered terminal classification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import (
    AssistantError,
    ModelError,
    ModelTimeoutError,
    OversizedValueError,
    SpeechTimeoutError,
    UnderstandingError,
)
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationDigest,
    ActivationUnderstanding,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    ChannelTarget,
    ClaimedAuthor,
    ControllerRule,
    ControllerStage,
    DigestOutcome,
    LabelKind,
    NewConversation,
    PlanningLabel,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenReply,
    StageOutcome,
    StatementPart,
    SupportHolder,
    TextChannelPayload,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    ActivationState,
    active_state,
    admit_channel,
    canonical_activation_id,
    terminal_status,
)

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


def test_admission_records_the_parties_each_kind_declares() -> None:
    """ADR-0351 §2:6-§2:8, §3:1, §3:6: set by code at admission, never ``None``."""
    owner = SupportHolder.person(OWNER_PERSON_ID)
    sam = SupportHolder.source("77", claimed=True)
    line = ChannelIdentity(channel_type="telegram", instance_id="conn-1/42")
    # A party the sensor brings is replaced by the one the kind declares (§2:8).
    note = RecordedInputMessage(
        text="Is this right?", sent_at=_AT, position=1, party=SupportHolder.person("sam")
    )
    forward = RecordedInputMessage(
        text="Ana moved to Porto.",
        sent_at=_AT,
        position=2,
        forwarded_from=ClaimedAuthor(name="Sam", account_id=77),
    )

    def admitted(target: ChannelTarget, **extra: object) -> RecordedChannelTrigger:
        return admit_channel(
            ChannelInput(target=target, payload=TextChannelPayload(text="hi")),
            None,
            clock=lambda: _AT,
            id_factory=lambda: _ID,
            **extra,  # type: ignore[arg-type]  # the messages or the mark a case varies
        ).trigger

    taken = admitted(line, messages=(note, forward))
    assert taken.parties == (owner, sam)
    assert [one.party for one in taken.messages] == [owner, sam]
    assert admitted(NewConversation()).parties == (owner,)
    schedule = ChannelIdentity(channel_type="task_scheduler", instance_id="schedule")
    statement = SupportHolder.statement(StatementPart.SCHEDULED_INSTRUCTION)
    assert admitted(schedule).parties == (statement,)
    assert admitted(schedule, carries_outside_mark=True).parties == (
        statement,
        SupportHolder.unknown(),
    )
    with pytest.raises(ValueError, match="takes in no forward"):
        admitted(NewConversation(), messages=(forward,))


def test_record_preserves_exact_admitted_material_and_reversed_wall_clock() -> None:
    state = _admitted()
    record = state.processing(_AT - timedelta(seconds=3), None)
    assert record.activation_id == _ID
    assert record.ended_at is not None
    assert record.started_at > record.ended_at
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedTextInput)
    assert record.trigger.payload.text == "  exact user text\n"
    assert record.trigger.context.history[0].text == "quoted input"
    assert record.trigger.channel is None
    assert record.status is ProcessingStatus.COMPLETED


def test_the_rounds_labels_and_digests_recorded_reach_the_open_and_the_frozen_record() -> None:
    """ADR-0307 §2:3, §5:7 and ADR-0308 §5:2: each appended in the order recorded."""
    state = _admitted()
    first = PlanningRound(id="round:1", recorded_at=_AT, text="Looking.")
    result = PlanningLabel(label="R1", kind=LabelKind.RESULT, id="result:1")
    digest = ActivationDigest(
        result="R1", question="when", outcome=DigestOutcome.FAILED, recorded_at=_AT
    )
    state.recorded_round(first, ())
    state.recorded_digest(digest, (result,))
    state.recorded_round(
        PlanningRound(id="round:2", follows="round:1", recorded_at=_AT, text="Nine."), ()
    )
    for record in (state.open_processing(), state.processing(_AT, None)):
        assert [one.id for one in record.rounds] == ["round:1", "round:2"]
        assert record.labels == (result,)
        assert record.digests == (digest,)


def test_speech_snapshot_never_contains_audio() -> None:
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
    record = state.processing(_AT, None)
    assert isinstance(record.trigger, RecordedChannelTrigger)
    assert isinstance(record.trigger.payload, RecordedSpeechInput)
    assert record.trigger.payload.transcript is None
    assert "YXVkaW8=" not in record.model_dump_json()


def test_actual_cancellation_takes_precedence_over_no_words() -> None:
    state = _admitted()
    state.no_words = True
    assert terminal_status(state, asyncio.CancelledError()) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.CANCELLED,
    )


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (ModelTimeoutError("private response"), ProcessingReason.TIMEOUT),
        (SpeechTimeoutError("private transcript"), ProcessingReason.TIMEOUT),
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


async def test_admission_in_a_tracked_child_remains_visible_only_to_its_worker() -> None:
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
    state.omit(UnderstandingOmission.NO_TEXT)
    state.omit(UnderstandingOmission.FAILED)
    assert state.processing(_AT, None).understanding_omitted is UnderstandingOmission.NO_TEXT


def test_a_recorded_version_outranks_a_later_failure() -> None:
    """A pass that recorded a version records no omission, whatever ended it."""
    state = _admitted()
    state.understood(_version(1), limit=8)
    state.understanding_failed(ModelError("later"))
    record = state.processing(_AT, ModelError("later"))
    assert record.understanding_omitted is None
    assert record.reason is ProcessingReason.PROCESSING_FAILED


# --- ADR-0280 §5, §6: the end entry supplied at finalization ----------------------------


@pytest.mark.parametrize(
    ("failure", "rule"),
    [
        (asyncio.CancelledError(), ControllerRule.INTERRUPTED),
        (
            AssistantError("it failed before the controller"),
            ControllerRule.ENDED_BEFORE_CONTROLLER,
        ),
        (None, ControllerRule.ENDED_BEFORE_CONTROLLER),
    ],
)
def test_a_pass_that_never_entered_the_controller_gains_its_end_entry_at_finalization(
    failure: BaseException | None, rule: ControllerRule
) -> None:
    state = _admitted()
    ended = _AT + timedelta(seconds=1)
    record = state.processing(ended, failure)
    (end,) = record.stages
    assert (end.stage, end.due, end.outcome) == (ControllerStage.END, rule, StageOutcome.DONE)
    assert end.started_at == end.ended_at == ended
    assert state.stages.entries == [], "a finalization reading changes nothing on the state"
    assert state.processing(ended, failure) == record


def test_an_end_entry_the_controller_appended_is_the_one_written() -> None:
    state = _admitted()
    state.stages.end(ControllerRule.NOTHING_DUE, _AT)
    record = state.processing(_AT + timedelta(seconds=1), asyncio.CancelledError())
    assert [entry.due for entry in record.stages] == [ControllerRule.NOTHING_DUE]


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
    assert terminal_status(_admitted(), OversizedValueError("o", limit=1, size=2))[1] is (
        ProcessingReason.OUTPUT_OVERSIZED
    )
    assert terminal_status(state, OversizedValueError("o", limit=1, size=2))[1] is (
        ProcessingReason.UNDERSTANDING_FAILED
    )


def test_an_unparseable_understandings_reason_survives_a_later_failure() -> None:
    """ADR-0276 §6: the reason holds whatever ends the pass; a model failure's does not."""
    state = _admitted()
    state.understanding_failed(UnderstandingError("x"))
    assert terminal_status(state, AssistantError("later"))[1] is (
        ProcessingReason.UNDERSTANDING_FAILED
    )
    other = _admitted()
    other.understanding_failed(ModelError("x"))
    assert terminal_status(other, AssistantError("later"))[1] is not (
        ProcessingReason.UNDERSTANDING_FAILED
    )
    assert other.processing(_AT, ModelError("x")).understanding_omitted is (
        UnderstandingOmission.FAILED
    )


# --- ADR-0297 §3, §4: the stop mark ---------------------------------------------------


def test_a_stop_marks_an_activation_whose_end_entry_is_not_appended() -> None:
    """§3:3: the test and the set, one synchronous step; a repeat finds it set."""
    state = _admitted()
    before = state.stopped
    first = state.stop()
    marked = state.stopped
    again = state.stop()
    assert (before, first, marked, again, state.stopped) == (False, True, True, True, True)


def test_a_stop_finds_an_activation_the_controller_ended_and_marks_nothing() -> None:
    """§3:2-§3:3: the end entry appended first decides, so the mark is not set."""
    state = _admitted()
    state.stages.end(ControllerRule.NOTHING_DUE, _AT)
    assert state.stop() is False
    assert not state.stopped


def test_a_stop_after_the_finalization_reading_marks_nothing() -> None:
    """§3:2: a pass ended at finalization has ended, whether or not an entry was appended."""
    state = _admitted()
    first = state.processing(_AT, None)
    assert state.stop() is False
    assert not state.stopped
    # And a second reading builds the same record: nothing moved.
    assert state.processing(_AT, None) == first


def test_a_marked_stopped_pass_ended_by_the_stops_entry_is_ended_for_a_later_stop() -> None:
    """§3:7's retry is for an activation still running; once ended, it is answered ended."""
    state = _admitted()
    assert state.stop()
    state.stages.end(ControllerRule.STOPPED, _AT)
    assert state.stop() is False
    assert state.stopped


@pytest.mark.parametrize(
    "failure",
    [
        None,
        asyncio.CancelledError(),
        ModelTimeoutError("late"),
        OversizedValueError("too big", limit=1, size=2),
        AssistantError("failed"),
    ],
)
def test_a_marked_pass_is_interrupted_stopped_ahead_of_every_other_row(
    failure: BaseException | None,
) -> None:
    """§4:12: ``interrupted / stopped``, ahead of every row, the cancellation row included."""
    state = _admitted()
    state.stop()
    assert terminal_status(state, failure) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )


def test_a_pass_the_phases_left_unfinished_is_failed_processing_failed() -> None:
    """ADR-0293 §8:3, ADR-0275 §5:3: it returned owing *couldn't finish*, so it failed."""
    state = _admitted()
    assert terminal_status(state, None) == (ProcessingStatus.COMPLETED, ProcessingReason.RETURNED)
    state.unfinished = True
    assert terminal_status(state, None) == (
        ProcessingStatus.FAILED,
        ProcessingReason.PROCESSING_FAILED,
    )
    # A failure that raised classifies as it is: the mark adds nothing to it.
    assert terminal_status(state, ModelTimeoutError("late")) == (
        ProcessingStatus.FAILED,
        ProcessingReason.TIMEOUT,
    )
    # A stop is no failure, whatever else the pass holds (ADR-0297 §4).
    state.stop()
    assert terminal_status(state, None) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )


@pytest.mark.parametrize("failure", [None, asyncio.CancelledError(), AssistantError("x")])
def test_a_marked_pass_that_never_entered_the_controller_ends_with_the_stops_entry(
    failure: BaseException | None,
) -> None:
    """§4:5: appended at finalization, where ADR-0280 §5:4 appends ``interrupted``."""
    state = _admitted()
    state.stop()
    record = state.processing(_AT, failure)
    assert [(entry.stage, entry.due) for entry in record.stages] == [
        (ControllerStage.END, ControllerRule.STOPPED)
    ]
    assert (record.status, record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.STOPPED,
    )


@pytest.mark.parametrize(
    ("minted", "canonical"),
    [
        (_ID, True),
        (_ID.upper(), False),
        ("not-a-uuid", False),
        ("00000000-0000-1000-8000-000000000000", False),
        (None, False),
    ],
)
def test_an_activation_id_is_canonical_uuid4_text(minted: object, *, canonical: bool) -> None:
    assert canonical_activation_id(minted) is canonical


_TAKER = "7a1c2e3d-4b5f-4a6b-8c7d-9e0f1a2b3c4d"


@pytest.mark.parametrize("taken", ["absorbed_by", "handed_to"])
def test_a_taken_over_activation_freezes_naming_the_one_that_took_its_matter(taken: str) -> None:
    """ADR-0352 §5:2: absorbed (ADR-0349 §7:7) or its input taken (§7:21), in its freeze."""
    state = _admitted()
    assert state.stop()
    setattr(state, taken, _TAKER)

    record = state.processing(_AT, None)

    assert record.reason is ProcessingReason.STOPPED
    assert record.taken_over_by == _TAKER


def test_an_activation_a_person_stopped_freezes_naming_no_taker() -> None:
    """ADR-0352 §5:2, §6:5: only a hand-over's stop names one; a person's names none."""
    state = _admitted()
    assert state.stop()

    record = state.processing(_AT, None)

    assert record.reason is ProcessingReason.STOPPED
    assert record.taken_over_by is None
