"""Whom the check runs for, and at what level, in each kind of work (ADR-0368 §7's table).

Table-driven over the rows one person can reach: an identified sender's message carrying
their authority; an unidentified sender's; the owner with an unidentified sender, the only
several senders one person makes; one sender by several connections, whose level is the
lowest and whose met connection is none; a task's work, for its recorded author at the
level it records, though its own facts carry none; and a work that carries none. Then a
call run under a ticket, for its tapper at the level the tap came by (ADR-0367 §5:5,
ADR-0377 §4:2 to §4:4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalGiver,
    ApprovalTap,
    AuthorityKind,
    ChannelIdentity,
    CheckedFor,
    DueNow,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    Sureness,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.work_facts import check_runs_for, tap_runs_for

_AT: Final = datetime(2026, 11, 24, 9, 0, tzinfo=UTC)
_CHAT: Final = ChannelIdentity(channel_type="conversation", instance_id="chat-1")
_OWNER: Final = WorkFor.for_person(OWNER_PERSON_ID)


def _facts(
    level: Sureness,
    *,
    persons: tuple[str, ...] = (OWNER_PERSON_ID,),
    unidentified: bool = False,
    kind: AuthorityKind = AuthorityKind.SENDERS,
) -> WorkFacts:
    return WorkFacts(
        for_whom=_OWNER,
        authority=WorkAuthority(kind=kind, persons=persons, unidentified=unidentified),
        level=level,
    )


def _task(*, by_the_person: bool = True, level: Sureness = Sureness.NORMAL) -> ScheduledTask:
    """A task, set by the owner's work at ``level``, or by the assistant."""
    return ScheduledTask(
        id="t-1",
        person=OWNER_PERSON_ID,
        author=ScheduledTaskAuthor.PERSON if by_the_person else ScheduledTaskAuthor.ASSISTANT,
        author_person=OWNER_PERSON_ID if by_the_person else None,
        setting_level=level if by_the_person else Sureness.NONE,
        setting_connection=None,
        when=DueNow(),
        instruction="water the plants",
        parent="act-0",
        set_in=_CHAT,
        set_at=_AT,
        chain_length=1,
        occurrences=(ScheduledOccurrence(number=1, due_at=_AT),),
    )


_NO_ONE: Final = (CheckedFor.no_one(),)
_NONE: Final = WorkFacts(for_whom=_OWNER, authority=WorkAuthority.none(), level=Sureness.NONE)

#: Each row: its name, the work's facts, whether its input is its senders' own words,
#: whether it holds a relayed input, its task, and whom the check runs for.
_ROWS: Final[
    list[
        tuple[
            str,
            WorkFacts | None,
            bool,
            bool,
            ScheduledTask | None,
            tuple[CheckedFor, ...],
        ]
    ]
] = [
    (
        "an identified sender's message carrying their authority, at its level",
        _facts(Sureness.NORMAL),
        True,
        False,
        None,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
    (
        "the same, from a link lowered to weak",
        _facts(Sureness.WEAK),
        True,
        False,
        None,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "an unidentified sender's message: a member of anyone alone, at none",
        _facts(Sureness.NONE, persons=(), unidentified=True),
        True,
        False,
        None,
        (CheckedFor.anyone(),),
    ),
    (
        "several senders, the owner and an unidentified one: each, at the work's none",
        _facts(Sureness.NONE, unidentified=True),
        True,
        False,
        None,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE), CheckedFor.anyone()),
    ),
    (
        "one sender by several connections: the lowest of its inputs' levels",
        _facts(Sureness.WEAK),
        True,
        False,
        None,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "a task's work: its recorded author, at the level it records, whatever its facts",
        _NONE,
        False,
        False,
        _task(level=Sureness.NORMAL),
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
    (
        "a task set at weak runs at weak",
        _NONE,
        False,
        False,
        _task(level=Sureness.WEAK),
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "a task the assistant authored carries none",
        _NONE,
        False,
        False,
        _task(by_the_person=False),
        _NO_ONE,
    ),
    (
        "a work that carries none: a signal, an approval's outcome, upkeep",
        _NONE,
        False,
        False,
        None,
        _NO_ONE,
    ),
    ("a work with no facts fails closed", None, True, False, None, _NO_ONE),
    (
        "a forward: its input is not its sender's own words",
        _facts(Sureness.NORMAL),
        False,
        False,
        None,
        _NO_ONE,
    ),
    (
        "a relayed input carries none (ADR-0351 §6:5)",
        _facts(Sureness.NORMAL),
        True,
        True,
        None,
        _NO_ONE,
    ),
    (
        "a person the hub does not admit is read as no one",
        _facts(Sureness.NORMAL, persons=("person:someone",)),
        True,
        False,
        None,
        _NO_ONE,
    ),
    (
        "in advance: its author, at its level",
        _facts(Sureness.NORMAL, kind=AuthorityKind.IN_ADVANCE),
        True,
        False,
        None,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
]


@pytest.mark.parametrize(
    ("facts", "own_input", "relayed", "task", "expected"),
    [row[1:] for row in _ROWS],
    ids=[row[0] for row in _ROWS],
)
def test_the_check_runs_for_whom_the_table_names(
    facts: WorkFacts | None,
    own_input: bool,
    relayed: bool,
    task: ScheduledTask | None,
    expected: tuple[CheckedFor, ...],
) -> None:
    """ADR-0368 §7:1 to §7:5 and its table, read from what the work records."""
    assert check_runs_for(facts, own_input=own_input, relayed=relayed, task=task) == expected


@pytest.mark.parametrize(
    ("tap", "expected"),
    [
        (
            ApprovalTap(
                who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
                at=_AT,
                person=OWNER_PERSON_ID,
                level=Sureness.NORMAL,
            ),
            CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),
        ),
        (
            ApprovalTap(
                who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
                at=_AT,
                person=OWNER_PERSON_ID,
                level=Sureness.WEAK,
            ),
            CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),
        ),
        (
            # ADR-0377 §4:3, §4:4: an answer from before the level was recorded.
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT, person=OWNER_PERSON_ID),
            CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE),
        ),
        (
            ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=_AT),
            CheckedFor.anyone(),
        ),
        (
            ApprovalTap(
                who=ApprovalGiver.USER_TAP_ON_HUB_PANEL,
                at=_AT,
                person="person:someone",
                level=Sureness.NORMAL,
            ),
            CheckedFor.no_one(),
        ),
    ],
    ids=["normal", "weak", "level not recorded", "no one's tap", "not admitted"],
)
def test_a_tickets_call_is_checked_for_its_tapper_at_the_taps_level(
    tap: ApprovalTap, expected: CheckedFor
) -> None:
    """ADR-0367 §5:5, ADR-0377 §4:2 to §4:4."""
    assert tap_runs_for(tap) == expected
