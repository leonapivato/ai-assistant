"""The check's outcome and its record of a call (ADR-0379 §3; ADR-0367 §16).

``CheckOutcome`` is exactly one of six, carrying what it carries and nothing else (§3:1);
``CheckedFor`` names a person exactly where it runs for one, and anyone else at none
(ADR-0368 §7); ``CallCheck`` holds an outcome exactly where the check ran (§3:2); an entry
recorded before the check reads as one the check never reached; and ``ActionRequest``'s
line a call rests on is optional, absent by default, and moves nothing a decision binds.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CHECK_ALLOWS,
    CHECK_NEEDS_A_YES,
    OWNER_PERSON_ID,
    ActionRequest,
    CallCheck,
    CallCheckKind,
    CheckedFor,
    CheckedForKind,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedCall,
    Sureness,
)
from ai_assistant.orchestration.message_tools import TEXT_CALL

_AT: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_the_outcomes_are_exactly_six() -> None:
    """§3:1: closed, and each either allows, needs a yes, or is not done."""
    assert {one.value for one in CheckOutcomeKind} == {
        "allowed_on_no_line",
        "allowed_on_made_grant",
        "needs_yes_shortfall",
        "needs_yes_with_approval",
        "not_done_limit",
        "not_done_no_grant",
    }
    assert set(CheckOutcomeKind) > CHECK_ALLOWS | CHECK_NEEDS_A_YES
    assert not CHECK_ALLOWS & CHECK_NEEDS_A_YES


@pytest.mark.parametrize(
    "carried",
    [
        {"kind": CheckOutcomeKind.ALLOWED_ON_NO_LINE},
        {"kind": CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, "line": "line:1"},
        {"kind": CheckOutcomeKind.NEEDS_YES_SHORTFALL, "bar": Sureness.WEAK},
        {"kind": CheckOutcomeKind.NEEDS_YES_SHORTFALL, "bar": Sureness.STRONG},
        {"kind": CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL},
        {"kind": CheckOutcomeKind.NOT_DONE_LIMIT},
        {"kind": CheckOutcomeKind.NOT_DONE_LIMIT, "line": "line:2"},
        {"kind": CheckOutcomeKind.NOT_DONE_NO_GRANT},
    ],
)
def test_each_outcome_carries_what_it_carries(carried: dict[str, Any]) -> None:
    outcome = CheckOutcome(**carried)
    assert CheckOutcome.model_validate_json(outcome.model_dump_json()) == outcome
    assert outcome.allows is (outcome.kind in CHECK_ALLOWS)


@pytest.mark.parametrize(
    "carried",
    [
        {"kind": CheckOutcomeKind.ALLOWED_ON_MADE_GRANT},
        {"kind": CheckOutcomeKind.ALLOWED_ON_NO_LINE, "line": "line:1"},
        {"kind": CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL, "line": "line:1"},
        {"kind": CheckOutcomeKind.NOT_DONE_NO_GRANT, "line": "line:1"},
        {"kind": CheckOutcomeKind.NEEDS_YES_SHORTFALL, "line": "line:1", "bar": Sureness.WEAK},
        {"kind": CheckOutcomeKind.NEEDS_YES_SHORTFALL},
        {"kind": CheckOutcomeKind.NEEDS_YES_SHORTFALL, "bar": Sureness.NONE},
        {"kind": CheckOutcomeKind.ALLOWED_ON_NO_LINE, "bar": Sureness.WEAK},
        {"kind": CheckOutcomeKind.NOT_DONE_LIMIT, "bar": Sureness.WEAK},
    ],
)
def test_an_outcome_carrying_what_its_kind_does_not_is_refused(carried: dict[str, Any]) -> None:
    """§3:1, §4:2: only a made grant that allows or a made limit is named; a shortfall
    alone carries a bar, never below weak (§2:5)."""
    with pytest.raises(ValidationError):
        CheckOutcome(**carried)


def test_whom_the_check_runs_for() -> None:
    """ADR-0368 §7: a person by their id, at any level; anyone else, by no id, at none."""
    owner = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE)
    assert (owner.kind, owner.person, owner.level) == (
        CheckedForKind.PERSON,
        OWNER_PERSON_ID,
        Sureness.NONE,
    )
    assert CheckedFor.anyone() == CheckedFor(kind=CheckedForKind.ANYONE)
    assert CheckedFor.no_one().level is Sureness.NONE
    for bad in (
        {"kind": CheckedForKind.PERSON},
        {"kind": CheckedForKind.ANYONE, "person": OWNER_PERSON_ID},
        {"kind": CheckedForKind.ANYONE, "level": Sureness.WEAK},
        {"kind": CheckedForKind.NO_ONE, "level": Sureness.NORMAL},
    ):
        with pytest.raises(ValidationError):
            CheckedFor(**bad)


def _run(checked_for: CheckedFor) -> CheckRun:
    return CheckRun(
        checked_for=checked_for, outcome=CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT)
    )


def test_a_calls_check_holds_outcomes_exactly_where_it_ran() -> None:
    """§3:2: one outcome for each one it ran for; none where it did not run."""
    ran = CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=(
            _run(CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE)),
            _run(CheckedFor.anyone()),
        ),
    )
    assert CallCheck.model_validate_json(ran.model_dump_json()) == ran
    for kind in (CallCheckKind.OUTSIDE, CallCheckKind.LINES_UNREAD, CallCheckKind.FAILED):
        assert CallCheck(kind=kind).runs == ()
        with pytest.raises(ValidationError):
            CallCheck(kind=kind, runs=(_run(CheckedFor.anyone()),))
    with pytest.raises(ValidationError):
        CallCheck(kind=CallCheckKind.CHECKED)
    with pytest.raises(ValidationError, match="one outcome for each"):
        CallCheck(
            kind=CallCheckKind.CHECKED,
            runs=(_run(CheckedFor.anyone()), _run(CheckedFor.anyone())),
        )


def test_an_entry_recorded_before_the_check_reads_as_never_checked() -> None:
    """ADR-0326 §4:2's shape: an entry without the field validates as one with none."""
    written = {
        "round": "round:1",
        "call_id": "c1",
        "capability": "search_memories",
        "effect": False,
        "outcome": "done",
        "recorded_at": _AT.isoformat(),
    }
    entry = RecordedCall.model_validate(written)
    assert entry.check is None
    checked = entry.model_copy(
        update={"check": CallCheck(kind=CallCheckKind.OUTSIDE)}
    ).model_dump_json()
    assert RecordedCall.model_validate_json(checked).check == CallCheck(kind=CallCheckKind.OUTSIDE)


def test_an_action_requests_line_is_optional_and_moves_no_decision() -> None:
    """ADR-0367 §16: absent by default; a decision transcribes nothing of it, so what a
    recorded decision authorises is what it was."""
    parameters = {"connection": "L1", "words": "hi"}
    plain = ActionRequest(tool=TEXT_CALL, parameters=parameters)
    assert plain.rests_on is None
    resting = ActionRequest(tool=TEXT_CALL, parameters=parameters, rests_on="line:1")
    decision = PermissionDecision.from_request(
        plain,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id="decision:1",
        decided_at=_AT,
    )
    assert "rests_on" not in decision.model_dump()
    assert decision.authorises(plain)
    assert decision.authorises(resting)
    with pytest.raises(ValidationError):
        ActionRequest(tool=TEXT_CALL, parameters=parameters, rests_on=" ")
