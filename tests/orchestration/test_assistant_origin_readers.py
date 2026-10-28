"""ADR-0350 §6:12, §12:7: every reader that attributes an input by its origin.

An input whose origin is ``assistant`` is a scheduled task's instruction, which the Task
Scheduler pushes when the task falls due. Each reader that attributes an input by its
origin (ADR-0284 §2:3) attributes it as written by the assistant, never as something the
person said, and none shows its text as the person's.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodeProjection,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StageEntry,
    StageOutcome,
    UnderstandingProducer,
)
from ai_assistant.orchestration import matters_pass, planning, story_tidy_up, understanding
from ai_assistant.testing.parties import parties_for

_AT = datetime(2026, 10, 25, 8, tzinfo=UTC)
_SCHEDULE = ChannelIdentity(channel_type="task_scheduler", instance_id="schedule")
_INSTRUCTION = "INSTRUCTION-SENTINEL: check whether the listing is still up"
_USERS = "the user just sent"


def _scheduled_episode() -> EpisodicMemory:
    """A frozen episode of an activation the Task Scheduler started."""
    return EpisodicMemory(
        id="activation:step",
        content="",
        occurred_at=_AT,
        outcome="It is still listed.",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=_AT),
        processing_record=EpisodeProcessingRecord(
            activation_id="step",
            started_at=_AT,
            ended_at=_AT + timedelta(seconds=1),
            trigger=RecordedChannelTrigger(
                target=_SCHEDULE,
                channel=_SCHEDULE,
                payload=RecordedTextInput(text=_INSTRUCTION),
                context=ChannelContext(),
                reply=None,
                parties=parties_for(InputOrigin.ASSISTANT),
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding=(
                ActivationUnderstanding(
                    version=1,
                    recorded_at=_AT,
                    producer=UnderstandingProducer.INTERPRETATION,
                    meaning="Checking the apartment listing again.",
                ),
            ),
            stages=(
                StageEntry(
                    stage=ControllerStage.END,
                    due=ControllerRule.NOTHING_DUE,
                    started_at=_AT,
                    ended_at=_AT,
                    outcome=StageOutcome.DONE,
                ),
            ),
        ),
    )


def _projection() -> EpisodeProjection:
    return project_episode(_scheduled_episode(), excerpt_chars=400)


def test_understanding_attributes_the_input_it_reads_as_the_assistants_instruction() -> None:
    """The activation's own input: an instruction the assistant wrote, never the user's."""
    rendered = understanding._input_rendering(_INSTRUCTION, _SCHEDULE, InputOrigin.ASSISTANT)

    assert "never something the user said" in str(rendered["received_as"])
    assert _USERS not in str(rendered["received_as"])
    assert rendered["text"] == _INSTRUCTION


def test_understanding_attributes_an_earlier_step_as_work_the_assistant_scheduled() -> None:
    episode = understanding._ProjectedEpisode.of(
        _scheduled_episode(), excerpt_chars=400, admit_outside_input=True
    )

    described = episode.described()

    assert "the assistant scheduled" in str(described["item"])
    assert "never something the user said" in str(described["item"])
    assert _INSTRUCTION not in json.dumps(described, default=str)


def test_the_matters_pass_and_the_tidy_up_attribute_it_and_never_show_it_as_the_users() -> None:
    projection = _projection()

    passed = matters_pass._Episode(
        activation_id="step", linked=(), projection=projection
    ).rendering("E1", {})
    tidied = story_tidy_up._Episode(activation_id="step", projection=projection).rendering("E1")

    for rendered in (passed, tidied):
        assert "the assistant scheduled" in str(rendered["item"])
        assert "the_users_own_input" not in rendered
        assert _INSTRUCTION not in json.dumps(rendered, default=str)


def test_planning_shows_an_earlier_steps_input_as_the_assistants_and_not_its_text() -> None:
    request = SimpleNamespace(shown=SimpleNamespace(marked=False))

    shown = planning._Request._episode_input(request, _projection(), in_place=False)  # type: ignore[arg-type]  # the one attribute the method reads

    assert shown == "the assistant's own instruction for work it scheduled, not shown"
    assert request.shown.marked is False
