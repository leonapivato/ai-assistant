"""Episode inspection shows what the check recorded of each call (ADR-0379 §3:2).

Each call's entry carries the check's record of it, ``RecordedCall.check``: for each one
it ran for, at its level, one of ADR-0379 §3:1's six outcomes with the made line or the bar
it carries; or that the call stayed outside it, or that it did not run. An entry recorded
before the check was built carries none, and the command line says "not checked".
"""

from __future__ import annotations

from io import StringIO
from typing import Final

import pytest
from rich.console import Console
from test_cli_episodes import _AT, _record, _staged

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    CallCheck,
    CallCheckKind,
    CallOutcomeKind,
    CheckedFor,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    EpisodicMemory,
    PlanningRound,
    ProposedCall,
    RecordedCall,
    Sureness,
)
from ai_assistant.interfaces import episode_inspection

_YOU_AT_NORMAL: Final = CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL)


def _checked(*runs: tuple[CheckedFor, CheckOutcome]) -> CallCheck:
    return CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=tuple(CheckRun(checked_for=who, outcome=outcome) for who, outcome in runs),
    )


def _rendered(check: CallCheck | None) -> list[str]:
    """The calls section of an episode holding one call whose entry carries ``check``."""
    rounds = (
        PlanningRound(
            id="r1",
            recorded_at=_AT,
            calls=(ProposedCall(call_id="c1", name="send_email", arguments={}),),
        ),
    )
    entry = RecordedCall(
        round="r1",
        call_id="c1",
        capability="send_email",
        effect=True,
        outcome=CallOutcomeKind.DONE,
        recorded_at=_AT,
        check=check,
    )
    record: EpisodicMemory = _staged(
        _record("checked", response="sent"), rounds=rounds, call_records=(entry,)
    )
    buffer = StringIO()
    episode_inspection.render_detail(
        Console(file=buffer, force_terminal=False, width=200), record, stories=()
    )
    lines = buffer.getvalue().splitlines()
    start = lines.index("Calls:")
    return lines[start + 1 : lines.index("{")]


def test_an_entry_from_before_the_check_says_not_checked() -> None:
    """An entry with no check is one the check never reached: an earlier record among them."""
    assert _rendered(None) == [
        '  Round "r1", call "c1": send_email (with an effect): done',
        "    Check: not checked",
    ]


@pytest.mark.parametrize(
    ("outcome", "said"),
    [
        (CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_NO_LINE), "allowed, on no line"),
        (
            CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line="line:1"),
            'allowed, resting on the grant "line:1"',
        ),
        (
            CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=Sureness.STRONG),
            "needs a yes at strong: no grant applies at this level",
        ),
        (
            CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL),
            "needs a yes: a grant allows it with approval",
        ),
        (
            CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_LIMIT, line="line:2"),
            'not done: the limit "line:2" covers it',
        ),
        (CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_LIMIT), "not done: a limit covers it"),
        (CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT), "not done: no grant covers it"),
    ],
)
def test_each_outcome_is_shown_with_what_it_carries(outcome: CheckOutcome, said: str) -> None:
    """ADR-0379 §3:1: each of the six, with the made line or the bar it carries."""
    assert _rendered(_checked((_YOU_AT_NORMAL, outcome)))[1:] == [
        f"    Check for you, at normal: {said}"
    ]


def test_each_one_the_check_ran_for_is_shown_in_the_order_it_ran() -> None:
    """ADR-0368 §7:3: a check that ran for several shows an outcome for each."""
    check = _checked(
        (_YOU_AT_NORMAL, CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_NO_LINE)),
        (
            CheckedFor.for_person("person:guest", Sureness.WEAK),
            CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT),
        ),
        (CheckedFor.anyone(), CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT)),
        (CheckedFor.no_one(), CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT)),
    )

    assert _rendered(check)[1:] == [
        "    Check for you, at normal: allowed, on no line",
        '    Check for "person:guest", at weak: not done: no grant covers it',
        "    Check for anyone, at none: not done: no grant covers it",
        "    Check for no one: not done: no grant covers it",
    ]


@pytest.mark.parametrize(
    ("kind", "said"),
    [
        (
            CallCheckKind.OUTSIDE,
            "    Check: outside it, a message into a place the work's own input came from",
        ),
        (CallCheckKind.LINES_UNREAD, "    Check: did not run, the lines could not be read"),
        (CallCheckKind.FAILED, "    Check: did not run to an outcome, it failed"),
    ],
)
def test_a_call_the_check_did_not_rule_on_says_why(kind: CallCheckKind, said: str) -> None:
    """ADR-0379 §3:2: outside the check, or a check that did not run, and why."""
    assert _rendered(CallCheck(kind=kind))[1:] == [said]


def test_a_person_id_carrying_a_line_break_cannot_pose_as_a_line() -> None:
    """Record text is quoted, so a line break in an id stays on the one line."""
    check = _checked(
        (
            CheckedFor.for_person("person:x\n    Check: not checked", Sureness.WEAK),
            CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT),
        )
    )

    shown = _rendered(check)

    assert len(shown) == 2
    assert shown[1].startswith('    Check for "person:x\\n')
