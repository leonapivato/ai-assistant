"""The stage-record types and the additive record fields of ADR-0280 §4 to §7."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ENDING_CONTROLLER_RULES,
    ChannelContext,
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    NewConversation,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedTextInput,
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
    ]


def test_the_rule_enumeration_carries_the_table_the_guard_and_the_endings() -> None:
    # §4's table (12 rules), the loop guard, §2's no_text_input and §5's endings.
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


def test_a_stage_entry_carries_exactly_five_fields_and_refuses_any_other() -> None:
    assert set(StageEntry.model_fields) == {"stage", "due", "started_at", "ended_at", "outcome"}
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


# --- §7 step 1: additive record fields ------------------------------------------


def test_the_record_defaults_to_no_stages_and_keeps_schema_version_two() -> None:
    record = _record()
    assert (record.schema_version, record.stages, record.stages_elided) == (2, (), 0)


def test_the_record_carries_a_stage_record_and_round_trips() -> None:
    record = _record(stages=(_entry(), _end()), stages_elided=3)
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("elided", [-1, 2**31, True])
def test_the_elided_count_is_a_strict_bounded_integer(elided: object) -> None:
    with pytest.raises(ValidationError):
        _record(stages_elided=elided)
