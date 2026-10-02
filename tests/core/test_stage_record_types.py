"""The stage-record types of ADR-0280 §4 to §7, with ADR-0284 §5's verdicts and resumes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ENDING_CONTROLLER_RULES,
    ActivationRecall,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    Disposition,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecallCue,
    RecallOutcome,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedTextInput,
    RouteOutcome,
    StageEntry,
    StageOutcome,
    UnderstandingOmission,
    WholeTextReply,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(seconds=1)


def _entry(**overrides: object) -> StageEntry:
    fields: dict[str, object] = {
        "stage": ControllerStage.UNDERSTANDING,
        "due": ControllerRule.NOT_UNDERSTOOD,
        "started_at": _NOW,
        "ended_at": _LATER,
        "outcome": StageOutcome.DONE,
    }
    fields.update(overrides)
    return StageEntry.model_validate(fields)


def _end(due: ControllerRule = ControllerRule.NOTHING_DUE) -> StageEntry:
    return _entry(stage=ControllerStage.END, due=due, started_at=_LATER, ended_at=_LATER)


def _record(**overrides: object) -> EpisodeProcessingRecord:
    fields: dict[str, object] = {
        "activation_id": "activation",
        "started_at": _NOW,
        "ended_at": _LATER,
        "trigger": RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="book the dentist"),
            context=ChannelContext(),
            conversation=None,
            reply=WholeTextReply(),
        ),
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "response_kind": EpisodeResponseKind.NONE,
        "model_eligible": True,
        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        "stages": (_end(),),
    }
    fields.update(overrides)
    return EpisodeProcessingRecord.model_validate(fields)


# --- §4, §5: closed enumerations ----------------------------------------------


def test_the_stage_enumeration_carries_exactly_the_members_the_adr_lists() -> None:
    assert [member.value for member in ControllerStage] == [
        "begin_conversation",
        "routing",
        "understanding",
        "event_summary",
        "associate_goal",
        "ask_disambiguation",
        "reconcile",
        "turn_loop",
        "drive",
        "compose",
        "end",
        # ADR-0281 §2 and ADR-0282 §3 each add a member without renaming one.
        "recall",
        "windows",
    ]


def test_the_rule_enumeration_carries_the_table_the_guard_and_the_endings() -> None:
    # §4's table (12 rules), the loop guard, §2's no_text_input and §5's endings,
    # then ADR-0281 §2's row, ADR-0282 §3's and ADR-0284 §5:4's, each added without
    # renaming one.
    assert [member.value for member in ControllerRule] == [
        "conversation_unresolved",
        "route_unchecked",
        "route_taken",
        "not_understood",
        "event_unsummarized",
        "association_due",
        "disambiguation_raised",
        "continuing_unreconciled",
        "unplanned",
        "plan_has_steps",
        "reply_owed",
        "nothing_due",
        "stage_repeated",
        "no_text_input",
        "stage_failed",
        "stage_timed_out",
        "interrupted",
        "ended_before_controller",
        "not_recalled",
        "windows_unassembled",
        "park_answered",
    ]


def test_exactly_the_rules_that_end_a_pass_are_ending_rules() -> None:
    assert {rule.value for rule in ENDING_CONTROLLER_RULES} == {
        "route_taken",
        "nothing_due",
        "stage_repeated",
        "no_text_input",
        "stage_failed",
        "stage_timed_out",
        "interrupted",
        "ended_before_controller",
    }


def test_the_outcome_is_a_three_member_classification() -> None:
    assert [member.value for member in StageOutcome] == ["done", "failed", "timed_out"]


# --- §6: the entry --------------------------------------------------------------


def test_a_stage_entry_carries_exactly_its_fields_and_refuses_any_other() -> None:
    # ADR-0280 §6's five, and ADR-0284 §5:1's two verdicts.
    assert set(StageEntry.model_fields) == {
        "stage",
        "due",
        "started_at",
        "ended_at",
        "outcome",
        "step_disposition",
        "route_outcome",
    }
    with pytest.raises(ValidationError):
        _entry(error="the stage raised")


@pytest.mark.parametrize("outcome", list(StageOutcome))
def test_a_stage_that_ran_records_any_outcome(outcome: StageOutcome) -> None:
    assert _entry(outcome=outcome).outcome is outcome


@pytest.mark.parametrize("due", sorted(ENDING_CONTROLLER_RULES))
def test_the_end_entry_names_any_rule_that_ends_the_pass(due: ControllerRule) -> None:
    assert _end(due).due is due


def test_the_end_entry_refuses_a_rule_that_makes_a_stage_due() -> None:
    with pytest.raises(ValidationError, match="only it, is due to a rule that ends"):
        _end(ControllerRule.REPLY_OWED)


def test_a_stage_entry_refuses_a_rule_that_ends_the_pass() -> None:
    with pytest.raises(ValidationError, match="only it, is due to a rule that ends"):
        _entry(stage=ControllerStage.COMPOSE, due=ControllerRule.NOTHING_DUE)


def test_the_end_entry_records_done_at_one_instant() -> None:
    with pytest.raises(ValidationError, match="outcome done at one instant"):
        _entry(stage=ControllerStage.END, due=ControllerRule.NOTHING_DUE)
    with pytest.raises(ValidationError, match="outcome done at one instant"):
        _entry(
            stage=ControllerStage.END,
            due=ControllerRule.STAGE_FAILED,
            started_at=_LATER,
            ended_at=_LATER,
            outcome=StageOutcome.FAILED,
        )


# --- §7: the record fields and the schema-3 shape rule ----------------------------


def test_the_record_is_schema_version_three_and_refuses_any_other() -> None:
    assert _record().schema_version == 4
    with pytest.raises(ValidationError):
        _record(schema_version=2)


@pytest.mark.parametrize(
    "stages",
    [
        pytest.param((), id="empty"),
        pytest.param((_entry(),), id="no-end"),
        pytest.param((_end(), _entry()), id="end-not-last"),
        pytest.param((_end(), _end()), id="two-ends"),
    ],
)
def test_a_channel_record_must_end_in_exactly_one_end_entry_last(
    stages: tuple[StageEntry, ...],
) -> None:
    with pytest.raises(ValidationError, match="exactly one end entry"):
        _record(stages=stages)


_RESUME = RecordedResumeTrigger(channel=None, approved=True)


def test_a_resume_record_may_still_carry_no_stage_record() -> None:
    # ADR-0284 §11:1: the legacy shape stays admitted until lane 6 removes it.
    record = _record(trigger=_RESUME, stages=())
    assert (record.stages, record.stages_elided) == ((), 0)


def test_a_resume_record_with_no_stage_record_elides_none() -> None:
    with pytest.raises(ValidationError, match="elides no stage entry"):
        _record(trigger=_RESUME, stages=(), stages_elided=1)


def test_the_record_carries_a_stage_record_and_round_trips() -> None:
    record = _record(stages=(_entry(), _end()), stages_elided=3)
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("elided", [-1, 2**31, True])
def test_the_elided_count_is_a_strict_bounded_integer(elided: object) -> None:
    with pytest.raises(ValidationError):
        _record(stages_elided=elided)


# --- ADR-0284 §5: the verdict is part of the stage that reached it ---------------


def test_park_answered_makes_a_stage_due_and_ends_no_pass() -> None:
    assert ControllerRule.PARK_ANSWERED not in ENDING_CONTROLLER_RULES
    entry = _entry(stage=ControllerStage.DRIVE, due=ControllerRule.PARK_ANSWERED)
    assert entry.due is ControllerRule.PARK_ANSWERED
    with pytest.raises(ValidationError, match="only it, is due to a rule that ends"):
        _end(ControllerRule.PARK_ANSWERED)


def test_an_entry_carries_no_verdict_by_default() -> None:
    entry = _entry()
    assert (entry.step_disposition, entry.route_outcome) == (None, None)


@pytest.mark.parametrize("disposition", list(Disposition))
def test_a_drive_entry_carries_the_steps_disposition(disposition: Disposition) -> None:
    entry = _entry(
        stage=ControllerStage.DRIVE, due=ControllerRule.PLAN_HAS_STEPS, step_disposition=disposition
    )
    assert entry.step_disposition is disposition
    assert StageEntry.model_validate_json(entry.model_dump_json()) == entry


@pytest.mark.parametrize("outcome", list(RouteOutcome))
def test_a_routing_entry_carries_the_routes_outcome(outcome: RouteOutcome) -> None:
    entry = _entry(
        stage=ControllerStage.ROUTING, due=ControllerRule.ROUTE_UNCHECKED, route_outcome=outcome
    )
    assert entry.route_outcome is outcome
    assert StageEntry.model_validate_json(entry.model_dump_json()) == entry


def _at(stage: ControllerStage, **verdict: object) -> StageEntry:
    """An otherwise valid entry for ``stage``, carrying ``verdict``."""
    if stage is ControllerStage.END:
        return _entry(
            stage=stage,
            due=ControllerRule.NOTHING_DUE,
            started_at=_LATER,
            ended_at=_LATER,
            **verdict,
        )
    return _entry(stage=stage, due=ControllerRule.REPLY_OWED, **verdict)


@pytest.mark.parametrize("stage", [s for s in ControllerStage if s is not ControllerStage.DRIVE])
def test_a_step_disposition_is_refused_off_a_drive_entry(stage: ControllerStage) -> None:
    with pytest.raises(ValidationError, match="on a drive entry alone"):
        _at(stage, step_disposition=Disposition.EXECUTED)


@pytest.mark.parametrize("stage", [s for s in ControllerStage if s is not ControllerStage.ROUTING])
def test_a_route_outcome_is_refused_off_a_routing_entry(stage: ControllerStage) -> None:
    with pytest.raises(ValidationError, match="on a routing entry alone"):
        _at(stage, route_outcome=RouteOutcome.PERFORMED)


def test_each_verdict_reads_back_as_its_own_enum() -> None:
    # The enums share the values `awaiting_confirmation` and `failed`; each field
    # decodes into its own type, so a parked route never reads back as a parked step.
    drive = _at(ControllerStage.DRIVE, step_disposition=Disposition.AWAITING_CONFIRMATION)
    routing = _at(ControllerStage.ROUTING, route_outcome=RouteOutcome.AWAITING_CONFIRMATION)
    drive_back = StageEntry.model_validate_json(drive.model_dump_json())
    routing_back = StageEntry.model_validate_json(routing.model_dump_json())
    assert type(drive_back.step_disposition) is Disposition
    assert type(routing_back.route_outcome) is RouteOutcome


def _resumed_step() -> tuple[StageEntry, ...]:
    """§5:4's shape: the continued stage, compose, and one end entry, last."""
    return (
        _entry(
            stage=ControllerStage.DRIVE,
            due=ControllerRule.PARK_ANSWERED,
            step_disposition=Disposition.EXECUTED,
        ),
        _entry(stage=ControllerStage.COMPOSE, due=ControllerRule.REPLY_OWED),
        _end(),
    )


_RESUMED_ROUTE = (
    _entry(
        stage=ControllerStage.ROUTING,
        due=ControllerRule.PARK_ANSWERED,
        route_outcome=RouteOutcome.REFUSED,
    ),
    _end(),
)


@pytest.mark.parametrize(
    "stages",
    [
        pytest.param(_resumed_step(), id="drive-compose-end"),
        pytest.param(_RESUMED_ROUTE, id="routing-end"),
        pytest.param((_end(),), id="end-alone"),
    ],
)
def test_a_resume_records_the_stages_it_runs(stages: tuple[StageEntry, ...]) -> None:
    record = _record(trigger=_RESUME, stages=stages)
    assert record.stages == stages
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    "stages",
    [
        pytest.param(_resumed_step()[:2], id="no-end"),
        pytest.param((_end(), *_resumed_step()[:2]), id="end-not-last"),
        pytest.param((_end(), _end()), id="two-ends"),
    ],
)
def test_a_resume_stage_record_ends_in_exactly_one_end_entry_last(
    stages: tuple[StageEntry, ...],
) -> None:
    with pytest.raises(ValidationError, match="exactly one end entry"):
        _record(trigger=_RESUME, stages=stages)


def test_a_resume_with_stages_may_elide_some() -> None:
    assert _record(trigger=_RESUME, stages=_resumed_step(), stages_elided=2).stages_elided == 2


def test_a_resume_with_stages_still_carries_no_recall_result() -> None:
    recall = ActivationRecall(
        outcome=RecallOutcome.NOTHING_FOUND, cues=(RecallCue.ACTIVATION_INPUT,)
    )
    with pytest.raises(ValidationError, match="carries no recall result"):
        _record(trigger=_RESUME, stages=_resumed_step(), recall=recall)
