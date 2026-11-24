"""Presentation for the permission-line commands (ADR-0376 §4, §5).

The command line's view of the lines that stand: each line the owner made and each tool's
default line, and what a making or a removal did. **Rendering only**: which lines stand,
every default line and every outcome are the hub's, so this module states what it
answered and decides none of it. The command line is the only caller of the four members
in this milestone (§6:6).

**Every value the engine supplies is escaped** by
:func:`~ai_assistant.interfaces.story_inspection.escaped` and printed with markup off, so
a capability or a connection carrying a line break, an ANSI escape or a Rich tag cannot
pose as a line this adapter wrote. Ids, capabilities and connections are quoted as a
shell takes them, so each can be pasted into the command that acts on it.

**A line does not yet decide any call** (ADR-0367 §4:5): the check reads the lines and
its outcome is recorded beside today's rules, which still decide. :data:`NOT_YET_DECIDING`
says so, once, wherever a command could suggest otherwise; the change that switches the
check on removes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.types import (
    ANYONE_GROUP_ID,
    OWNER_PERSON_ID,
    GrantHow,
    MakeLineOutcome,
    MakeLineRefusal,
    PermissionLineKind,
    RemoveLineOutcome,
)
from ai_assistant.interfaces.story_inspection import quoted

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console

    from ai_assistant.core.types import (
        MakeLineResult,
        PermissionLine,
        PermissionLineEntry,
        RemoveLineResult,
        Sureness,
    )

#: The one sentence saying that lines do not decide calls yet (ADR-0367 §4:5).
NOT_YET_DECIDING: Final = (
    "Lines are recorded and listed, and do not decide any call until the release that "
    "switches the check on: today's rules still do."
)

#: How the owner names a connection, as a line's thing or condition (ADR-0376 §2:4).
CONNECTION_SPELLING: Final = (
    "Name a connection as a line does: 'conversation' for the hub chat, "
    "'telegram:<connection reference>/<chat id>' for the Telegram line, and "
    "'account:<reference>' for an account, as 'assistant connections' shows its reference."
)

#: What the listing says where no line stands.
NO_LINES: Final = "No line stands."

#: How to act on what the listing shows, said once after it.
HOW_TO_ACT: Final = (
    "Make one with 'assistant permissions grant' or 'assistant permissions limit', and "
    "remove one you made with 'assistant permissions remove <line id>'. A tool's default "
    "line cannot be removed: a limit narrows it, and a grant of your own allows more."
)

#: The words a command takes for the two people a line may name (ADR-0376 §2:1).
WHO_WORDS: Final = {"me": OWNER_PERSON_ID, "anyone": ANYONE_GROUP_ID}


def _print(console: Console, text: str) -> None:
    console.print(text, markup=False, emoji=False, highlight=False, soft_wrap=True)


def who_named(word: str) -> str:
    """The who a command sends for what the owner typed: ``me``, ``anyone``, or as typed.

    Anything but the two words is sent as typed, and the hub refuses it (§4:5).
    """
    return WHO_WORDS.get(word, word)


def _who(who: str) -> str:
    if who == OWNER_PERSON_ID:
        return "you"
    if who == ANYONE_GROUP_ID:
        return "anyone"
    return quoted(who)


def how_text(how: GrantHow, bar: Sureness) -> str:
    """How a grant allows, and from what level (ADR-0367 §3:1, §5:1)."""
    match how:
        case GrantHow.ALLOWED:
            allows = "allowed"
        case GrantHow.WITH_APPROVAL:
            allows = "allowed with approval"
        case unreachable:
            assert_never(unreachable)
    return f"{allows}, at {bar.value} or above"


def _parts(line: PermissionLineEntry | PermissionLine) -> list[str]:
    """A line's who, action, thing, how and bar, and condition, each where it has one."""
    lines = [f"  Who: {_who(line.who)}", f"  Action: {quoted(line.action)}"]
    if line.thing is not None:
        lines.append(f"  On: {quoted(line.thing)}")
    if line.how is not None and line.bar is not None:
        lines.append(f"  How: {how_text(line.how, line.bar)}")
    if line.condition is not None:
        lines.append(
            f"  Only when every message the work acts on came by: {quoted(line.condition)}"
        )
    return lines


def _kind(kind: PermissionLineKind) -> str:
    match kind:
        case PermissionLineKind.GRANT:
            return "Grant"
        case PermissionLineKind.LIMIT:
            return "Limit"
        case unreachable:
            assert_never(unreachable)


def entry_lines(entry: PermissionLineEntry) -> list[str]:
    """One line that stands as the listing shows it (ADR-0376 §5:1), and no more."""
    if entry.line_id is not None and entry.made_by is not None:
        head = f"{_kind(entry.kind)} {quoted(entry.line_id)}, made by {_who(entry.made_by)}"
    else:
        head = f"Default grant of tool {quoted(str(entry.tool_id))}"
    return [
        head,
        *_parts(entry),
    ]


def line_lines(line: PermissionLine) -> list[str]:
    """One made line as a making or a removal names it."""
    head = f"{_kind(line.kind)} {quoted(line.id)}, made by {_who(line.made_by)}"
    return [
        head,
        *_parts(line),
    ]


def render_listing(console: Console, entries: Sequence[PermissionLineEntry]) -> None:
    """Every line that stands, in the order the hub answered, which binds nothing."""
    if not entries:
        _print(console, NO_LINES)
    else:
        _print(console, "\n".join(line for one in entries for line in entry_lines(one)))
        _print(console, HOW_TO_ACT)
    _print(console, NOT_YET_DECIDING)


def made_text(result: MakeLineResult) -> tuple[bool, str]:
    """Say what ``make_grant`` or ``make_limit`` did, and whether the line now stands.

    Returns:
        ``True`` where the line stands (``made`` or ``unchanged``), ``False`` where it was
        refused; and the sentence saying so.
    """
    match result.outcome:
        case MakeLineOutcome.MADE:
            return True, "Made. The line stands until you remove it."
        case MakeLineOutcome.UNCHANGED:
            return True, "Unchanged: a line you made with exactly these parts already stands."
        case MakeLineOutcome.REFUSED:
            return False, _refusal_text(result.refusal)
        case unreachable:
            assert_never(unreachable)


def _refusal_text(refusal: MakeLineRefusal | None) -> str:
    match refusal:
        case MakeLineRefusal.UNKNOWN_WHO:
            said = "a line names you ('me') or 'anyone', and no one else yet"
        case MakeLineRefusal.UNKNOWN_ACTION:
            said = (
                "no tool this hub declares has that capability; 'assistant permissions "
                "list' shows each tool's default line, with its capability"
            )
        case MakeLineRefusal.NO_THING:
            said = "that capability's calls act through no connection, so a line names none"
        case MakeLineRefusal.UNKNOWN_CONNECTION:
            said = f"a connection you named is not one this hub has. {CONNECTION_SPELLING}"
        case None:
            said = "the hub gave no reason"
        case unreachable:
            assert_never(unreachable)
    return f"Refused: {said}. Nothing was changed."


def render_made(console: Console, result: MakeLineResult) -> bool:
    """Say what a making did, then the line as it stands.

    Returns:
        Whether the line stands.
    """
    stands, said = made_text(result)
    _print(console, said)
    if result.line is not None:
        _print(console, "\n".join(line_lines(result.line)))
    _print(console, NOT_YET_DECIDING)
    return stands


def removed_text(line_id: str, result: RemoveLineResult) -> str:
    """Say what ``remove_line`` did. Neither outcome is an error (§4:6)."""
    match result.outcome:
        case RemoveLineOutcome.REMOVED:
            return "Removed. The line no longer stands, and is kept as removed."
        case RemoveLineOutcome.NOT_STANDING:
            return f"No line you made with the id {quoted(line_id)} stands, so nothing was changed."
        case unreachable:
            assert_never(unreachable)


def render_removed(console: Console, line_id: str, result: RemoveLineResult) -> None:
    """Say what ``remove_line`` did, then the line it removed."""
    _print(console, removed_text(line_id, result))
    if result.line is not None:
        _print(console, "\n".join(line_lines(result.line)))
