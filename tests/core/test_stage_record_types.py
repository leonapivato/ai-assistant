"""The stage-record types of ADR-0280 §4 to §7, as ADR-0309 §3:6-§3:7 and ADR-0318 leave them."""

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
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
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
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        "status": ProcessingStatus.COMPLETED,
        "reason": ProcessingReason.RETURNED,
        "understanding_omitted": UnderstandingOmission.NOT_REACHED,
        "stages": (_end(),),
    }
    fields.update(overrides)
    return EpisodeProcessingRecord.model_validate(fields)


# --- §4, §5: closed enumerations ----------------------------------------------


def test_the_stage_enumeration_carries_exactly_the_members_the_adr_lists() -> None:
    assert [member.value for member in ControllerStage] == [
        "begin_conversation",
        "understanding",
        "end",
        # ADR-0281 §2, ADR-0282 §3 and ADR-0300 §6:10 each add a member without
        # renaming one.
        "recall",
        "windows",
        "story_links",
        # ADR-0307 §10 and ADR-0309 §3:2 add the phases' stages, and ADR-0308 §4:5
        # digesting.
        "planning",
        "authorizing",
        "acting",
        "digesting",
        # ADR-0332 §4:5's takeover, added without renaming one.
        "takeover",
    ]
    # ADR-0309 §3:6: the old path's stages left, a recorded exception to *added to
    # and never renamed*.


def test_the_rule_enumeration_carries_the_table_the_guard_and_the_endings() -> None:
    # §4's table, the loop guard, §2's no_text_input and §5's endings, then ADR-0281
    # §2's row, ADR-0282 §3's, ADR-0286 §7's, ADR-0297 §4's and ADR-0300 §6:10's,
    # each added without renaming one. ADR-0309 §3:6 took the old path's rules out, a
    # recorded exception to that rule.
    assert [member.value for member in ControllerRule] == [
        "conversation_unresolved",
        "not_understood",
        "nothing_due",
        "stage_repeated",
        "no_text_input",
        "stage_failed",
        "stage_timed_out",
        "interrupted",
        "ended_before_controller",
        "not_recalled",
        "windows_unassembled",
        "hub_stopped",
        "stopped",
        "story_links_unrecorded",
        # ADR-0307 §10's three planning rows and ADR-0309 §3:2's two.
        "first_round_due",
        "round_unauthorized",
        "round_authorized",
        "round_limit_reached",
        "round_due",
        # ADR-0308 §2:9's row for recall's second run.
        "understood_not_recalled",
        # ADR-0308 §4:5's row for recall's digest.
        "recall_undigested",
        # ADR-0332 §4:5's row for the takeover.
        "takeover_undecided",
    ]


def test_exactly_the_rules_that_end_a_pass_are_ending_rules() -> None:
    assert {rule.value for rule in ENDING_CONTROLLER_RULES} == {
        "nothing_due",
        "stage_repeated",
        "no_text_input",
        "stage_failed",
        "stage_timed_out",
        "interrupted",
        "ended_before_controller",
        "hub_stopped",
        "stopped",
        "round_limit_reached",
    }


def test_the_outcome_is_a_three_member_classification() -> None:
    assert [member.value for member in StageOutcome] == ["done", "failed", "timed_out"]


# --- §6: the entry --------------------------------------------------------------


def test_a_stage_entry_carries_exactly_its_fields_and_refuses_any_other() -> None:
    # ADR-0280 §6's five; ADR-0284 §5:1's two verdicts left with their stages
    # (ADR-0309 §3:7).
    assert set(StageEntry.model_fields) == {
        "stage",
        "due",
        "started_at",
        "ended_at",
        "outcome",
    }
    with pytest.raises(ValidationError):
        _entry(error="the stage raised")
    for verdict in ("step_disposition", "route_outcome"):
        with pytest.raises(ValidationError):
            _entry(**{verdict: "awaiting_confirmation"})


@pytest.mark.parametrize("outcome", list(StageOutcome))
def test_a_stage_that_ran_records_any_outcome(outcome: StageOutcome) -> None:
    assert _entry(outcome=outcome).outcome is outcome


@pytest.mark.parametrize("due", sorted(ENDING_CONTROLLER_RULES))
def test_the_end_entry_names_any_rule_that_ends_the_pass(due: ControllerRule) -> None:
    assert _end(due).due is due


def test_the_end_entry_refuses_a_rule_that_makes_a_stage_due() -> None:
    with pytest.raises(ValidationError, match="only it, is due to a rule that ends"):
        _end(ControllerRule.NOT_UNDERSTOOD)


def test_a_stage_entry_refuses_a_rule_that_ends_the_pass() -> None:
    with pytest.raises(ValidationError, match="only it, is due to a rule that ends"):
        _entry(stage=ControllerStage.PLANNING, due=ControllerRule.NOTHING_DUE)


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


def test_the_record_is_the_current_schema_version_and_refuses_an_earlier_one() -> None:
    assert _record().schema_version == 12
    for earlier in (4, 10, 11):
        with pytest.raises(ValidationError):
            _record(schema_version=earlier)


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


def test_the_record_carries_a_stage_record_and_round_trips() -> None:
    record = _record(stages=(_entry(), _end()), stages_elided=3)
    assert EpisodeProcessingRecord.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize("elided", [-1, 2**31, True])
def test_the_elided_count_is_a_strict_bounded_integer(elided: object) -> None:
    with pytest.raises(ValidationError):
        _record(stages_elided=elided)


# --- ADR-0318 §4, §5:3: the record keeps no resume, no links and no compose degradation


def test_a_resume_trigger_is_refused() -> None:
    """§4:1: the trigger is a ``RecordedChannelTrigger`` alone."""
    with pytest.raises(ValidationError):
        _record(trigger={"kind": "resume", "channel": None, "approved": True})


@pytest.mark.parametrize(
    "field",
    [
        pytest.param({"links": {}}, id="links"),
        pytest.param({"response_degraded": False}, id="response-degraded"),
    ],
)
def test_the_old_paths_fields_are_refused(field: dict[str, object]) -> None:
    """§4:2 and §5:3: neither field is the record's, so neither is admitted."""
    assert {"links", "response_degraded"}.isdisjoint(EpisodeProcessingRecord.model_fields)
    with pytest.raises(ValidationError):
        _record(**field)
