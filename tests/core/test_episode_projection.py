"""ADR-0284 §2, §7 and §8: the input's origin, the search text and the one projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.channel_validation import input_origin
from ai_assistant.core.episode_encoding import (
    ROUTE_OUTCOME_PHRASES,
    STEP_DISPOSITION_PHRASES,
    episode_content,
    project_episode,
)
from ai_assistant.core.types import (
    ActivationUnderstanding,
    Capture,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    Disposition,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EpisodeResponseKind,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    Modality,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    ProjectedText,
    Provenance,
    RecordedActivationTrigger,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    RouteOutcome,
    SpokenAudioFormat,
    SpokenReply,
    StageEntry,
    StageOutcome,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    UnresolvedMatter,
    WholeTextReply,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=1)
_CONVERSATION = ChannelIdentity(channel_type="conversation", instance_id="c1")
_EVENTS = ChannelIdentity(channel_type="informational_event", instance_id="calendar")
_USER_WORDS = "book the dentist for Tuesday at 3"
_REPORT = "Dentist appointment moved to Wednesday 10:00 by the clinic"


def _trigger(origin: InputOrigin | None, *, text: str = _USER_WORDS) -> RecordedChannelTrigger:
    if origin is InputOrigin.OUTSIDE:
        return RecordedChannelTrigger(
            target=_EVENTS,
            channel=_EVENTS,
            payload=RecordedTextInput(text=text),
            context=ChannelContext(),
            conversation=None,
            reply=None,
            origin=origin,
        )
    return RecordedChannelTrigger(
        target=_CONVERSATION,
        channel=_CONVERSATION,
        payload=RecordedTextInput(text=text),
        context=ChannelContext(),
        conversation=None,
        reply=WholeTextReply(),
        origin=origin,
    )


def _understanding(meaning: str, *, version: int = 1, **fields: object) -> ActivationUnderstanding:
    return ActivationUnderstanding.model_validate(
        {
            "version": version,
            "recorded_at": _NOW,
            "producer": UnderstandingProducer.INTERPRETATION,
            "meaning": meaning,
            "meaning_ground": UnderstandingGround.STATED,
            **fields,
        }
    )


def _stage(stage: ControllerStage, due: ControllerRule, **verdict: object) -> StageEntry:
    return StageEntry.model_validate(
        {
            "stage": stage,
            "due": due,
            "started_at": _NOW,
            "ended_at": _LATER,
            "outcome": StageOutcome.DONE,
            **verdict,
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
    trigger: RecordedActivationTrigger,
    *,
    understanding: tuple[ActivationUnderstanding, ...] = (),
    stages: tuple[StageEntry, ...] = (_END,),
    outcome: str | None = None,
    status: ProcessingStatus = ProcessingStatus.COMPLETED,
    reason: ProcessingReason = ProcessingReason.RETURNED,
    provenance: Provenance | None = None,
) -> EpisodicMemory:
    omitted = None
    if not understanding:
        omitted = (
            UnderstandingOmission.NO_INPUT
            if isinstance(trigger, RecordedResumeTrigger)
            else UnderstandingOmission.NOT_REACHED
        )
    processing = EpisodeProcessingRecord(
        activation_id="activation",
        started_at=_NOW,
        ended_at=_LATER,
        trigger=trigger,
        status=status,
        reason=reason,
        response_kind=(
            EpisodeResponseKind.NONE if outcome is None else EpisodeResponseKind.CONVERSATION_REPLY
        ),
        model_eligible=True,
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


_RESUME = RecordedResumeTrigger(channel=_CONVERSATION, approved=True)


# --- §2: where the input came from ----------------------------------------------


def test_the_origin_enumeration_is_user_and_outside() -> None:
    assert [member.value for member in InputOrigin] == ["user", "outside"]


def test_a_recorded_trigger_carries_no_origin_until_admission_sets_one() -> None:
    assert _trigger(None).origin is None


@pytest.mark.parametrize("origin", list(InputOrigin))
def test_a_recorded_trigger_round_trips_its_origin(origin: InputOrigin) -> None:
    trigger = _trigger(origin)
    assert RecordedChannelTrigger.model_validate_json(trigger.model_dump_json()) == trigger
    assert trigger.origin is origin


def test_a_resume_trigger_has_no_origin_field() -> None:
    # §2:4: a resume has no input.
    assert "origin" not in RecordedResumeTrigger.model_fields
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RecordedResumeTrigger.model_validate(
            {"channel": None, "approved": True, "origin": InputOrigin.USER}
        )


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
    with pytest.raises(ValueError, match="declares no input origin"):
        input_origin(ChannelIdentity(channel_type="sensor", instance_id="door"))


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


def test_an_input_of_unknown_origin_contributes_no_words() -> None:
    record = _episode(_trigger(None), understanding=(_understanding("a dentist booking"),))
    assert episode_content(record) == "a dentist booking"


def test_an_episode_with_no_understanding_is_found_by_how_it_ended() -> None:
    record = _episode(
        _trigger(InputOrigin.USER),
        status=ProcessingStatus.WAITING,
        reason=ProcessingReason.DISAMBIGUATION,
    )
    assert episode_content(record) == f"status waiting, reason disambiguation\n{_USER_WORDS}"


def test_a_users_transcript_is_their_words() -> None:
    trigger = RecordedChannelTrigger(
        target=_CONVERSATION,
        channel=_CONVERSATION,
        payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript="call mum"),
        context=ChannelContext(),
        conversation=None,
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        origin=InputOrigin.USER,
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
        conversation=None,
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        origin=InputOrigin.USER,
    )
    record = _episode(
        trigger, status=ProcessingStatus.FAILED, reason=ProcessingReason.TRANSCRIPTION_FAILED
    )
    assert episode_content(record) == "status failed, reason transcription_failed"


def test_a_resume_is_found_by_how_it_ended() -> None:
    record = _episode(_RESUME, outcome="Done: the invite is sent.")
    assert episode_content(record) == "status completed, reason returned"


def test_the_search_text_ignores_the_content_it_replaces() -> None:
    record = _episode(_trigger(InputOrigin.USER), understanding=(_understanding("a booking"),))
    assert "never shown" not in episode_content(record)


def test_an_episode_without_a_processing_record_keeps_its_content() -> None:
    record = _recordless("a harness row's own text")
    assert episode_content(record) == "a harness row's own text"


# --- §8: the projection -------------------------------------------------------------


def test_a_users_episode_projects_every_part() -> None:
    unresolved = (UnresolvedMatter(matter="which dentist", why_it_matters="two are saved"),)
    record = _episode(
        _trigger(InputOrigin.USER),
        understanding=(
            _understanding("an earlier reading", version=1),
            _understanding("a dentist booking", version=2, unresolved=unresolved),
        ),
        outcome="Booked for Tuesday at 3.",
    )
    projection = project_episode(record, excerpt_chars=1000)
    assert projection == EpisodeProjection(
        occurred_at=_NOW,
        channel=_CONVERSATION,
        origin=InputOrigin.USER,
        input=ProjectedText(text=_USER_WORDS, full_chars=len(_USER_WORDS)),
        meaning="a dentist booking",
        meaning_ground=UnderstandingGround.STATED,
        unresolved=unresolved,
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


@pytest.mark.parametrize("admit", [False, True])
def test_an_input_of_unknown_origin_is_never_shown(admit: bool) -> None:
    projection = project_episode(
        _episode(_trigger(None)), excerpt_chars=1000, admit_outside_input=admit
    )
    assert (projection.origin, projection.input) == (None, None)


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


def test_a_resume_projects_no_origin_and_no_input() -> None:
    projection = project_episode(
        _episode(_RESUME, outcome="Sent."), excerpt_chars=100, admit_outside_input=True
    )
    assert (projection.origin, projection.input, projection.meaning) == (None, None, None)
    assert projection.channel == _CONVERSATION


def test_the_stage_verdicts_are_projected_in_stage_order() -> None:
    stages = (
        _stage(ControllerStage.ROUTING, ControllerRule.ROUTE_UNCHECKED),
        _stage(
            ControllerStage.DRIVE,
            ControllerRule.PLAN_HAS_STEPS,
            step_disposition=Disposition.EXECUTED,
        ),
        _stage(ControllerStage.DRIVE, ControllerRule.PLAN_HAS_STEPS),
        _stage(
            ControllerStage.DRIVE,
            ControllerRule.PLAN_HAS_STEPS,
            step_disposition=Disposition.AWAITING_CONFIRMATION,
        ),
        _END,
    )
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), stages=stages), excerpt_chars=100
    )
    assert projection.step_dispositions == (Disposition.EXECUTED, Disposition.AWAITING_CONFIRMATION)
    assert projection.route_outcomes == ()


def test_a_routed_verdict_is_projected() -> None:
    stages = (
        _stage(
            ControllerStage.ROUTING,
            ControllerRule.ROUTE_UNCHECKED,
            route_outcome=RouteOutcome.NOT_FOUND,
        ),
        StageEntry(
            stage=ControllerStage.END,
            due=ControllerRule.ROUTE_TAKEN,
            started_at=_LATER,
            ended_at=_LATER,
            outcome=StageOutcome.DONE,
        ),
    )
    projection = project_episode(
        _episode(_trigger(InputOrigin.USER), stages=stages), excerpt_chars=100
    )
    assert projection.route_outcomes == (RouteOutcome.NOT_FOUND,)
    assert projection.step_dispositions == ()


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
        project_episode(_recordless(), excerpt_chars=bound)  # type: ignore[arg-type]


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
            "meaning exactly with its ground",
            id="meaning-without-ground",
        ),
        pytest.param(
            {
                "capture_modality": Modality.TEXT,
                "unresolved": (UnresolvedMatter(matter="m", why_it_matters="w"),),
            },
            "unresolved matters only with a meaning",
            id="unresolved-without-meaning",
        ),
        pytest.param(
            {"capture_modality": Modality.TEXT, "origin": InputOrigin.USER},
            "carries its content alone",
            id="recordless-with-origin",
        ),
        pytest.param(
            {"capture_modality": Modality.TEXT, "step_dispositions": (Disposition.EXECUTED,)},
            "carries its content alone",
            id="recordless-with-verdict",
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


# --- §8:6: the verdict phrases --------------------------------------------------------


#: ADR-0221 §2's table, as the composer, the planner and the observer each render it
#: (their three copies are byte-identical), keyed by the member each phrase names.
_ADR_0221_STEP_PHRASES = {
    Disposition.EXECUTED: "the selected tool ran",
    Disposition.DENIED: "the action was refused by the permission policy",
    Disposition.AWAITING_CONFIRMATION: "the action was parked for the user to confirm",
    Disposition.NO_CAPABLE_TOOL: "no tool advertised the capability the step needed",
    Disposition.AMBIGUOUS_CAPABILITY: "several tools advertised the capability, so none was chosen",
    Disposition.INVALID_PARAMETERS: (
        "the step's arguments did not fit the declared schema of any capable tool"
    ),
    Disposition.EGRESS_UNBINDABLE: (
        "the outbound call could not be described, so nothing was asked or sent"
    ),
    Disposition.EFFECT_ALREADY_CLAIMED: (
        "this goal had already claimed the act, so nothing was dispatched"
    ),
    Disposition.EFFECT_UNSCOPED: (
        "the plan did not say which act the step was, so nothing was dispatched"
    ),
}
_ADR_0221_ROUTE_PHRASES = {
    RouteOutcome.PERFORMED: "the assistant performed the operation the user asked for",
    RouteOutcome.AWAITING_CONFIRMATION: "the operation was parked for the user to confirm",
    RouteOutcome.REFUSED: "the user declined, so the operation was not performed",
    RouteOutcome.AMBIGUOUS: "more than one record matched, so nothing was performed",
    RouteOutcome.AMBIGUOUS_TRUNCATED: (
        "more records matched than could be shown, so nothing was performed"
    ),
    RouteOutcome.NOT_FOUND: "nothing matched, so nothing was performed",
    RouteOutcome.UNRECORDED: "the decision could not be recorded, so nothing was performed",
    RouteOutcome.FAILED: "the operation was attempted and failed",
}


def test_every_disposition_has_exactly_its_adr_0221_phrase() -> None:
    assert set(STEP_DISPOSITION_PHRASES) == set(Disposition)
    assert dict(STEP_DISPOSITION_PHRASES) == _ADR_0221_STEP_PHRASES


def test_every_route_outcome_has_exactly_its_adr_0221_phrase() -> None:
    assert set(ROUTE_OUTCOME_PHRASES) == set(RouteOutcome)
    assert dict(ROUTE_OUTCOME_PHRASES) == _ADR_0221_ROUTE_PHRASES


def test_a_parked_step_and_a_parked_route_read_differently() -> None:
    # The enums share the value `awaiting_confirmation`; the two tables keep them apart.
    step = STEP_DISPOSITION_PHRASES[Disposition.AWAITING_CONFIRMATION]
    route = ROUTE_OUTCOME_PHRASES[RouteOutcome.AWAITING_CONFIRMATION]
    assert step != route


def test_the_phrase_tables_are_read_only() -> None:
    with pytest.raises(TypeError):
        STEP_DISPOSITION_PHRASES[Disposition.EXECUTED] = "x"  # type: ignore[index]
