"""What a work's authority could use: the tools it is offered and the connections it is shown.

ADR-0368 §8 filters what a work is offered and shown to what its authority **could use**: a
tool, or a connection, on which some call of the work could be allowed, at its level, by the
check, by a card (ADR-0367 §5:3) or under a ticket it holds (§5:5), or which the check would
not reach (§4:7). This module is that reading, and **nothing else**: a function of its
arguments, with no model, no store and no clock of its own. Its caller reads the standing
lines, and the records it may read, and hands them in; the outcome of each call it weighs is
the one check (:func:`~ai_assistant.orchestration.permission_check.checked`), and what an
outcome comes to is what the authorizer makes of it, mirrored here:

* **The check allows it** for every one the check runs for: usable.
* **A limit, or no grant**, for any one of them, or **lines that could not be read**: not
  usable. The authorizer leaves such a call not done, whoever would be asked (ADR-0367 §4:2,
  ADR-0368 §7:3), and a check that did not run leaves every call not done.
* **It needs a yes**: usable only by a card, so only in a work that is a person's (ADR-0368
  §7:4), and never for a message or a ``request_approval``, which are never asked about
  (ADR-0356 §7:7, ADR-0361 §2:9). A shortfall's card goes to the person whose authority the
  work carries (ADR-0367 §5:3); a grant that asks needs the yes of whoever the call's thing
  belongs to (§5:6), read from its record where the caller hands records in (ADR-0381 §6:1,
  §6:3), and for a call with no thing, the work's person (§6:2).

**Under a ticket** (:func:`ticket_could_run`): the ticket's call is checked for the person
whose tap approved it, at the level that tap came by (ADR-0367 §5:5), and runs only where the
check allows it or the tap is the yes a grant that asks needs, as the authorizer's
``_tap_is_the_yes`` has it.

**What the check would not reach** (ADR-0367 §4:7): a message into a place one of the work's
own inputs came from. So ``send_text`` is one a work could use wherever it has such a place,
and that place is a connection it could use (ADR-0368 §8, its closing note).

**Which calls are on a connection** (:func:`connections_it_could_use`). A connection a call's
thing can be (ADR-0376 §2:3) is weighed with that thing: a place that takes a text message by
``send_text`` into it, and an email account by ``send_email`` from it. A connection no call's
thing is, is weighed by the capabilities that act in it or look things up in it, as its kind
declares it can be (ADR-0364 §3:3): the schedule by the Task Scheduler's calls, the approvals
by ``request_approval``, and the search and forecast accounts by the capability their caller
names for each. Any other, such as an event's place, could be used only as an input's own.

A filter shows what a work could use and never why (ADR-0368 §8:4): nothing here is rendered,
and every call is still checked when made, whatever was offered or shown (§8:5).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.types import (
    APPROVALS_CONNECTION,
    CHECK_NEEDS_A_YES,
    OWN_CHAT_CONNECTION,
    SCHEDULE_CONNECTION,
    CallCheck,
    CallCheckKind,
    CheckOutcomeKind,
)
from ai_assistant.orchestration.approvals import (
    APPROVAL_CAPABILITIES,
    REQUEST_APPROVAL_CAPABILITY,
)
from ai_assistant.orchestration.channel_kinds import EMAIL_ACCOUNT_KIND, takes_text
from ai_assistant.orchestration.message_tools import (
    EMAIL_CAPABILITY,
    TEXT_CALL,
    TEXT_CAPABILITY,
)
from ai_assistant.orchestration.permission_check import (
    CheckSubject,
    call_thing,
    checked,
    place_connection,
)
from ai_assistant.orchestration.renames import current_name
from ai_assistant.orchestration.task_scheduler import TASK_SCHEDULER_CAPABILITIES
from ai_assistant.orchestration.work_facts import tap_runs_for

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Sequence

    from ai_assistant.core.types import PermissionLine, ToolDefinition
    from ai_assistant.orchestration.approvals import Ticket
    from ai_assistant.orchestration.planning import ConnectionShown

__all__ = [
    "CouldUse",
    "WorkAuthority",
    "capabilities_it_could_use",
    "connection_key",
    "connections_it_could_use",
    "could_allow",
    "records_it_needs",
    "ticket_could_run",
]

_log = structlog.get_logger(__name__)

#: The calls a card never asks about: a message (ADR-0356 §7:7) and ``request_approval``
#: itself (ADR-0361 §2:9). One that needs a yes is not done.
_NEVER_ASKED: Final = frozenset({TEXT_CAPABILITY, REQUEST_APPROVAL_CAPABILITY})

#: The outcomes that leave a call not done, whoever would be asked (ADR-0367 §4:2).
_REFUSED: Final = frozenset({CheckOutcomeKind.NOT_DONE_LIMIT, CheckOutcomeKind.NOT_DONE_NO_GRANT})


@dataclass(frozen=True, slots=True)
class WorkAuthority:
    """What a work's calls are checked against, and whose yes a card in it asks.

    Attributes:
        lines: The standing made lines, as the line store lists them; ``None`` where they
            could not be read, so the check would not run and no call it reaches is done.
        subject: Whom the check runs for in the work, at what level, and where a condition
            is met (ADR-0368 §7), as the authorizer is handed it.
        person: The person whose work it is, whom a card in it asks; ``None`` where it is
            no person's, which asks no one (ADR-0368 §7:4, §9:5).
    """

    lines: tuple[PermissionLine, ...] | None
    subject: CheckSubject
    person: str | None


def _comes_to_a_run(
    made: CallCheck,
    *,
    capability: str,
    person: str | None,
    thing: str | None,
    whose: Mapping[str, str] | None,
) -> bool:
    """Whether a checked call could run: allowed, or by a card in a person's work."""
    if made.kind is not CallCheckKind.CHECKED:
        return False
    kinds = {one.outcome.kind for one in made.runs}
    needs = frozenset(kinds & CHECK_NEEDS_A_YES)
    if kinds & _REFUSED or not needs:
        return not kinds & _REFUSED
    return _a_card_could_ask(needs, capability=capability, person=person, thing=thing, whose=whose)


def _a_card_could_ask(
    needs: frozenset[CheckOutcomeKind],
    *,
    capability: str,
    person: str | None,
    thing: str | None,
    whose: Mapping[str, str] | None,
) -> bool:
    """Whether a call needing a yes could be asked about, and by whose yes it would run.

    The authorizer's ``_yes_needed``: no card in a work that is no person's (ADR-0368 §7:4)
    or for a call never asked about; a shortfall's card goes to the work's person (ADR-0367
    §5:3); a grant that asks needs the yes of whoever the call's thing belongs to, by its
    record (§5:6, ADR-0381 §6:1), or for a call with no thing the work's person's (§6:2).
    Where no record is handed in, as for the offer, which reads none (§6:4), a card is one
    this work could make.
    """
    if capability in _NEVER_ASKED or person is None:
        return False
    if CheckOutcomeKind.NEEDS_YES_SHORTFALL in needs or thing is None or whose is None:
        return True
    return whose.get(thing) == person


def _checked(
    lines: Sequence[PermissionLine],
    tool: ToolDefinition,
    *,
    thing: str | None,
    subject: CheckSubject,
) -> CallCheck:
    """The check for one call, recorded as failed where it raises, which fails closed."""
    try:
        return checked(lines, tool, thing=thing, subject=subject)
    except Exception:  # a check that raises is no outcome, and leaves the call unusable
        _log.warning("could_use_failed", stage="planning", reason="defect")
        return CallCheck(kind=CallCheckKind.FAILED)


def could_allow(
    authority: WorkAuthority,
    tool: ToolDefinition,
    *,
    thing: str | None,
    whose: Mapping[str, str] | None = None,
) -> bool:
    """Whether a call of ``tool`` on ``thing`` could run in the work, by the check or a card.

    Args:
        authority: What the work's calls are checked against.
        tool: The declaration the call would be selected under.
        thing: The call's thing (ADR-0376 §2:3), or ``None``.
        whose: The person each connection's record names, as read; ``None`` where no
            record is read. A connection with no entry has no record, and is no one's
            (ADR-0381 §5:1).

    Returns:
        Whether it could run.
    """
    if authority.lines is None:
        return False
    made = _checked(authority.lines, tool, thing=thing, subject=authority.subject)
    return _comes_to_a_run(
        made,
        capability=str(tool.capability),
        person=authority.person,
        thing=thing,
        whose=whose,
    )


def ticket_could_run(
    authority: WorkAuthority, ticket: Ticket, *, whose: Mapping[str, str] | None = None
) -> bool:
    """Whether a ticket the work holds could run its call (ADR-0367 §5:4-§5:6).

    Checked for the person whose tap approved it, at the level the tap came by, no
    connection met for a condition; it runs where the check allows it, or where the call
    needs the yes of a grant that asks and the tap could be that yes: for a call with no
    thing, the tapper being the work's person (ADR-0381 §6:2); for a call with a thing, the
    tapper being whom its record names (§6:1), or, where no record is handed in, as for the
    offer, which reads none (§6:4), a tap by a person. A shortfall means the tap fell below
    the bar, which answers nothing.

    Args:
        authority: What the work's calls are checked against: its lines and its person.
        ticket: The ticket.
        whose: The person each connection's record names, as read; ``None`` where no
            record is read.

    Returns:
        Whether it could run.
    """
    answer = ticket.request.answer
    if authority.lines is None or answer is None:
        return False
    call = ticket.request.call
    thing = call_thing(str(call.tool.capability), binding=call.binding)
    tapper = CheckSubject(runs=(tap_runs_for(answer),))
    made = _checked(authority.lines, call.tool, thing=thing, subject=tapper)
    if made.kind is not CallCheckKind.CHECKED:
        return False
    kinds = {one.outcome.kind for one in made.runs}
    if kinds & _REFUSED or CheckOutcomeKind.NEEDS_YES_SHORTFALL in kinds:
        return False
    if CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL not in kinds:
        return True
    return _the_taps_yes(authority, answer.person, thing=thing, whose=whose)


def _the_taps_yes(
    authority: WorkAuthority,
    tapper: str | None,
    *,
    thing: str | None,
    whose: Mapping[str, str] | None,
) -> bool:
    """Whether a tap is the yes a grant that asks needs (ADR-0367 §5:6, ADR-0381 §6:1-§6:2)."""
    if tapper is None:
        return False
    if thing is None:
        # §6:2: a call with no thing needs the work's person's yes.
        return tapper == authority.person
    # §6:1: a call with a thing needs the yes of whoever its record names.
    return whose is None or whose.get(thing) == tapper


def connection_key(place: str) -> str:
    """The connection a place is in, as a line names it, or the place where no line does.

    The system's own chat is one connection, whichever conversation; the schedule and the
    approvals, which no line names (ADR-0376 §2:4), are keyed by their places.
    """
    connection = place_connection(place)
    return place if connection is None else connection


def _by_capability(declarations: Iterable[ToolDefinition]) -> dict[str, list[ToolDefinition]]:
    held: dict[str, list[ToolDefinition]] = {}
    for one in declarations:
        held.setdefault(str(one.capability), []).append(one)
    return held


def _things(capability: str, had: Sequence[ConnectionShown]) -> tuple[str | None, ...]:
    """Every thing a call of ``capability`` could have, among the connections the hub has."""
    if capability == TEXT_CAPABILITY:
        return tuple(
            dict.fromkeys(
                (
                    OWN_CHAT_CONNECTION,
                    *(connection_key(one.place) for one in had if takes_text(one.place)),
                )
            )
        )
    if capability == EMAIL_CAPABILITY:
        return tuple(
            dict.fromkeys(
                connection_key(one.place) for one in had if one.account == EMAIL_ACCOUNT_KIND
            )
        )
    return (None,)


def capabilities_it_could_use(
    authority: WorkAuthority,
    declarations: Sequence[ToolDefinition],
    *,
    had: Sequence[ConnectionShown],
    own_place: bool,
    tickets: Sequence[Ticket] = (),
) -> frozenset[str]:
    """The capabilities a work's authority could use, by name (ADR-0368 §8:1).

    A capability where a call of one of its declarations, on some thing such a call could
    have among the connections the hub has, could run (:func:`could_allow`; no record is
    read, ADR-0381 §6:4); ``send_text`` wherever the work has a place its own input came
    from, which the check would not reach (ADR-0367 §4:7); and the capability of each
    ticket it holds that could run its call (:func:`ticket_could_run`).

    Args:
        authority: What the work's calls are checked against.
        declarations: Every declaration the hub offers.
        had: The connections the hub has, as the Connections section was built, before
            anything filtered it.
        own_place: Whether the work has a place one of its own inputs came from.
        tickets: The tickets the work holds.

    Returns:
        Each capability it could use.
    """
    usable: set[str] = set()
    for capability, tools in _by_capability(declarations).items():
        if capability == TEXT_CAPABILITY and own_place:
            usable.add(capability)
            continue
        if any(
            could_allow(authority, tool, thing=thing)
            for tool in tools
            for thing in _things(capability, had)
        ):
            usable.add(capability)
    usable.update(
        current_name(str(one.request.call.tool.capability))
        for one in tickets
        if ticket_could_run(authority, one)
    )
    return frozenset(usable)


@dataclass(frozen=True, slots=True)
class CouldUse:
    """The connections a work's authority could use, read for the section and the search.

    A place is shown where one of the work's own inputs came from it, or where it is in a
    connection the work could use. A connection on which no call of any declared capability
    is made at all, such as an event's place, offers nothing the check could refuse: it is
    left as it is shown without a filter, an item naming it by ``where`` included.

    Attributes:
        connections: Each connection it could use, keyed by :func:`connection_key`.
        own: Each place one of its own inputs came from, which it could use whatever the
            check would make of a call into it (ADR-0367 §4:7).
        refused: Each connection, by key, on which calls are made but none of the work's
            could run: those it may not be shown.
    """

    connections: frozenset[str]
    own: frozenset[str]
    refused: frozenset[str] = frozenset()

    def shows(self, place: str) -> bool:
        """Whether the place may be shown to the work."""
        return place in self.own or connection_key(place) not in self.refused


def _acting_in(
    entry: ConnectionShown, accounts: Mapping[str, str]
) -> tuple[frozenset[str], str | None]:
    """The capabilities whose calls are on ``entry``, and the thing such a call has."""
    key = connection_key(entry.place)
    if takes_text(entry.place):
        return frozenset({TEXT_CAPABILITY}), key
    if entry.account == EMAIL_ACCOUNT_KIND:
        return frozenset({EMAIL_CAPABILITY}), key
    if entry.account is not None:
        named = accounts.get(entry.account)
        return (frozenset() if named is None else frozenset({named})), None
    if key == SCHEDULE_CONNECTION:
        return TASK_SCHEDULER_CAPABILITIES, None
    if key == APPROVALS_CONNECTION:
        return APPROVAL_CAPABILITIES, None
    return frozenset(), None


def connections_it_could_use(  # noqa: PLR0913 — the authority, what the hub has, and each reading a connection takes
    authority: WorkAuthority,
    had: Sequence[ConnectionShown],
    *,
    declarations: Sequence[ToolDefinition],
    accounts: Mapping[str, str],
    own: Collection[str],
    whose: Mapping[str, str],
    tickets: Sequence[Ticket] = (),
) -> CouldUse:
    """The connections a work's authority could use (ADR-0368 §8:2, ADR-0381 §6:3).

    Each connection the hub has on which some call of the work could run
    (:func:`could_allow`), or which a ticket it holds could run its call on
    (:func:`ticket_could_run`), each record read as ``whose`` hands it in; the system's own
    chat weighed whether or not a conversation of it is listed, since a search finds them;
    and each place its own input came from.

    Args:
        authority: What the work's calls are checked against.
        had: The connections the hub has, as the Connections section was built.
        declarations: Every declaration the hub offers, ``send_text``'s included.
        accounts: For each account kind whose calls carry no thing, the capability its
            calls are made under, such as the search account's search.
        own: Each place one of the work's own inputs came from.
        whose: The person each connection's record names, as read; a connection missing
            from it has no record (ADR-0381 §5:1).
        tickets: The tickets the work holds.

    Returns:
        What the work could use, and what it may not be shown.
    """
    tools = _by_capability((*declarations, TEXT_CALL))
    acted_on: dict[str, tuple[frozenset[str], str | None]] = {
        OWN_CHAT_CONNECTION: (frozenset({TEXT_CAPABILITY}), OWN_CHAT_CONNECTION)
    }
    for entry in had:
        capabilities, thing = _acting_in(entry, accounts)
        declared = frozenset(one for one in capabilities if one in tools)
        if declared:
            acted_on.setdefault(connection_key(entry.place), (declared, thing))
    usable = {
        key
        for key, (capabilities, thing) in acted_on.items()
        if any(
            could_allow(authority, tool, thing=thing, whose=whose)
            for capability in sorted(capabilities)
            for tool in tools[capability]
        )
    }
    for ticket in tickets:
        if ticket_could_run(authority, ticket, whose=whose):
            usable.update(_ticketed(ticket, acted_on))
    return CouldUse(
        connections=frozenset(usable),
        own=frozenset(own),
        refused=frozenset(acted_on) - usable,
    )


def _ticketed(
    ticket: Ticket, acted_on: Mapping[str, tuple[frozenset[str], str | None]]
) -> set[str]:
    """The connections a ticket's call is on: its thing, or each its capability acts in."""
    call = ticket.request.call
    capability = current_name(str(call.tool.capability))
    thing = call_thing(str(call.tool.capability), binding=call.binding)
    if thing is not None:
        return {thing}
    return {key for key, (capabilities, _) in acted_on.items() if capability in capabilities}


class _Asked(Mapping[str, str]):
    """A mapping holding no record, which notes each connection a reading asks about."""

    def __init__(self) -> None:
        self.asked: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.asked.add(key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def records_it_needs(  # noqa: PLR0913 — as connections_it_could_use takes them
    authority: WorkAuthority,
    had: Sequence[ConnectionShown],
    *,
    declarations: Sequence[ToolDefinition],
    accounts: Mapping[str, str],
    own: Collection[str],
    tickets: Sequence[Ticket] = (),
) -> frozenset[str]:
    """The connections whose records :func:`connections_it_could_use` would read.

    Only those on which an outcome needs the yes of whoever the call's thing belongs to,
    the one outcome that reads a record (ADR-0381 §6:1, §6:3); none where every outcome is
    decided without one, so a caller reads only these.
    """
    asked = _Asked()
    connections_it_could_use(
        authority,
        had,
        declarations=declarations,
        accounts=accounts,
        own=own,
        whose=asked,
        tickets=tickets,
    )
    return frozenset(asked.asked)
