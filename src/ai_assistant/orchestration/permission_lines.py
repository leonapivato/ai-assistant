"""The owner's permission lines: the listing, a grant, a limit and a removal (ADR-0376 §4, §5).

``AssistantEngine``'s four members for lines, answered here over the line store
(:class:`~ai_assistant.core.protocols.PermissionLineStore`), the tools the running hub
declares and the connections it has, so the engine and the canonical fake answer them
alike. Neither decides any of it itself.

**What the listing shows** (§4:2, §5:1): each standing made line, with its identifier and
its maker, then the default line of each declared tool that holds one (ADR-0380), with the
tool's id: a grant to anyone, its tool's capability, no thing, the declaration's how and
bar, no condition (§3:1). A tool whose declaration holds no default grant has no default
line, and lists none.

**The order of a making's outcomes is §4:5's.** This module decides the four refusals,
which need what the hub knows and the store does not: ``unknown_who`` where the who is
neither the owner's identity nor anyone (§2:1); ``unknown_action`` where no declared tool
has the capability; ``no_thing`` where a thing is given and the action's calls have none
(§2:3); and ``unknown_connection`` where a thing or a condition names no connection a line
may name that the hub has (§2:4). It hands the rest to the store's ``record_making``,
which decides ``unchanged`` against ``made`` in one atomic step with its write, so no other
making can come between the decision and the write.

**A call's thing** is derived for ``send_text`` and ``send_email`` alone, as the check's
:func:`~ai_assistant.orchestration.permission_check.call_thing` derives it; every other
capability's calls have none (§2:3), so a line about one names no thing.

**The connections the hub has** are those it holds as it starts that a line may name
(:func:`nameable_connections`): each connection ADR-0381 §2:1 records, less the schedule and
the approvals, which no line names (§2:4).

**Every line these members make or remove is the owner's act** (§6:3): ``by`` is
:data:`~ai_assistant.core.types.OWNER_PERSON_ID`, which no caller supplies. **With no line
store** the hub holds no made line: the listing shows the default lines alone, a removal
names no standing line, and a making its refusals have not answered raises the store's
error, as a store that cannot be written does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.errors import PermissionLineStoreError
from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    LINE_WHO,
    OWNER_PERSON_ID,
    LineConnection,
    LineMakingKind,
    LineParts,
    LineRemovalKind,
    MakeLineOutcome,
    MakeLineRefusal,
    MakeLineResult,
    PermissionLineEntry,
    PermissionLineKind,
    RemoveLineOutcome,
    RemoveLineResult,
    ThingKind,
    grant_bar,
    grant_how,
)
from ai_assistant.orchestration.message_tools import EMAIL_CAPABILITY, TEXT_CAPABILITY
from ai_assistant.orchestration.payloads import identifier

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from ai_assistant.core.protocols import PermissionLineStore
    from ai_assistant.core.types import (
        GrantHow,
        PermissionLine,
        Sureness,
        ThingKey,
        ToolDefinition,
    )

__all__ = [
    "THING_CAPABILITIES",
    "LineArguments",
    "grant_arguments",
    "limit_arguments",
    "made_entry",
    "make_line",
    "nameable_connections",
    "permission_lines",
    "remove_line",
]

#: The capabilities whose calls have a thing (ADR-0376 §2:3): ``send_text``'s connection
#: and ``send_email``'s account. Every other capability declared on the day ADR-0376 was
#: ratified has none, and a capability added since has none until a ratified decision or
#: its change says which value names its connection.
THING_CAPABILITIES: Final = frozenset({TEXT_CAPABILITY, EMAIL_CAPABILITY})

#: A connection as a line names it (ADR-0376 §2:4).
_LINE_CONNECTION: Final = TypeAdapter[str](LineConnection)


def nameable_connections(held: Iterable[ThingKey]) -> frozenset[str]:
    """The connections a line may name that the hub has (ADR-0376 §2:4, §4:5).

    Each connection among the things the hub holds as it starts (ADR-0381 §2:1), spelled
    as a line spells one, less the schedule and the approvals, which a record names and no
    line does. A source is no connection.

    Args:
        held: The things the hub holds, as their records are keyed.

    Returns:
        Their spellings.
    """
    nameable: set[str] = set()
    for one in held:
        if one.kind is not ThingKind.CONNECTION:
            continue
        try:
            nameable.add(_LINE_CONNECTION.validate_python(one.identifier))
        except ValidationError:
            continue
    return frozenset(nameable)


def made_entry(line: PermissionLine) -> PermissionLineEntry:
    """A standing made line as the listing shows it (ADR-0376 §5:1), and no more.

    Args:
        line: The line, as the store keeps it.

    Returns:
        Its entry: its parts, its identifier and its maker.
    """
    return PermissionLineEntry(
        kind=line.kind,
        who=line.who,
        action=line.action,
        thing=line.thing,
        how=line.how,
        bar=line.bar,
        condition=line.condition,
        line_id=line.id,
        made_by=line.made_by,
    )


def _default_entries(tools: Sequence[ToolDefinition]) -> list[PermissionLineEntry]:
    """Each declared tool's default line, with its tool's id (ADR-0376 §3:1, §5:1)."""
    entries: list[PermissionLineEntry] = []
    for tool in tools:
        grant = tool.default_grant
        if grant is None:
            continue
        entries.append(
            PermissionLineEntry(
                kind=PermissionLineKind.GRANT,
                who=ANYONE_GROUP_ID,
                action=tool.capability,
                how=grant.how,
                bar=grant.bar,
                tool_id=tool.id,
            )
        )
    return entries


async def permission_lines(
    store: PermissionLineStore | None, tools: Sequence[ToolDefinition]
) -> tuple[PermissionLineEntry, ...]:
    """Every line that stands, one entry each (ADR-0376 §4:2, §5).

    Args:
        store: The line store, or ``None`` where the hub holds none.
        tools: Every tool the running hub declares, each once.

    Returns:
        The made lines, in the order made, then the default lines, in ``tools``' order;
        which is no contractual order.

    Raises:
        PermissionLineStoreError: If the store cannot be read.
    """
    made = () if store is None else await store.standing()
    return (*(made_entry(one) for one in made), *_default_entries(tools))


def _refusal(
    line: LineArguments, *, tools: Sequence[ToolDefinition], connections: frozenset[str]
) -> MakeLineRefusal | None:
    """The first of §4:5's four refusals that applies, or ``None`` where none does."""
    if line.who not in LINE_WHO:
        return MakeLineRefusal.UNKNOWN_WHO
    if all(str(one.capability) != line.action for one in tools):
        return MakeLineRefusal.UNKNOWN_ACTION
    if line.thing is not None and line.action not in THING_CAPABILITIES:
        return MakeLineRefusal.NO_THING
    if any(one is not None and one not in connections for one in (line.thing, line.condition)):
        return MakeLineRefusal.UNKNOWN_CONNECTION
    return None


@dataclass(frozen=True, slots=True)
class LineArguments:
    """A making's arguments, each validated as the surface takes it (ADR-0376 §4:7).

    Attributes:
        kind: Grant or limit: which member was called.
        who: The who, stripped.
        action: The action, stripped.
        thing: The thing, stripped, or ``None``.
        how: For a grant, how it allows; ``None`` for a limit.
        bar: For a grant, its bar; ``None`` for a limit.
        condition: For a grant, its condition, stripped, or ``None``.
    """

    kind: PermissionLineKind
    who: str
    action: str
    thing: str | None = None
    how: GrantHow | None = None
    bar: Sureness | None = None
    condition: str | None = None

    def arguments(self) -> dict[str, object]:
        """The member's arguments, named as its parameters are, for measuring the call."""
        named: dict[str, object] = {"who": self.who, "action": self.action, "thing": self.thing}
        if self.kind is PermissionLineKind.GRANT:
            named |= {"how": self.how, "bar": self.bar, "condition": self.condition}
        return named


def _optional(value: str | None, *, name: str) -> str | None:
    return None if value is None else identifier(value, name=name)


def grant_arguments(  # noqa: PLR0913 — ADR-0376 §4:3's six parts of a grant
    *,
    who: str,
    action: str,
    how: object,
    bar: object,
    thing: str | None,
    condition: str | None,
) -> LineArguments:
    """``make_grant``'s arguments, refused before any I/O where malformed (ADR-0376 §4:7).

    Raises:
        ValueError: If an identifier is blank or unwritable, ``how`` is not one of its two
            values, or ``bar`` is not one of the four.
    """
    return LineArguments(
        kind=PermissionLineKind.GRANT,
        who=identifier(who, name="who"),
        action=identifier(action, name="action"),
        thing=_optional(thing, name="thing"),
        how=grant_how(how),
        bar=grant_bar(bar),
        condition=_optional(condition, name="condition"),
    )


def limit_arguments(*, who: str, action: str, thing: str | None) -> LineArguments:
    """``make_limit``'s arguments, refused before any I/O where malformed (ADR-0376 §4:7).

    Raises:
        ValueError: If an identifier is blank or unwritable.
    """
    return LineArguments(
        kind=PermissionLineKind.LIMIT,
        who=identifier(who, name="who"),
        action=identifier(action, name="action"),
        thing=_optional(thing, name="thing"),
    )


async def make_line(
    store: PermissionLineStore | None,
    line: LineArguments,
    *,
    tools: Sequence[ToolDefinition],
    connections: frozenset[str],
) -> MakeLineResult:
    """Make a grant or a limit, by the owner's act (ADR-0376 §4:3 to §4:5).

    Args:
        store: The line store, or ``None`` where the hub holds none.
        line: The making's arguments, validated.
        tools: Every tool the running hub declares.
        connections: The connections a line may name that the hub has.

    Returns:
        ``refused`` with the first of §4:5's four reasons that applies; ``unchanged``
        with the standing line; or ``made`` with the line as the store recorded it.

    Raises:
        PermissionLineStoreError: If there is no store, or it cannot be read or written.
    """
    refusal = _refusal(line, tools=tools, connections=connections)
    if refusal is not None:
        return MakeLineResult(outcome=MakeLineOutcome.REFUSED, refusal=refusal)
    if store is None:
        msg = "this hub holds no line store, so no line can be made"
        raise PermissionLineStoreError(msg)
    # Each part is now one a line may carry: the who is in LINE_WHO, the action a declared
    # capability, and each connection one a line may name.
    parts = LineParts(
        kind=line.kind,
        who=line.who,
        action=line.action,
        thing=line.thing,
        how=line.how,
        bar=line.bar,
        condition=line.condition,
    )
    making = await store.record_making(parts, by=OWNER_PERSON_ID)
    outcome = (
        MakeLineOutcome.MADE if making.kind is LineMakingKind.MADE else MakeLineOutcome.UNCHANGED
    )
    return MakeLineResult(outcome=outcome, line=making.line)


async def remove_line(store: PermissionLineStore | None, line_id: str) -> RemoveLineResult:
    """Remove a standing made line, by the owner's act (ADR-0376 §4:6, §6:3).

    The caller has validated the argument.

    Args:
        store: The line store, or ``None`` where the hub holds none.
        line_id: The line, by its identifier.

    Returns:
        ``removed`` with the line as the store now keeps it, or ``not_standing`` where no
        standing made line has that identifier.

    Raises:
        PermissionLineStoreError: If the store cannot be read or written.
    """
    if store is None:
        return RemoveLineResult(outcome=RemoveLineOutcome.NOT_STANDING)
    removal = await store.record_removal(line_id, by=OWNER_PERSON_ID)
    if removal.kind is LineRemovalKind.NOT_STANDING:
        return RemoveLineResult(outcome=RemoveLineOutcome.NOT_STANDING)
    return RemoveLineResult(outcome=RemoveLineOutcome.REMOVED, line=removal.line)
