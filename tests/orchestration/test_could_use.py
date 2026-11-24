"""What a work's authority could use: the offer and the connections it is shown (ADR-0368 §8).

The reading is a function of the standing lines, the declarations and whom the check runs
for, using the one check (ADR-0379 §2), with what an outcome comes to mirrored from the
authorizer: allowed is usable; a limit or no grant is not; a yes is usable only by a card in
a person's work, never for a message or ``request_approval``; a ticket the work holds is
checked for its tapper (ADR-0367 §5:5); and a reply into the work's own place is outside the
check (§4:7). A connection a grant that asks covers is usable only where its record names
the work's person (ADR-0381 §6:3).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.types import (
    APPROVALS_CONNECTION,
    OWN_CHAT_CONNECTION,
    OWNER_PERSON_ID,
    SCHEDULE_CONNECTION,
    ApprovalGiver,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalTap,
    CheckedFor,
    GrantHow,
    PermissionLine,
    PermissionLineKind,
    RequestedCall,
    Sureness,
    TicketState,
)
from ai_assistant.orchestration.approvals import REQUEST_APPROVAL, Ticket
from ai_assistant.orchestration.channel_kinds import (
    ACCOUNT_KINDS,
    CONNECTION_KINDS,
    connection_kind,
)
from ai_assistant.orchestration.could_use import (
    CouldUse,
    WorkAuthority,
    capabilities_it_could_use,
    connection_key,
    connections_it_could_use,
    records_it_needs,
)
from ai_assistant.orchestration.lookups import ConnectionSearch
from ai_assistant.orchestration.message_tools import TEXT_CALL
from ai_assistant.orchestration.permission_check import CheckSubject
from ai_assistant.orchestration.planning import ConnectionShown
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.orchestration.task_scheduler import TASK_SCHEDULER_CALLS
from ai_assistant.testing import FakeConversationStore
from ai_assistant.testing.searching import FAKE_WEB_SEARCH
from ai_assistant.tools.send_email import EMAIL

_AT: Final = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
_HERE: Final = "conversation:c-here"
_OTHER: Final = "conversation:c-other"
_LINE: Final = "telegram:line"
_MAIL: Final = "account:mail"
_SEARCH: Final = "account:search"

#: Every declaration a hub offers, as these cases have it: a weak bar, two normal ones, the
#: Task Scheduler's, ``request_approval`` and ``send_text``.
_DECLARED: Final = (
    REMEMBER_CANDIDATE,
    FAKE_WEB_SEARCH,
    EMAIL,
    *TASK_SCHEDULER_CALLS,
    REQUEST_APPROVAL,
    TEXT_CALL,
)
_ACCOUNTS: Final = {"search": str(FAKE_WEB_SEARCH.capability)}

#: The connections the hub has, as the section is built before anything filters it.
_HAD: Final = (
    ConnectionShown(place=_HERE, kind=CONNECTION_KINDS["conversation"]),
    ConnectionShown(place=_OTHER, kind=CONNECTION_KINDS["conversation"]),
    ConnectionShown(place=_LINE, kind=CONNECTION_KINDS["telegram"]),
    ConnectionShown(place=SCHEDULE_CONNECTION, kind=CONNECTION_KINDS["task_scheduler"]),
    ConnectionShown(place=APPROVALS_CONNECTION, kind=CONNECTION_KINDS["approvals"]),
    ConnectionShown(place=_MAIL, kind=ACCOUNT_KINDS["email"], account="email"),
    ConnectionShown(place=_SEARCH, kind=ACCOUNT_KINDS["search"], account="search"),
)
_EVERY_CAPABILITY: Final = frozenset(str(one.capability) for one in _DECLARED)


def _owner(level: Sureness, *lines: PermissionLine) -> WorkAuthority:
    return WorkAuthority(
        lines=lines,
        subject=CheckSubject(runs=(CheckedFor.for_person(OWNER_PERSON_ID, level),)),
        person=OWNER_PERSON_ID,
    )


def _no_ones(runs: CheckedFor) -> WorkAuthority:
    return WorkAuthority(lines=(), subject=CheckSubject(runs=(runs,)), person=None)


def _line(  # noqa: PLR0913 — one keyword per part of a line a case varies
    kind: PermissionLineKind,
    action: str,
    *,
    thing: str | None = None,
    how: GrantHow | None = None,
    bar: Sureness | None = None,
    number: int = 1,
) -> PermissionLine:
    return PermissionLine(
        id=f"line:{number}",
        kind=kind,
        who=OWNER_PERSON_ID,
        action=action,
        thing=thing,
        how=how,
        bar=bar,
        made_at=_AT,
        made_by=OWNER_PERSON_ID,
    )


def _shown(could: CouldUse) -> list[str]:
    return [one.place for one in _HAD if could.shows(one.place)]


def _connections(
    authority: WorkAuthority, *, whose: dict[str, str] | None = None, own: tuple[str, ...] = ()
) -> CouldUse:
    return connections_it_could_use(
        authority,
        _HAD,
        declarations=_DECLARED,
        accounts=_ACCOUNTS,
        own=own,
        whose={} if whose is None else whose,
    )


def _capabilities(
    authority: WorkAuthority, *, own_place: bool = True, tickets: tuple[Ticket, ...] = ()
) -> frozenset[str]:
    return capabilities_it_could_use(
        authority, _DECLARED, had=_HAD, own_place=own_place, tickets=tickets
    )


def test_the_owner_at_normal_could_use_everything_the_default_grants_hold() -> None:
    """With no made line, the owner at normal could use every capability and connection."""
    authority = _owner(Sureness.NORMAL)

    assert _capabilities(authority) == _EVERY_CAPABILITY
    assert _shown(_connections(authority)) == [one.place for one in _HAD]


def test_the_owner_at_weak_could_use_a_normal_bar_by_a_card() -> None:
    """ADR-0367 §5:3: a shortfall is a card to the work's person, so it is still usable."""
    authority = _owner(Sureness.WEAK)

    assert _capabilities(authority) == _EVERY_CAPABILITY
    assert _shown(_connections(authority)) == [one.place for one in _HAD]


@pytest.mark.parametrize(
    "runs",
    [CheckedFor.anyone(), CheckedFor.no_one()],
    ids=["an unidentified sender, at none", "a work carrying no authority"],
)
def test_a_work_that_is_no_persons_could_use_only_a_reply_into_its_own_place(
    runs: CheckedFor,
) -> None:
    """ADR-0368 §7:2, §7:4, §7:5: no default grant applies to anyone at none, and no card is
    asked in a work that is no person's, so only a reply into its own place is left (§4:7)."""
    authority = _no_ones(runs)

    assert _capabilities(authority) == {"send_text"}
    assert _capabilities(authority, own_place=False) == frozenset()
    could = _connections(authority, own=(_HERE,))
    assert _shown(could) == [_HERE]
    assert could.connections == frozenset()


def test_a_limit_takes_its_capability_out_of_the_offer() -> None:
    """ADR-0379 §2:2: a limit decides at every level, so its capability is not usable."""
    authority = _owner(Sureness.NORMAL, _line(PermissionLineKind.LIMIT, "remember_fact"))

    assert _capabilities(authority) == _EVERY_CAPABILITY - {"remember_fact"}


def test_a_limit_on_one_connection_hides_it_and_nothing_else() -> None:
    """ADR-0376 §2:5: a line naming the line's chat covers only a text into it."""
    authority = _owner(Sureness.NORMAL, _line(PermissionLineKind.LIMIT, "send_text", thing=_LINE))

    assert _LINE not in _shown(_connections(authority))
    assert _HERE in _shown(_connections(authority))
    assert "send_text" in _capabilities(authority, own_place=False)


def test_a_message_or_a_request_needing_a_yes_is_not_usable_where_another_call_is() -> None:
    """ADR-0356 §7:7, ADR-0361 §2:9: a message and ``request_approval`` are never asked
    about, so a shortfall leaves them unusable where it leaves any other call to a card."""
    authority = _owner(Sureness.NONE)

    usable = _capabilities(authority, own_place=False)

    assert "remember_fact" in usable
    assert "search_web" in usable
    assert "send_text" not in usable
    assert "request_approval" not in usable
    could = _connections(authority)
    assert OWN_CHAT_CONNECTION not in could.connections
    assert _LINE not in _shown(could)
    assert APPROVALS_CONNECTION not in _shown(could)
    assert SCHEDULE_CONNECTION in _shown(could)


def test_lines_that_cannot_be_read_leave_only_the_own_place() -> None:
    """The check would not run, so no call it reaches could be done (ADR-0379 §3:2)."""
    authority = WorkAuthority(
        lines=None,
        subject=CheckSubject(runs=(CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),)),
        person=OWNER_PERSON_ID,
    )

    assert _capabilities(authority) == {"send_text"}
    assert _shown(_connections(authority, own=(_HERE,))) == [_HERE]


def test_a_connection_a_grant_that_asks_covers_is_shown_only_where_its_record_names_one() -> None:
    """ADR-0381 §6:3: one usable only by its person's yes, with no record, is not usable;
    the offer reads no record (§6:4), so the capability stays offered to a person's work."""
    asking = _line(
        PermissionLineKind.GRANT,
        "send_email",
        thing=_MAIL,
        how=GrantHow.WITH_APPROVAL,
        bar=Sureness.WEAK,
    )
    # At weak the default's normal bar does not apply, so the grant that asks decides.
    authority = _owner(Sureness.WEAK, asking)

    assert _MAIL in _shown(_connections(authority, whose={_MAIL: OWNER_PERSON_ID}))
    assert _MAIL not in _shown(_connections(authority))
    assert "send_email" in _capabilities(authority)


def _ticket(level: Sureness) -> Ticket:
    tap = ApprovalTap(
        who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD,
        at=_AT + timedelta(minutes=1),
        person=OWNER_PERSON_ID,
        level=level,
    )
    return Ticket(
        request=ApprovalRequest(
            id="approval:1",
            person=OWNER_PERSON_ID,
            activation_id="act-asker",
            round="round:ask",
            call=RequestedCall(
                tool=REMEMBER_CANDIDATE,
                values={
                    "fact": "The owner waters the plants on Sundays.",
                    "why": "worth keeping",
                    "rests_on_this_stimulus": True,
                    "episode": "activation:act-asker",
                    "rests_on_outside_content": False,
                },
            ),
            why="You asked me to look it up.",
            written_at=_AT,
            expires_at=_AT + timedelta(hours=24),
            state=ApprovalRequestState.APPROVED,
            answer=tap,
            ticket=TicketState.HELD,
        )
    )


@pytest.mark.parametrize(
    ("level", "usable"),
    [(Sureness.WEAK, True), (Sureness.NONE, False)],
    ids=["tapped at the bar", "tapped below it"],
)
def test_a_ticket_the_work_holds_puts_its_call_in_the_offer_where_the_tap_could_run_it(
    level: Sureness, usable: bool
) -> None:
    """ADR-0367 §5:4, §5:5: a ticket's call is checked for its tapper at the tap's level,
    whatever the work carries; a tap below the bar runs nothing."""
    authority = _no_ones(CheckedFor.no_one())

    offered = _capabilities(authority, tickets=(_ticket(level),))

    assert ("remember_fact" in offered) is usable


def test_a_work_of_several_senders_could_use_only_what_every_one_of_them_could() -> None:
    """ADR-0368 §7:3: done only where the check allows it for every one."""
    authority = WorkAuthority(
        lines=(),
        subject=CheckSubject(
            runs=(
                CheckedFor.for_person(OWNER_PERSON_ID, Sureness.NORMAL),
                CheckedFor.anyone(),
            )
        ),
        person=None,
    )

    assert _capabilities(authority) == {"send_text"}


def test_a_connection_no_call_is_made_on_is_left_as_it_is_shown() -> None:
    """A connection on which no declared capability makes a call offers nothing the check
    could refuse, so it is not filtered, at none as for the owner: an event's place, or the
    schedule where no Task Scheduler call is declared. One calls are made on, all refused
    at none, is not shown unless an input of the work came from it."""
    kind = connection_kind("informational_event:door")
    assert kind is not None
    event = ConnectionShown(place="informational_event:door", kind=kind)

    def could(authority: WorkAuthority) -> CouldUse:
        return connections_it_could_use(
            authority,
            (*_HAD, event),
            declarations=(TEXT_CALL,),
            accounts={},
            own=(_HERE,),
            whose={},
        )

    at_none = could(_no_ones(CheckedFor.anyone()))
    assert at_none.shows("informational_event:door")
    assert at_none.shows(SCHEDULE_CONNECTION)
    assert at_none.shows(_SEARCH)
    assert at_none.shows(_HERE)
    assert not at_none.shows(_OTHER)
    assert not at_none.shows(_LINE)
    assert could(_owner(Sureness.NORMAL)).shows(_LINE)


def test_a_conversation_is_shown_as_the_systems_own_chat_is() -> None:
    """ADR-0376 §2:4: every conversation is the one connection, the system's own chat."""
    could = CouldUse(
        connections=frozenset(), own=frozenset(), refused=frozenset({OWN_CHAT_CONNECTION})
    )

    assert connection_key(_OTHER) == OWN_CHAT_CONNECTION
    assert connection_key(SCHEDULE_CONNECTION) == SCHEDULE_CONNECTION
    assert not could.shows("conversation:any")
    assert could.shows(_LINE)


def test_a_record_is_read_only_where_an_outcome_needs_its_things_yes() -> None:
    """ADR-0381 §6:1, §6:3: none where every outcome is decided without one, a grant that
    asks on a capability whose calls have no thing included; the thing's alone where one
    needs it."""
    no_thing = _line(
        PermissionLineKind.GRANT, "search_web", how=GrantHow.WITH_APPROVAL, bar=Sureness.WEAK
    )
    on_mail = _line(
        PermissionLineKind.GRANT,
        "send_email",
        thing=_MAIL,
        how=GrantHow.WITH_APPROVAL,
        bar=Sureness.WEAK,
        number=2,
    )

    def needed(authority: WorkAuthority) -> frozenset[str]:
        return records_it_needs(
            authority, _HAD, declarations=_DECLARED, accounts=_ACCOUNTS, own=(_HERE,)
        )

    assert needed(_owner(Sureness.NORMAL)) == frozenset()
    assert needed(_owner(Sureness.NORMAL, no_thing, on_mail)) == frozenset()
    assert needed(_owner(Sureness.WEAK, no_thing)) == frozenset()
    assert needed(_owner(Sureness.WEAK, on_mail)) == {_MAIL}


def test_a_ticket_the_work_holds_shows_the_connection_its_call_acts_in() -> None:
    """ADR-0368 §8: a connection a ticket it holds could run its call on is one it could
    use, though the work carries no authority: the schedule, for a Task Scheduler call."""
    tap = ApprovalTap(
        who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD,
        at=_AT + timedelta(minutes=1),
        person=OWNER_PERSON_ID,
        level=Sureness.NORMAL,
    )
    listing = next(one for one in TASK_SCHEDULER_CALLS if str(one.capability) == "list_tasks")
    ticket = Ticket(
        request=ApprovalRequest(
            id="approval:2",
            person=OWNER_PERSON_ID,
            activation_id="act-asker",
            round="round:ask",
            call=RequestedCall(tool=listing, values={}),
            why="You asked what is scheduled.",
            written_at=_AT,
            expires_at=_AT + timedelta(hours=24),
            state=ApprovalRequestState.APPROVED,
            answer=tap,
            ticket=TicketState.HELD,
        )
    )
    authority = _no_ones(CheckedFor.no_one())

    def shown(tickets: tuple[Ticket, ...]) -> bool:
        return connections_it_could_use(
            authority,
            _HAD,
            declarations=_DECLARED,
            accounts=_ACCOUNTS,
            own=(APPROVALS_CONNECTION,),
            whose={},
            tickets=tickets,
        ).shows(SCHEDULE_CONNECTION)

    assert not shown(())
    assert shown((ticket,))
    assert "list_tasks" in _capabilities(authority, tickets=(ticket,))


async def test_a_connections_search_finds_only_what_the_work_could_use() -> None:
    """ADR-0368 §8:2: ``search_connections`` finds only connections the work could use."""
    store = FakeConversationStore()
    first = await store.start()
    second = await store.start()
    search = ConnectionSearch(conversations=store, scan=10, page_size=5)
    own_place = f"conversation:{first.id}"
    at_none = CouldUse(
        connections=frozenset(),
        own=frozenset({own_place}),
        refused=frozenset({OWN_CHAT_CONNECTION}),
    )
    owners = CouldUse(connections=frozenset({OWN_CHAT_CONNECTION}), own=frozenset())

    narrowed = await search.search("text messages", 1, shows=at_none.shows)
    whole = await search.search("text messages", 1, shows=owners.shows)

    assert [one.place for one in narrowed.connections] == [own_place]
    assert {one.place for one in whole.connections} == {own_place, f"conversation:{second.id}"}
