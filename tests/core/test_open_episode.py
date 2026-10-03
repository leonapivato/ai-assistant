"""The open episode's shapes and its extension check (ADR-0286 §1, §3, §7).

Lane 1 of ADR-0286 §15: the optional end fields and the validators that hold an open
record and an open episode, :func:`episode_extends`, and ``hub_stopped``. No writer
produces an open episode yet; these pin the shapes the later lanes write.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.episode_encoding import episode_content, episode_extends, project_episode
from ai_assistant.core.types import (
    ENDING_CONTROLLER_RULES,
    ActivationLinks,
    ActivationRecall,
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    NewConversation,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecallCue,
    RecallOutcome,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpokenAudioFormat,
    SpokenReply,
    StageEntry,
    StageOutcome,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=30)
_CONVERSATION = ChannelIdentity(channel_type="conversation", instance_id="c1")
_OWNER_ONLY = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_NOW)


def _trigger(*, channel: ChannelIdentity | None = None) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=NewConversation(),
        channel=channel,
        payload=RecordedTextInput(text="what is on today?"),
        context=ChannelContext(),
        reply=WholeTextReply(),
        origin=InputOrigin.USER,
    )


def _speech(transcript: str | None) -> RecordedChannelTrigger:
    return RecordedChannelTrigger(
        target=NewConversation(),
        channel=None,
        payload=RecordedSpeechInput(media_type=SpokenAudioFormat.WEBM_OPUS, transcript=transcript),
        context=ChannelContext(),
        reply=SpokenReply(plays=(SpokenAudioFormat.WEBM_OPUS,)),
        origin=InputOrigin.USER,
    )


def _stage(index: int, stage: ControllerStage = ControllerStage.TURN_LOOP) -> StageEntry:
    at = _NOW + timedelta(seconds=index)
    return StageEntry(
        stage=stage,
        due=ControllerRule.UNPLANNED,
        started_at=at,
        ended_at=at,
        outcome=StageOutcome.DONE,
    )


def _end(due: ControllerRule = ControllerRule.NOTHING_DUE) -> StageEntry:
    return StageEntry(
        stage=ControllerStage.END,
        due=due,
        started_at=_LATER,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )


def _understanding(version: int) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_NOW,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=f"reading {version}",
        meaning_ground=UnderstandingGround.INFERRED,
    )


def _open(**fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "trigger": _trigger(),
    }
    values.update(fields)
    return EpisodeProcessingRecord.model_validate(values)


def _frozen(record: EpisodeProcessingRecord, **fields: object) -> EpisodeProcessingRecord:
    values: dict[str, object] = {
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "ended_at": _LATER,
        "stages": (*record.stages, _end()),
    }
    if not record.understanding:
        values["understanding_omitted"] = UnderstandingOmission.NOT_REACHED
    values.update(fields)
    return EpisodeProcessingRecord.model_validate({**dict(record), **values})


def _episode(
    record: EpisodeProcessingRecord,
    *,
    outcome: str | None = None,
    content: str = "",
    placement: Placement = _OWNER_ONLY,
) -> EpisodicMemory:
    return EpisodicMemory(
        id="activation:activation",
        content=content,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
        outcome=outcome,
        processing_record=record,
        placement=placement,
    )


# --- §1: open and frozen ----------------------------------------------------------


def test_a_record_with_no_status_is_open() -> None:
    record = _open()
    assert record.is_open
    assert (record.status, record.reason, record.ended_at) == (None, None, None)
    assert record.stages == ()


def test_a_record_with_its_status_is_frozen() -> None:
    assert not _frozen(_open()).is_open


@pytest.mark.parametrize(
    "fields",
    [
        {"status": ProcessingStatus.COMPLETED},
        {"reason": ProcessingReason.RETURNED},
        {"ended_at": _LATER},
        {"status": ProcessingStatus.COMPLETED, "reason": ProcessingReason.RETURNED},
        {"reason": ProcessingReason.RETURNED, "ended_at": _LATER},
    ],
)
def test_status_reason_and_end_time_are_set_together(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="together"):
        _open(stages=(_end(),), understanding_omitted=UnderstandingOmission.NOT_REACHED, **fields)


def test_an_open_record_carries_no_end_entry() -> None:
    with pytest.raises(ValidationError, match="open stage record carries no end entry"):
        _open(stages=(_stage(1), _end()))


def test_an_open_record_carries_no_omission() -> None:
    with pytest.raises(ValidationError, match="no understanding omission"):
        _open(understanding_omitted=UnderstandingOmission.NOT_REACHED)


def test_an_open_record_may_carry_stages_and_understanding() -> None:
    record = _open(stages=(_stage(1), _stage(2)), understanding=(_understanding(1),))
    assert record.is_open


def test_a_frozen_record_keeps_its_end_entry_rule() -> None:
    with pytest.raises(ValidationError, match="exactly one end entry, last"):
        _frozen(_open(), stages=(_stage(1),))


def test_a_frozen_record_keeps_its_understood_or_omitted_rule() -> None:
    with pytest.raises(ValidationError, match="either its understanding or why"):
        _frozen(_open(), understanding_omitted=None)


def test_an_open_record_round_trips() -> None:
    record = _open(stages=(_stage(1),))
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


def test_an_open_episode_is_bare_and_owner_only() -> None:
    episode = _episode(_open())
    assert episode.content == ""
    assert episode.placement.reach is PlacementReach.OWNER


def test_an_open_episode_carries_no_content() -> None:
    with pytest.raises(ValidationError, match="empty content"):
        _episode(_open(), content="what is on today?")


@pytest.mark.parametrize(
    "placement",
    [
        Placement(),
        Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_NOW),
        Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.PROPOSED, set_at=_NOW),
    ],
)
def test_an_open_episode_is_placed_owner_only_by_derivation(placement: Placement) -> None:
    with pytest.raises(ValidationError, match="reach owner, set by derivation"):
        _episode(_open(), placement=placement)


def test_a_frozen_episode_carries_its_content_and_any_placement() -> None:
    episode = _episode(_frozen(_open()), content="status completed", placement=Placement())
    assert episode.placement == Placement()


def test_an_open_episodes_search_text_is_empty() -> None:
    assert episode_content(_episode(_open(understanding=(_understanding(1),)))) == ""


def test_an_open_episode_is_never_projected() -> None:
    with pytest.raises(ValueError, match="never a model input"):
        project_episode(_episode(_open()), excerpt_chars=100)


# --- §7: hub_stopped --------------------------------------------------------------


def test_hub_stopped_is_a_processing_reason_and_an_ending_rule() -> None:
    assert ProcessingReason("hub_stopped") is ProcessingReason.HUB_STOPPED
    assert ControllerRule("hub_stopped") is ControllerRule.HUB_STOPPED
    assert ControllerRule.HUB_STOPPED in ENDING_CONTROLLER_RULES


def test_a_restarts_close_is_a_frozen_record() -> None:
    stored = _open(stages=(_stage(1),))
    closed = _frozen(
        stored,
        status=ProcessingStatus.INTERRUPTED,
        reason=ProcessingReason.HUB_STOPPED,
        stages=(*stored.stages, _end(ControllerRule.HUB_STOPPED)),
    )
    assert closed.stages[-1].due is ControllerRule.HUB_STOPPED
    assert episode_extends(_episode(stored), _episode(closed))


# --- §3: episode_extends holds --------------------------------------------------


def _extends(before: EpisodeProcessingRecord, after: EpisodeProcessingRecord) -> bool:
    return episode_extends(_episode(before), _episode(after))


def test_a_stage_entry_appended_extends() -> None:
    stored = _open(stages=(_stage(1),))
    assert _extends(stored, _open(stages=(_stage(1), _stage(2))))


def test_the_freezing_revision_extends() -> None:
    stored = _open(stages=(_stage(1),), understanding=(_understanding(1),))
    assert _extends(stored, _frozen(stored))


def test_the_freezing_revision_may_record_the_omission() -> None:
    stored = _open(stages=(_stage(1),))
    revision = _frozen(stored, understanding_omitted=UnderstandingOmission.FAILED)
    assert _extends(stored, revision)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ({"trigger": _trigger()}, {"trigger": _trigger(channel=_CONVERSATION)}),
        ({"trigger": _speech(None)}, {"trigger": _speech("what is on today?")}),
        ({"trigger": _speech(None)}, {"trigger": _speech("")}),
        ({}, {"links": ActivationLinks(goal_id="g1")}),
        (
            {"links": ActivationLinks(goal_id="g1")},
            {"links": ActivationLinks(goal_id="g1", attempt_id="a1")},
        ),
        (
            {},
            {
                "recall": ActivationRecall(
                    outcome=RecallOutcome.NOTHING_FOUND, cues=(RecallCue.ACTIVATION_INPUT,)
                )
            },
        ),
        ({}, {"response_degraded": True}),
        ({}, {"output_degraded": True}),
        ({}, {"understanding": (_understanding(1),)}),
        (
            {"understanding": (_understanding(1),)},
            {"understanding": tuple(map(_understanding, (1, 2)))},
        ),
    ],
)
def test_an_unset_field_taking_a_value_extends(
    before: dict[str, object], after: dict[str, object]
) -> None:
    stored = _open(**before)
    assert _extends(stored, _open(**{**before, **after}))


def test_the_response_taking_a_value_extends() -> None:
    stored = _open(stages=(_stage(1),))
    assert episode_extends(_episode(stored), _episode(stored, outcome="Nothing today."))


def test_several_admitted_differences_at_once_extend() -> None:
    stored = _open(trigger=_speech(None))
    revision = _frozen(
        _open(
            trigger=_speech("hello").model_copy(update={"channel": _CONVERSATION}),
            stages=(_stage(1), _stage(2)),
            understanding=(_understanding(1),),
            links=ActivationLinks(goal_id="g1"),
            response_degraded=True,
        )
    )
    assert episode_extends(_episode(stored), _episode(revision, outcome="Hello."))


def test_no_other_field_of_the_episode_enters_it() -> None:
    stored = _open()
    revision = _open(stages=(_stage(1),))
    widened = _episode(_frozen(revision), content="anything", placement=Placement())
    assert episode_extends(_episode(stored), widened)


# --- §3: episode_extends refuses -------------------------------------------------


def test_an_unchanged_revision_does_not_extend() -> None:
    stored = _open(stages=(_stage(1),))
    assert not _extends(stored, stored)


def test_a_difference_outside_the_record_and_outcome_does_not_extend() -> None:
    stored = _open()
    frozen_placement = _episode(stored, placement=_OWNER_ONLY.model_copy(update={"set_at": None}))
    assert not episode_extends(_episode(stored), frozen_placement)


def test_nothing_extends_a_frozen_record() -> None:
    stored = _frozen(_open(stages=(_stage(1),)))
    revision = stored.model_copy(update={"response_degraded": True})
    assert not episode_extends(
        _episode(stored, content="x", placement=Placement()),
        _episode(revision, content="x", placement=Placement()),
    )


def test_another_activations_record_does_not_extend() -> None:
    assert not _extends(_open(), _open(activation_id="other", stages=(_stage(1),)))


def test_an_episode_without_a_processing_record_neither_extends_nor_is_extended() -> None:
    bare = EpisodicMemory(
        id="activation:activation",
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_NOW),
        occurred_at=_NOW,
    )
    assert not episode_extends(bare, _episode(_open()))
    assert not episode_extends(_episode(_open()), bare)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            {"trigger": _trigger(channel=_CONVERSATION)},
            {
                "trigger": _trigger(
                    channel=ChannelIdentity(channel_type="conversation", instance_id="c2")
                )
            },
        ),
        ({"trigger": _trigger(channel=_CONVERSATION)}, {"trigger": _trigger()}),
        ({"trigger": _speech("hello")}, {"trigger": _speech("goodbye")}),
        ({"trigger": _speech("hello")}, {"trigger": _speech(None)}),
        ({"links": ActivationLinks(goal_id="g1")}, {"links": ActivationLinks(goal_id="g2")}),
        ({"links": ActivationLinks(goal_id="g1")}, {"links": ActivationLinks()}),
        ({"response_degraded": True}, {"response_degraded": False}),
        ({"output_degraded": True}, {"output_degraded": False}),
        (
            {
                "recall": ActivationRecall(
                    outcome=RecallOutcome.NOTHING_FOUND, cues=(RecallCue.ACTIVATION_INPUT,)
                )
            },
            {
                "recall": ActivationRecall(
                    outcome=RecallOutcome.FAILED, cues=(RecallCue.ACTIVATION_INPUT,)
                )
            },
        ),
        ({}, {"started_at": _LATER}),
        ({}, {"trigger": RecordedResumeTrigger(channel=None, approved=True)}),
        ({"trigger": _speech(None)}, {"trigger": _trigger()}),
    ],
)
def test_a_value_once_carried_is_kept(before: dict[str, object], after: dict[str, object]) -> None:
    stored = _open(**before)
    assert not _extends(stored, _open(**{**before, **after}))


def test_a_response_once_carried_is_kept() -> None:
    stored = _episode(_open(), outcome="Nothing today.")
    assert not episode_extends(stored, _episode(_open(), outcome="Something today."))
    assert not episode_extends(stored, _episode(_open(stages=(_stage(1),))))


@pytest.mark.parametrize(
    ("stored", "revision"),
    [
        ((1, 2), (1,)),
        ((1, 2), (2, 1)),
        ((1, 2), (1, 3)),
        ((1, 2), (3, 1, 2)),
        ((1, 2), (1, 3, 2)),
    ],
)
def test_stage_entries_are_only_appended(
    stored: tuple[int, ...], revision: tuple[int, ...]
) -> None:
    assert not _extends(
        _open(stages=tuple(map(_stage, stored))), _open(stages=tuple(map(_stage, revision)))
    )


def test_understanding_versions_are_only_appended() -> None:
    stored = _open(understanding=tuple(map(_understanding, (1, 2))))
    assert not _extends(stored, _open(understanding=tuple(map(_understanding, (1, 3)))))
    assert not _extends(stored, _open(understanding=(_understanding(1),)))


def test_an_elided_count_grows_by_what_the_bound_dropped() -> None:
    stored = _open(stages=tuple(map(_stage, (1, 2, 3, 4))))
    # Limit 4: the fifth entry drops the third; the head keeps 1, 2, the tail 4, 5.
    kept = tuple(map(_stage, (1, 2, 4, 5)))
    assert _extends(stored, _open(stages=kept, stages_elided=1))
    # Dropping one, the tail starts at the stored fourth entry, not the third.
    assert not _extends(stored, _open(stages=tuple(map(_stage, (1, 2, 3, 5))), stages_elided=1))
    # Dropping none, the stored entries are the prefix.
    assert not _extends(stored, _open(stages=kept))
    # The head is the stored head.
    assert not _extends(stored, _open(stages=tuple(map(_stage, (1, 3, 4, 5))), stages_elided=1))


def test_entries_equal_to_stored_ones_may_be_appended_past_the_tail() -> None:
    """Two appended entries, dropping 3 and 4, may leave what looks like 4 and 5.

    The records alone cannot tell this from one appended entry, and ADR-0286 §3
    decides from the records alone: the elided count says how many were appended.
    """
    stored = _open(stages=tuple(map(_stage, (1, 2, 3, 4))))
    assert _extends(stored, _open(stages=tuple(map(_stage, (1, 2, 4, 5))), stages_elided=2))


def test_a_cut_record_takes_no_entry_the_bound_does_not_drop() -> None:
    stored = _open(stages=tuple(map(_stage, (1, 2, 4, 5))), stages_elided=1)
    assert not _extends(stored, _open(stages=tuple(map(_stage, (1, 2, 4, 5, 6))), stages_elided=1))
    assert _extends(stored, _open(stages=tuple(map(_stage, (1, 2, 5, 6))), stages_elided=2))


def test_the_understanding_bound_keeps_version_one_and_the_latest() -> None:
    stored = _open(understanding=tuple(map(_understanding, (1, 2, 3))))
    kept = tuple(map(_understanding, (1, 3, 4)))
    assert _extends(stored, _open(understanding=kept, understanding_elided=1))
    assert not _extends(
        stored, _open(understanding=tuple(map(_understanding, (2, 3, 4))), understanding_elided=1)
    )


def test_an_elided_count_never_shrinks() -> None:
    stored = _open(stages=tuple(map(_stage, (1, 2, 4, 5))), stages_elided=1)
    assert not _extends(stored, _open(stages=tuple(map(_stage, (1, 2, 4, 5)))))


# --- §3: appends equal one write at the end ---------------------------------------


def _bounded[T](entries: tuple[T, ...], limit: int, head: int) -> tuple[tuple[T, ...], int]:
    if len(entries) <= limit:
        return entries, 0
    return (*entries[:head], *entries[len(entries) - (limit - head) :]), len(entries) - limit


@pytest.mark.parametrize("limit", [2, 3, 4, 5, 64])
@pytest.mark.parametrize("batch", [1, 2, 3])
def test_a_record_frozen_through_appends_equals_one_write_at_the_end(
    limit: int, batch: int
) -> None:
    """ADR-0286 §3: each bound applied to stored-then-appended is the bound over all."""
    stages = tuple(map(_stage, range(1, 12)))
    versions = tuple(map(_understanding, range(1, 9)))
    stored = _open()
    for count in range(batch, len(stages) + batch, batch):
        kept_stages, stages_elided = _bounded(stages[:count], limit, limit // 2)
        kept_versions, versions_elided = _bounded(versions[: count * 8 // 11], limit, 1)
        revision = _open(
            stages=kept_stages,
            stages_elided=stages_elided,
            understanding=kept_versions,
            understanding_elided=versions_elided,
        )
        if revision != stored:
            assert _extends(stored, revision), count
        stored = revision
    all_stages, all_elided = _bounded((*stages, _end()), limit, limit // 2)
    in_one_write = _frozen(_open(understanding=_bounded(versions, limit, 1)[0]))
    in_one_write = in_one_write.model_copy(
        update={
            "understanding_elided": _bounded(versions, limit, 1)[1],
            "stages": all_stages,
            "stages_elided": all_elided,
        }
    )
    last, last_elided = _bounded((*stages, _end()), limit, limit // 2)
    freezing = _frozen(stored, stages=last, stages_elided=last_elided)
    assert _extends(stored, freezing)
    assert freezing == in_one_write
