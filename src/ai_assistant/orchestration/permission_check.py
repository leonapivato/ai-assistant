"""The check: a call's outcome against the lines, for one person at one level.

ADR-0367 §4:1 has code check every call a work makes against lines, with no model, before it
runs, for the person whose authority the work carries, at its level. ADR-0379 §2 gives the
order that joins the lines that cover a call into exactly one of §3:1's six outcomes, and
ADR-0376 §2 says what a line names and when it covers a call. This module is that check,
and **nothing else**: a function of its arguments, with no model, no store and no clock of
its own, so the authorizer, which joins it to ADR-0306 §4:1's checks first (ADR-0367 §4:5),
reads the standing lines once and hands them in.

**Which lines it weighs** (:func:`check_call`): the standing made lines the line store
holds (ADR-0367 §3:6), and the default line the call's declaration holds, where it holds
one (ADR-0376 §3:1, §3:2; ADR-0380 §2:2): a line to anyone, the tool's capability, no
thing, the declaration's how and bar, no condition, made by no one.

**When a line covers a call** (ADR-0376 §2:7): its who includes whom the check runs for,
its action is the call's capability, its thing is none or the call's thing (§2:5), and its
condition, where it has one, is the one connection the work's senders' inputs all came by
(§2:6, ADR-0368 §4:2, §6:4). A line's bar is not part of it. No line covers a call for no
one (ADR-0368 §7:5); a member of anyone alone is covered by lines to anyone only (§7:2).

**Which decides** (ADR-0379 §2), the first that applies: a covering limit; a grant that
allows and applies at the level, the outcome naming the earliest made one among them, or
none where only the default allows; a grant that asks and applies; a covering grant that
applies at no level reached, a shortfall at the least level at which one would; and no
grant. A grant applies where the level is at or above its bar (ADR-0367 §5:1), and a
grant to a named person only at weak or above (§5:2).

**A call's thing** (:func:`call_thing`, ADR-0376 §2:3): for ``send_text``, the connection
its place is in, the system's own chat as one connection; for ``send_email``, the account
connection its ``from`` names, which planning has written as the person's own account and
the hub has bound the call to (:class:`~ai_assistant.core.types.EgressBinding`'s account);
for every other capability, none.

**Whom it runs for** (:class:`CheckSubject`) is handed to the authorizer, which decides
none of it (ADR-0368 §7, :func:`~ai_assistant.orchestration.work_facts.check_runs_for`).

**The level a request's call needs** (:func:`level_needed`, ADR-0377 §3:2): the least level
at which this check, over the standing lines, finds a grant covering and applying to the
call for the request's person, a grant that allows with approval counted alike; weak where
that is none or where no grant covers it. It is what a tap on the request's card must reach
to answer it (§3:1), on the line and on the hub page alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWN_CHAT_CONNECTION,
    CallCheck,
    CallCheckKind,
    CheckedFor,
    CheckedForKind,
    CheckOutcome,
    CheckOutcomeKind,
    CheckRun,
    EgressBinding,
    GrantHow,
    LineConnection,
    PermissionLineKind,
    Sureness,
)
from ai_assistant.orchestration.channel_kinds import ACCOUNT_PREFIX
from ai_assistant.orchestration.message_tools import EMAIL_CAPABILITY, TEXT_CAPABILITY

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from ai_assistant.core.types import PermissionLine, RequestedCall, ToolDefinition

__all__ = [
    "CheckSubject",
    "call_thing",
    "check_call",
    "checked",
    "level_needed",
    "place_connection",
]

#: The hub chat's channel type, whose conversations are one connection (ADR-0376 §2:4).
_OWN_CHAT_KIND: Final = OWN_CHAT_CONNECTION

#: A connection as a line names it, which a call's thing is spelled as (ADR-0376 §2:4).
_LINE_CONNECTION: Final = TypeAdapter[str](LineConnection)

#: The outcomes at which the check finds a grant covering a call and applying at the
#: level, one that allows with approval counted (ADR-0377 §3:2, ADR-0379 §2:3, §2:4).
_A_GRANT_APPLIES: Final = frozenset(
    {
        CheckOutcomeKind.ALLOWED_ON_NO_LINE,
        CheckOutcomeKind.ALLOWED_ON_MADE_GRANT,
        CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL,
    }
)

#: The levels, least first, that :func:`level_needed` tries in turn.
_LEVELS: Final = tuple(sorted(Sureness, key=lambda level: level.rank))


@dataclass(frozen=True, slots=True)
class CheckSubject:
    """Whom the check runs for in a work, at what level, and where a condition is met.

    The authorizer is handed it and decides none of it (ADR-0367 §4:1, ADR-0368 §7).

    Attributes:
        runs: Each one the check runs for, at the level it runs at (ADR-0368 §7's table):
            one, save a work of several senders, which it runs for each of (§7:3). No one,
            at none, by default: a round handed nothing holds no grant.
        met: The one connection a grant's condition naming a connection is met for in the
            work (ADR-0368 §4:2, §6:4), or ``None`` where no one connection is.

    Raises:
        ValueError: If it runs for no one at all.
    """

    runs: tuple[CheckedFor, ...] = field(default=(CheckedFor.no_one(),))
    met: str | None = None

    def __post_init__(self) -> None:
        """It runs for at least one."""
        if not self.runs:
            msg = "the check runs for someone, or for no one, but always for one"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class _Line:
    """A line as the check weighs it: a made one, or a tool's default."""

    kind: PermissionLineKind
    who: str
    thing: str | None
    how: GrantHow | None
    bar: Sureness | None
    condition: str | None
    made: tuple[datetime, str] | None
    """Where the store recorded it: when, then its identifier; ``None`` for a default."""

    @property
    def line_id(self) -> str | None:
        return None if self.made is None else self.made[1]


def _made(lines: Iterable[PermissionLine], capability: str) -> list[_Line]:
    """The standing made lines naming ``capability``, as the check weighs them."""
    return [
        _Line(
            kind=one.kind,
            who=str(one.who),
            thing=one.thing,
            how=one.how,
            bar=one.bar,
            condition=one.condition,
            made=(one.made_at, str(one.id)),
        )
        for one in lines
        if one.standing and str(one.action) == capability
    ]


def _default(tool: ToolDefinition) -> list[_Line]:
    """The tool's default line, where its declaration holds one (ADR-0376 §3:1, ADR-0380)."""
    grant = tool.default_grant
    if grant is None:
        return []
    return [
        _Line(
            kind=PermissionLineKind.GRANT,
            who=ANYONE_GROUP_ID,
            thing=None,
            how=grant.how,
            bar=grant.bar,
            condition=None,
            made=None,
        )
    ]


def _includes(who: str, checked_for: CheckedFor) -> bool:
    """Whether a line's who includes whom the check runs for (ADR-0367 §2:3, ADR-0368 §7)."""
    if checked_for.kind is CheckedForKind.NO_ONE:
        return False
    if who == ANYONE_GROUP_ID:
        return True
    return checked_for.kind is CheckedForKind.PERSON and who == checked_for.person


def _covers(line: _Line, *, thing: str | None, checked_for: CheckedFor, met: str | None) -> bool:
    """ADR-0376 §2:7, its action already matched: who, thing and condition."""
    return (
        _includes(line.who, checked_for)
        and (line.thing is None or line.thing == thing)
        and (line.condition is None or line.condition == met)
    )


def _least_level(line: _Line) -> Sureness:
    """The least level at which a grant applies (ADR-0367 §5:1, §5:2, ADR-0379 §2:5)."""
    bar = Sureness.NONE if line.bar is None else line.bar
    if line.who == ANYONE_GROUP_ID:
        return bar
    return max(bar, Sureness.WEAK)


def _first(lines: Iterable[_Line]) -> str | None:
    """The made line recorded first, of two at one moment the identifier sorting first (§2:8)."""
    made = sorted(one.made for one in lines if one.made is not None)
    return made[0][1] if made else None


def check_call(
    lines: Sequence[PermissionLine],
    tool: ToolDefinition,
    *,
    thing: str | None,
    checked_for: CheckedFor,
    met: str | None,
) -> CheckOutcome:
    """The check's outcome for one call, for one person at one level (ADR-0379 §2, §3:1).

    Args:
        lines: The standing made lines, as the line store lists them; a removed one is
            weighed as no line.
        tool: The declaration the call was selected under, whose default grant is one of
            the lines weighed.
        thing: The call's thing (:func:`call_thing`), or ``None``.
        checked_for: Whom the check runs for, and the level it runs at.
        met: The one connection a grant's condition is met for, or ``None``.

    Returns:
        Exactly one of the six outcomes, carrying what it carries.
    """
    capability = str(tool.capability)
    covering = [
        one
        for one in (*_made(lines, capability), *_default(tool))
        if _covers(one, thing=thing, checked_for=checked_for, met=met)
    ]
    limits = [one for one in covering if one.kind is PermissionLineKind.LIMIT]
    if limits:
        return CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_LIMIT, line=_first(limits))
    grants = [one for one in covering if one.kind is PermissionLineKind.GRANT]
    level = checked_for.level
    applying = [one for one in grants if level >= _least_level(one)]
    allowing = [one for one in applying if one.how is GrantHow.ALLOWED]
    if allowing:
        named = _first(allowing)
        if named is None:
            return CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_NO_LINE)
        return CheckOutcome(kind=CheckOutcomeKind.ALLOWED_ON_MADE_GRANT, line=named)
    if applying:
        return CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_WITH_APPROVAL)
    if grants:
        bar = min(_least_level(one) for one in grants)
        return CheckOutcome(kind=CheckOutcomeKind.NEEDS_YES_SHORTFALL, bar=bar)
    return CheckOutcome(kind=CheckOutcomeKind.NOT_DONE_NO_GRANT)


def checked(
    lines: Sequence[PermissionLine],
    tool: ToolDefinition,
    *,
    thing: str | None,
    subject: CheckSubject,
) -> CallCheck:
    """The check run for each one ``subject`` names, recorded whole (ADR-0379 §3:2).

    Args:
        lines: The standing made lines.
        tool: The declaration the call was selected under.
        thing: The call's thing, or ``None``.
        subject: Whom the check runs for, and where a condition is met.

    Returns:
        The call's check, an outcome for each one it ran for, in ``subject``'s order.
    """
    return CallCheck(
        kind=CallCheckKind.CHECKED,
        runs=tuple(
            CheckRun(
                checked_for=one,
                outcome=check_call(lines, tool, thing=thing, checked_for=one, met=subject.met),
            )
            for one in subject.runs
        ),
    )


def place_connection(place: str | None) -> str | None:
    """The connection a place is in, as a line names it (ADR-0376 §2:4).

    The system's own chat is one connection, whichever conversation; any other place is the
    connection it names. A place no line can name, such as the schedule, is in none.

    Args:
        place: The place, as an effect record names it, ``<channel type>:<instance id>``.

    Returns:
        The connection, or ``None``.
    """
    if place is None:
        return None
    kind = place.partition(":")[0]
    if kind == _OWN_CHAT_KIND:
        return OWN_CHAT_CONNECTION
    try:
        return _LINE_CONNECTION.validate_python(place)
    except ValidationError:
        return None


def call_thing(
    capability: str, *, binding: EgressBinding | None = None, place: str | None = None
) -> str | None:
    """A call's thing, derived in code from the call (ADR-0376 §2:3).

    For ``send_text``, the connection its place is in (:func:`place_connection`). For
    ``send_email``, the account connection its ``from`` names: planning writes the
    person's own account there for the account an ``L`` label named (ADR-0364 §9:11), and
    the hub binds the call to that account, one tool per connected account (ADR-0148 §6),
    so the account is read from the call's binding, ``account:`` and its reference. For
    every other capability, none.

    Args:
        capability: The call's capability.
        binding: The call's egress binding, where it has one.
        place: For a ``send_text`` call, the place it goes into.

    Returns:
        The connection, as a line names it, or ``None``.
    """
    if capability == TEXT_CAPABILITY:
        return place_connection(place)
    if capability == EMAIL_CAPABILITY and isinstance(binding, EgressBinding):
        try:
            return _LINE_CONNECTION.validate_python(f"{ACCOUNT_PREFIX}{binding.account.reference}")
        except ValidationError:
            return None
    return None


def level_needed(lines: Sequence[PermissionLine], call: RequestedCall, *, person: str) -> Sureness:
    """The level a tap must reach to answer a request for ``call`` (ADR-0377 §3:2).

    The least level at which :func:`check_call`, over ``lines`` and the call's declared
    default, finds a grant covering the call for ``person`` and applying at that level,
    counting one that allows with approval; and weak where that level is none or where no
    grant covers it. A shortfall's card needs its grant's bar (ADR-0367 §5:4), which is
    this same least level (ADR-0379 §2:5), so one computation serves every card.

    A limit is not weighed: it decides that the call is not done, at every level, and never
    which level a grant applies at (ADR-0379 §2:2). A ticket the tap grants is still checked
    when its call runs (ADR-0367 §5:5), and a limit refuses it there.

    The call is checked as a ticket's call is checked for its tapper: its thing derived
    from its values and its binding (:func:`call_thing`), and no connection met for a
    condition, since a tap arrives by none a condition names. So a tap that reaches the
    level this gives is not refused for its level when its ticket's call is checked,
    unless the lines change in between.

    Args:
        lines: The standing made lines, as the line store lists them, read when the tap
            lands; a removed one is weighed as no line.
        call: The request's call, as the request records it.
        person: The request's person.

    Returns:
        The level, never below weak.
    """
    grants = [one for one in lines if one.kind is PermissionLineKind.GRANT]
    tool = call.tool
    thing = call_thing(str(tool.capability), binding=call.binding)
    for level in _LEVELS:
        outcome = check_call(
            grants,
            tool,
            thing=thing,
            checked_for=CheckedFor.for_person(person, level),
            met=None,
        )
        if outcome.kind in _A_GRANT_APPLIES:
            return max(level, Sureness.WEAK)
    return Sureness.WEAK
