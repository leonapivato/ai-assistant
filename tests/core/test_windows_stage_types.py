"""ADR-0282 §3: the windows stage and its rule are added to the stage record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ENDING_CONTROLLER_RULES,
    ControllerRule,
    ControllerStage,
    StageEntry,
    StageOutcome,
)

_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
_LATER = _NOW + timedelta(milliseconds=5)


def test_the_windows_stage_and_rule_are_members_that_make_a_stage_due() -> None:
    assert ControllerStage("windows") is ControllerStage.WINDOWS
    assert ControllerRule("windows_unassembled") is ControllerRule.WINDOWS_UNASSEMBLED
    assert ControllerRule.WINDOWS_UNASSEMBLED not in ENDING_CONTROLLER_RULES
    entry = StageEntry(
        stage=ControllerStage.WINDOWS,
        due=ControllerRule.WINDOWS_UNASSEMBLED,
        started_at=_NOW,
        ended_at=_LATER,
        outcome=StageOutcome.DONE,
    )
    assert StageEntry.model_validate_json(entry.model_dump_json()) == entry


def test_windows_unassembled_cannot_end_a_pass() -> None:
    with pytest.raises(ValidationError, match="end entry"):
        StageEntry(
            stage=ControllerStage.END,
            due=ControllerRule.WINDOWS_UNASSEMBLED,
            started_at=_LATER,
            ended_at=_LATER,
            outcome=StageOutcome.DONE,
        )
