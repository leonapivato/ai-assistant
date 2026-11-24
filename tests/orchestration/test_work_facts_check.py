"""Whom the check runs for, and at what level, in each kind of work (ADR-0368 §7's table).

Table-driven over the rows one person can reach: an identified sender's message carrying
their authority; an unidentified sender's; the owner with an unidentified sender, the only
several senders one person makes; one sender by several connections, whose level is the
lowest and whose met connection is none; a task's work, whose facts record its author's
authority in advance at the level its task records (ADR-0368 §6:1, §6:3), whatever its
input's words are, and none where it holds a relayed input; and a work that carries none.
Then a
call run under a ticket, for its tapper at the level the tap came by (ADR-0367 §5:5,
ADR-0377 §4:2 to §4:4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalGiver,
    ApprovalTap,
    AuthorityKind,
    ChannelContext,
    ChannelIdentity,
    CheckedFor,
    DueNow,
    RecordedChannelTrigger,
    RecordedTextInput,
    ScheduledOccurrence,
    ScheduledTask,
    ScheduledTaskAuthor,
    Sureness,
    WholeTextReply,
    WorkAuthority,
    WorkFacts,
    WorkFor,
)
from ai_assistant.orchestration.task_scheduler import SCHEDULE
from ai_assistant.orchestration.work_facts import check_runs_for, started, tap_runs_for

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


#: A task's occurrence's recorded trigger: on the schedule, sent by no person.
_OCCURRENCE: Final = RecordedChannelTrigger(
    target=SCHEDULE,
    channel=SCHEDULE,
    payload=RecordedTextInput(text="it is time"),
    context=ChannelContext(),
    reply=WholeTextReply(),
    parties=declared_input(SCHEDULE, ())[0],
)


def _task_facts(task: ScheduledTask) -> WorkFacts:
    """A task's work's facts, as its occurrence's admission records them (§6:1, §6:3)."""
    return started(_OCCURRENCE, task=task)


_NO_ONE: Final = (CheckedFor.no_one(),)
_NONE: Final = WorkFacts(for_whom=_OWNER, authority=WorkAuthority.none(), level=Sureness.NONE)

#: Each row: its name, the work's facts, whether its input is its senders' own words,
#: whether it holds a relayed input, and whom the check runs for.
_ROWS: Final[list[tuple[str, WorkFacts | None, bool, bool, tuple[CheckedFor, ...]]]] = [
    (
        "an identified sender's message carrying their authority, at its level",
        _facts(Sureness.NORMAL),
        True,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
    (
        "the same, from a link lowered to weak",
        _facts(Sureness.WEAK),
        True,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "an unidentified sender's message: a member of anyone alone, at none",
        _facts(Sureness.NONE, persons=(), unidentified=True),
        True,
        False,
        (CheckedFor.anyone(),),
    ),
    (
        "several senders, the owner and an unidentified one: each, at the work's none",
        _facts(Sureness.NONE, unidentified=True),
        True,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NONE), CheckedFor.anyone()),
    ),
    (
        "one sender by several connections: the lowest of its inputs' levels",
        _facts(Sureness.WEAK),
        True,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "a task's work: its author, in advance, at the level its task records",
        _task_facts(_task(level=Sureness.NORMAL)),
        False,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
    (
        "a task set at weak runs at weak",
        _task_facts(_task(level=Sureness.WEAK)),
        False,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
    ),
    (
        "a task the assistant authored carries none",
        _task_facts(_task(by_the_person=False)),
        False,
        False,
        _NO_ONE,
    ),
    (
        "a work that carries none: a signal, an approval's outcome, upkeep",
        _NONE,
        False,
        False,
        _NO_ONE,
    ),
    ("a work with no facts fails closed", None, True, False, _NO_ONE),
    (
        "a forward: its input is not its sender's own words",
        _facts(Sureness.NORMAL),
        False,
        False,
        _NO_ONE,
    ),
    (
        "a relayed input carries none (ADR-0351 §6:5)",
        _facts(Sureness.NORMAL),
        True,
        True,
        _NO_ONE,
    ),
    (
        "a person the hub does not admit is read as no one",
        _facts(Sureness.NORMAL, persons=("person:someone",)),
        True,
        False,
        _NO_ONE,
    ),
    (
        "in advance: its author, at its level",
        _facts(Sureness.NORMAL, kind=AuthorityKind.IN_ADVANCE),
        True,
        False,
        (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),),
    ),
]
_ROWS.extend(
    (
        (
            "in advance, its input's words not being a sender's own take nothing away",
            _facts(Sureness.WEAK, kind=AuthorityKind.IN_ADVANCE),
            False,
            False,
            (CheckedFor.for_person(OWNER_PERSON_ID, Sureness.WEAK),),
        ),
        (
            "in advance, a relayed input carries none (ADR-0351 §6:5)",
            _facts(Sureness.WEAK, kind=AuthorityKind.IN_ADVANCE),
            False,
            True,
            _NO_ONE,
        ),
    )
)


@pytest.mark.parametrize(
    ("facts", "own_input", "relayed", "expected"),
    [row[1:] for row in _ROWS],
    ids=[row[0] for row in _ROWS],
)
def test_the_check_runs_for_whom_the_table_names(
    facts: WorkFacts | None,
    own_input: bool,
    relayed: bool,
    expected: tuple[CheckedFor, ...],
) -> None:
    """ADR-0368 §7:1 to §7:5 and its table, read from what the work records."""
    assert check_runs_for(facts, own_input=own_input, relayed=relayed) == expected


@pytest.mark.parametrize(
    ("by_the_person", "level", "authority"),
    [
        (
            True,
            Sureness.NORMAL,
            WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(OWNER_PERSON_ID,)),
        ),
        (
            True,
            Sureness.WEAK,
            WorkAuthority(kind=AuthorityKind.IN_ADVANCE, persons=(OWNER_PERSON_ID,)),
        ),
        (False, Sureness.NONE, WorkAuthority.none()),
    ],
    ids=["set by the owner at normal", "set by the owner at weak", "set by the assistant"],
)
def test_a_tasks_work_records_its_authors_authority_in_advance(
    by_the_person: bool, level: Sureness, authority: WorkAuthority
) -> None:
    """ADR-0368 §6:1, §6:3: its facts say so, at the level the task records; none where the
    assistant set it. An occurrence handed no task records none, failing closed."""
    facts = _task_facts(_task(by_the_person=by_the_person, level=level))
    bare = started(_OCCURRENCE)

    assert facts == WorkFacts(for_whom=_OWNER, authority=authority, level=level)
    assert bare.authority == WorkAuthority.none()


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
