"""ADR-0284 §2, §7 and §8: the input's origin, the search text and the one projection.

As ADR-0318 §3 and §4 leave them: no resume trigger and no stage verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import (
    TASK_SCHEDULER,
    establishes_the_user,
    input_origin,
)
from ai_assistant.core.episode_encoding import episode_content, project_episode
from ai_assistant.core.types import (
    ActivationUnderstanding,
    Capture,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    Modality,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    ProjectedText,
    Provenance,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpokenAudioFormat,
    SpokenReply,
    StageEntry,
    StageOutcome,
    UnclearPoint,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.testing.parties import parties_for

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=1)
_CONVERSATION = ChannelIdentity(channel_type="conversation", instance_id="c1")
_EVENTS = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
_USER_WORDS = "book the dentist for Tuesday at 3"
_REPORT = "Dentist appointment moved to Wednesday 10:00 by the clinic"


def _trigger(origin: InputOrigin, *, text: str = _USER_WORDS) -> RecordedChannelTrigger:
    if origin is InputOrigin.OUTSIDE:
        return RecordedChannelTrigger(
            target=_EVENTS,
            channel=_EVENTS,
            payload=RecordedTextInput(text=text),
            context=ChannelContext(),
            reply=None,
            parties=parties_for(origin),
        )
    return RecordedChannelTrigger(
        target=_CONVERSATION,
        channel=_CONVERSATION,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        reply=WholeTextReply(),
        parties=parties_for(origin),
    )


_SCHEDULE = ChannelIdentity(channel_type=TASK_SCHEDULER, instance_id="schedule")
_INSTRUCTION = "check back with the user about the dentist"


def _scheduled() -> RecordedChannelTrigger:
    """A trigger the Task Scheduler pushed: a task's instruction, its origin ``assistant``."""
    return RecordedChannelTrigger(
        target=_SCHEDULE,
        channel=_SCHEDULE,
        payload=RecordedTextInput(text=_INSTRUCTION),
        context=ChannelContext(),
        reply=None,
        parties=parties_for(InputOrigin.ASSISTANT),
    )


def _understanding(meaning: str, *, version: int = 1, **fields: object) -> ActivationUnderstanding:
    return ActivationUnderstanding.model_validate(
        {
            "version": version,
            "recorded_at": _NOW,
            "producer": UnderstandingProducer.INTERPRETATION,
            "meaning": meaning,
            **fields,
        }
    )


_END = StageEntry(
    stage=ControllerStage.END,
    due=ControllerRule.NOTHING_DUE,
    started_at=_LATER,
    ended_at=_LATER,
    outcome=StageOutcome.DONE,
)


def _episode(  # noqa: PLR0913 — one keyword per part of the record a test varies
    trigger: RecordedChannelTrigger,
    *,
    understanding: tuple[ActivationUnderstanding, ...] = (),
    stages: tuple[StageEntry, ...] = (_END,),
    outcome: str | None = None,
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
    reason: ProcessingReason = ProcessingReason.RETURNED,
    provenance: Provenance | None = None,
) -> EpisodicMemory:
    omitted = None if understanding else UnderstandingOmission.NOT_REACHED
    processing = EpisodeProcessingRecord(
        activation_id="activation",
        started_at=_NOW,
        ended_at=_LATER,
        trigger=trigger,
        status=status,
        reason=reason,
        understanding=understanding,
        understanding_omitted=omitted,
        stages=stages,
    )
    return EpisodicMemory(
        id="episode",
        content="the search text, never shown as the episode",
        provenance=provenance
        or Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        outcome=outcome,
        processing_record=processing,
    )


def _recordless(content: str = "The user asked: what is on today?") -> EpisodicMemory:
    return EpisodicMemory(
        id="harness-row",
        content=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        outcome="Two meetings and a dentist appointment.",
        capture=Capture(modality=Modality.SPEECH),
    )


# --- §2: where the input came from ----------------------------------------------


def test_the_origin_enumeration_is_user_outside_and_assistant() -> None:
    """ADR-0284 §2:1, ADR-0350 §12:7: closed, added to and never renamed."""
    assert [member.value for member in InputOrigin] == ["user", "outside", "assistant"]


@pytest.mark.parametrize("origin", list(InputOrigin))
def test_a_recorded_trigger_round_trips_its_origin(origin: InputOrigin) -> None:
    trigger = _trigger(origin)
    assert RecordedChannelTrigger.model_validate_json(trigger.model_dump_json()) == trigger
    assert trigger.origin is origin


@pytest.mark.parametrize(
    ("target", "origin"),
    [
        pytest.param(_CONVERSATION, InputOrigin.USER, id="conversation"),
        pytest.param(NewConversation(), InputOrigin.USER, id="new-conversation"),
        pytest.param(_EVENTS, InputOrigin.OUTSIDE, id="informational-event"),
    ],
)
def test_each_channel_type_declares_its_inputs_origin(
    target: ChannelIdentity | NewConversation, origin: InputOrigin
) -> None:
    assert input_origin(target) is origin


def test_a_channel_type_with_no_declaration_is_refused() -> None:
    with pytest.raises(ValueError, match="declares no parties for its input"):
        input_origin(ChannelIdentity(channel_type="sensor", instance_id="door"))


def test_the_task_scheduler_declares_its_origin_per_input() -> None:
    """ADR-0350 §2:7, §6:3: ``assistant``, or ``outside`` for a task carrying the mark."""
    assert input_origin(_SCHEDULE) is InputOrigin.ASSISTANT
    assert input_origin(_SCHEDULE, carries_outside_mark=True) is InputOrigin.OUTSIDE
    assert not establishes_the_user(TASK_SCHEDULER)


def test_a_mark_is_declared_by_the_task_scheduler_alone_and_never_with_a_forward() -> None:
    """A kind that pushes no marked input declares no origin for one, and none takes both."""
    with pytest.raises(ValueError, match="declares no parties for an input carrying the mark"):
        input_origin(_CONVERSATION, carries_outside_mark=True)
    with pytest.raises(ValueError, match="not both"):
        input_origin(_SCHEDULE, takes_in_forward=True, carries_outside_mark=True)


# --- §7: the search text ----------------------------------------------------------


def test_a_users_episode_is_found_by_its_meaning_and_the_users_words() -> None:
    record = _episode(
        _trigger(InputOrigin.USER),
        understanding=(
            _understanding("an earlier reading", version=1),
            _understanding("a dentist booking", version=2),
        ),
    )
    assert episode_content(record) == f"a dentist booking\n{_USER_WORDS}"


def test_an_outside_episode_is_found_by_its_meaning_alone() -> None:
    record = _episode(
        _trigger(InputOrigin.OUTSIDE, text=_REPORT),
        understanding=(_understanding("the dentist moved the appointment"),),
    )
    content = episode_content(record)
    assert content == "the dentist moved the appointment"
    assert _REPORT not in content


def test_an_outside_episode_no_stage_understood_never_carries_the_report() -> None:
    record = _episode(
        _trigger(InputOrigin.OUTSIDE, text=_REPORT),
        status=ProcessingStatus.FAILED,
        reason=ProcessingReason.UNDERSTANDING_FAILED,
    )
    assert episode_content(record) == "status failed, reason understanding_failed"


def test_a_scheduled_steps_episode_is_found_by_its_meaning_alone() -> None:
    """ADR-0350 §6:3, §6:12: the instruction is the assistant's words, never the user's."""
    record = _episode(_scheduled(), understanding=(_understanding("checking back on the dentist"),))
    content = episode_content(record)
    assert content == "checking back on the dentist"
    assert _INSTRUCTION not in content


def test_a_scheduled_steps_input_is_never_shown_and_carries_its_origin() -> None:
    """ADR-0350 §6:12: a reader attributes it from its origin, never as the user's words."""
    record = _episode(_scheduled(), understanding=(_understanding("checking back"),))
    for admitted in (False, True):
        projection = project_episode(record, excerpt_chars=200, admit_outside_input=admitted)
        assert projection.origin is InputOrigin.ASSISTANT
        assert projection.input is None
        assert projection.meaning == "checking back"


def test_an_episode_with_no_understanding_is_found_by_how_it_ended() -> None:
    record = _episode(
        _trigger(InputOrigin.USER),
        status=ProcessingStatus.FAILED,
        reason=ProcessingReason.PROCESSING_FAILED,
    )
    assert episode_content(record) == f"status failed, reason processing_failed\n{_USER_WORDS}"


def test_a_users_transcript_is_their_words() -> None:
    trigger = RecordedChannelTrigger(
        target=_CONVERSATION,
        channel=_CONVERSATION,
        payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript="call mum"),
        context=ChannelContext(),
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        parties=parties_for(InputOrigin.USER),
    )
    record = _episode(trigger, understanding=(_understanding("a call to make"),))
    assert episode_content(record) == "a call to make\ncall mum"


@pytest.mark.parametrize("transcript", [None, "   "])
def test_speech_with_no_words_adds_none(transcript: str | None) -> None:
    trigger = RecordedChannelTrigger(
        target=_CONVERSATION,
        channel=_CONVERSATION,
        payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript=transcript),
        context=ChannelContext(),
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        parties=parties_for(InputOrigin.USER),
    )
    record = _episode(
        trigger, status=ProcessingStatus.FAILED, reason=ProcessingReason.TRANSCRIPTION_FAILED
    )
    assert episode_content(record) == "status failed, reason transcription_failed"


def test_the_search_text_ignores_the_content_it_replaces() -> None:
    record = _episode(_trigger(InputOrigin.USER), understanding=(_understanding("a booking"),))
    assert "never shown" not in episode_content(record)


def test_an_episode_without_a_processing_record_keeps_its_content() -> None:
    record = _recordless("a harness row's own text")
    assert episode_content(record) == "a harness row's own text"


# --- §8: the projection -------------------------------------------------------------


def test_the_projection_carries_unclear_and_no_ground() -> None:
    """ADR-0353 §14:2: ``unclear`` in place of ``unresolved``, and no ``meaning_ground``."""
    fields = set(EpisodeProjection.model_fields)
    assert "unclear" in fields
    assert not {"meaning_ground", "unresolved"} & fields


def test_a_users_episode_projects_every_part() -> None:
    unclear = (UnclearPoint(gap="which dentist", readings=("Dr Lind", "Dr Moss")),)
    record = _episode(
        _trigger(InputOrigin.USER),
        understanding=(
            _understanding("an earlier reading", version=1),
            _understanding("a dentist booking", version=2, unclear=unclear),
        ),
        outcome="Booked for Tuesday at 3.",
    )
    projection = project_episode(record, excerpt_chars=1000)
    assert projection == EpisodeProjection(
        occurred_at=_NOW,
        channel=_CONVERSATION,
        parties=parties_for(InputOrigin.USER),
        input=ProjectedText(text=_USER_WORDS, full_chars=len(_USER_WORDS)),
        meaning="a dentist booking",
        unclear=unclear,
        response=ProjectedText(text="Booked for Tuesday at 3.", full_chars=24),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        derived_from_external=False,
    )
    assert projection.has_processing_record
    assert projection.capture_modality is None


def test_an_outside_input_is_withheld_unless_admitted() -> None:
    record = _episode(
        _trigger(InputOrigin.OUTSIDE, text=_REPORT),
        understanding=(_understanding("the appointment moved"),),
    )
    withheld = project_episode(record, excerpt_chars=1000)
    assert withheld.origin is InputOrigin.OUTSIDE
    assert withheld.input is None
    assert withheld.meaning == "the appointment moved"
    admitted = project_episode(record, excerpt_chars=1000, admit_outside_input=True)
    assert admitted.input == ProjectedText(text=_REPORT, full_chars=len(_REPORT))


def test_the_input_and_the_response_are_cut_and_the_cut_is_carried() -> None:
    reply = "R" * 50
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), outcome=reply), excerpt_chars=10
    )
    assert projection.input == ProjectedText(text=_USER_WORDS[:10], full_chars=len(_USER_WORDS))
    assert projection.response == ProjectedText(text="R" * 10, full_chars=50)
    assert projection.input is not None
    assert projection.response is not None
    assert projection.input.cut
    assert projection.response.cut


def test_a_text_exactly_at_the_bound_is_not_cut() -> None:
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), outcome="ok"), excerpt_chars=len(_USER_WORDS)
    )
    assert projection.input is not None
    assert projection.response is not None
    assert (projection.input.cut, projection.response.cut) == (False, False)
    assert projection.input.text == _USER_WORDS


def test_an_episode_without_a_processing_record_shows_its_content_as_its_input() -> None:
    projection = project_episode(_recordless(), excerpt_chars=12)
    assert projection == EpisodeProjection(
        occurred_at=_NOW,
        capture_modality=Modality.SPEECH,
        input=ProjectedText(text="The user ask", full_chars=33),
        response=ProjectedText(text="Two meetings", full_chars=39),
    )
    assert not projection.has_processing_record
    assert (projection.channel, projection.origin, projection.status) == (None, None, None)


def test_derived_from_external_is_what_the_predicate_answers() -> None:
    tainted = Provenance(
        source=MemorySource.OBSERVED,
        confidence=0.5,
        last_updated=_NOW,
        derived_from_external=True,
    )
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), provenance=tainted), excerpt_chars=100
    )
    assert projection.derived_from_external
    # ADR-0106 §2: the field means nothing in the asserted band, and the predicate
    # honours the band rather than the boolean.
    asserted = Provenance(
        source=MemorySource.USER_ASSERTED,
        confidence=1.0,
        last_updated=_NOW,
        derived_from_external=True,
    )
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), provenance=asserted), excerpt_chars=100
    )
    assert not projection.derived_from_external


def test_origin_and_derived_from_external_are_independent() -> None:
    # §8:4: an outside report read over no external material is outside and untainted.
    projection = project_episode(_episode(_trigger(InputOrigin.OUTSIDE)), excerpt_chars=100)
    assert projection.origin is InputOrigin.OUTSIDE
    assert not projection.derived_from_external


@pytest.mark.parametrize("bound", [0, -1, True, 1.5])
def test_the_excerpt_bound_is_a_positive_integer(bound: object) -> None:
    with pytest.raises(ValueError, match="excerpt bound"):
        project_episode(_recordless(), excerpt_chars=bound)  # type: ignore[call-overload]


def test_the_projection_never_carries_the_search_text_of_a_recorded_episode() -> None:
    projection = project_episode(_episode(_trigger(InputOrigin.USER)), excerpt_chars=1000)
    assert "never shown" not in projection.model_dump_json()


# --- the projection's shapes -----------------------------------------------------------


def test_a_projected_text_is_no_longer_than_its_whole() -> None:
    with pytest.raises(ValidationError, match="no longer than"):
        ProjectedText(text="abc", full_chars=2)
    assert not ProjectedText(text="", full_chars=0).cut


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        pytest.param(
            {"status": ProcessingStatus.COMPLETED, "channel": _CONVERSATION},
            "status exactly with its reason",
            id="status-without-reason",
        ),
        pytest.param(
            {"meaning": "m", "capture_modality": Modality.TEXT},
            "carries its content alone",
            id="recordless-with-meaning",
        ),
        pytest.param(
            {
                "capture_modality": Modality.TEXT,
                "unclear": (UnclearPoint(gap="g", readings=("r",)),),
            },
            "unclear points only with a meaning",
            id="unclear-without-meaning",
        ),
        pytest.param(
            {"capture_modality": Modality.TEXT, "parties": [{"kind": "unknown"}]},
            "carries its content alone",
            id="recordless-with-parties",
        ),
        pytest.param(
            {"capture_modality": Modality.TEXT, "relayed": True},
            "carries its content alone",
            id="recordless-relayed",
        ),
        pytest.param({}, "carries its content alone", id="recordless-without-modality"),
        pytest.param(
            {
                "status": ProcessingStatus.COMPLETED,
                "reason": ProcessingReason.RETURNED,
                "capture_modality": Modality.TEXT,
            },
            "its channel, not a modality",
            id="recorded-with-modality",
        ),
    ],
)
def test_a_projection_takes_one_of_the_two_shapes(fields: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        EpisodeProjection.model_validate({"occurred_at": _NOW, **fields})


# --- ADR-0318 §3:1: a rendering states status and reason, and no verdict -----------


def test_the_projection_carries_no_stage_verdict() -> None:
    assert {"step_dispositions", "route_outcomes"}.isdisjoint(EpisodeProjection.model_fields)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EpisodeProjection.model_validate(
            {"occurred_at": _NOW, "capture_modality": Modality.TEXT, "step_dispositions": ()}
        )
