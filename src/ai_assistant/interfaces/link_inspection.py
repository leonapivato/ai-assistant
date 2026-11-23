"""Presentation for the linked-accounts commands (ADR-0373 §2, §3).

The command line's view of the owner's linked accounts: each account the hub knows is
the owner's, how sure each makes the hub, the lowerings the owner made on it, and what a
lowering or a withdrawal did. **Rendering only**: which links stand, each kind's most and
each link's level are the hub's (§3:2), so this module states what it answered and
computes none of it. The command line is the only caller of the three members in this
milestone (§4:6).

**Every value the engine supplies is escaped** by
:func:`~ai_assistant.interfaces.story_inspection.escaped` and printed with markup off,
so an account identifier carrying a line break, an ANSI escape or a Rich tag cannot pose
as a line this adapter wrote. Ids are quoted as a shell takes them, so each can be pasted
into the command that acts on it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LowerLinkOutcome,
    LowerLinkRefusal,
    WithdrawLoweringOutcome,
)
from ai_assistant.interfaces.story_inspection import quoted

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import Console

    from ai_assistant.core.types import (
        LinkedAccount,
        LowerLinkResult,
        StandingLowering,
        WithdrawLoweringResult,
    )

#: What the listing says where the owner has no linked account.
NONE_LINKED: Final = "You have no linked accounts."

#: How to act on what the listing shows, said once after it.
HOW_TO_ACT: Final = (
    "Lower one with 'assistant links lower <link id> --level <level>', and withdraw a "
    "lowering with 'assistant links withdraw <lowering id>'."
)


def _print(console: Console, text: str) -> None:
    console.print(text, markup=False, emoji=False, highlight=False, soft_wrap=True)


def _maker(by: str) -> str:
    """Whose a lowering is: ``you`` for the owner's, which every one is today (§4:3)."""
    return "you" if by == OWNER_PERSON_ID else quoted(by)


def lowering_text(lowering: StandingLowering) -> str:
    """One standing lowering: its id, the level it lowers to, and who made it."""
    return (
        f"Lowering {quoted(lowering.id)}: to {lowering.level.value}, made by {_maker(lowering.by)}"
    )


def entry_lines(entry: LinkedAccount) -> list[str]:
    """One linked account as the listing shows it (§3:1), and no more.

    Its link's id, the account (its kind and identifier), the level the hub computed
    with the most its kind gives, and each lowering that stands on it.
    """
    lines = [
        f"Link {quoted(entry.link_id)}: {quoted(entry.account.kind)} account "
        f"{quoted(entry.account.identifier)}",
        f"  Level: {entry.level.value} (its kind gives at most {entry.most.value})",
    ]
    lines.extend(f"  {lowering_text(one)}" for one in entry.lowerings)
    return lines


def render_listing(console: Console, entries: Sequence[LinkedAccount]) -> None:
    """The owner's linked accounts, in the order the hub answered, which binds nothing."""
    if not entries:
        _print(console, NONE_LINKED)
        return
    _print(console, "\n".join(line for one in entries for line in entry_lines(one)))
    _print(console, HOW_TO_ACT)


def lowered_text(link_id: str, result: LowerLinkResult) -> tuple[bool, str]:
    """Say what ``lower_link`` did, and whether it did what was asked.

    Args:
        link_id: The link the owner named, as sent.
        result: The hub's answer.

    Returns:
        ``True`` where the link now stands lowered as asked (``lowered`` or
        ``unchanged``), ``False`` where it was refused; and the sentence saying so.
    """
    match result.outcome:
        case LowerLinkOutcome.LOWERED:
            return True, "Lowered. The lowering stands until you withdraw it."
        case LowerLinkOutcome.UNCHANGED:
            return True, "Unchanged: you had already lowered this link to that level."
        case LowerLinkOutcome.REFUSED:
            return False, _refusal_text(link_id, result.refusal)
        case unreachable:
            assert_never(unreachable)


def _refusal_text(link_id: str, refusal: LowerLinkRefusal | None) -> str:
    match refusal:
        case LowerLinkRefusal.UNKNOWN_LINK:
            return (
                f"Refused: none of your linked accounts has the link id {quoted(link_id)}. "
                "Nothing was changed."
            )
        case LowerLinkRefusal.NOT_A_LOWERING:
            return (
                "Refused: that level is not below the most this account's kind gives, so "
                "it would lower nothing. Nothing was changed."
            )
        case None:
            return "Refused. Nothing was changed."
        case unreachable:
            assert_never(unreachable)


def render_lowered(console: Console, link_id: str, result: LowerLinkResult) -> bool:
    """Say what ``lower_link`` did, then the link as it now stands.

    Returns:
        Whether the link stands lowered as asked.
    """
    done, said = lowered_text(link_id, result)
    _print(console, said)
    if result.entry is not None:
        _print(console, "\n".join(entry_lines(result.entry)))
    return done


def withdrawn_text(lowering_id: str, result: WithdrawLoweringResult) -> str:
    """Say what ``withdraw_lowering`` did. Neither outcome is an error (§2:6)."""
    match result.outcome:
        case WithdrawLoweringOutcome.WITHDRAWN:
            return "Withdrawn. The lowering no longer stands."
        case WithdrawLoweringOutcome.NOT_STANDING:
            return (
                f"No lowering with the id {quoted(lowering_id)} stands on your linked "
                "accounts, so nothing was changed."
            )
        case unreachable:
            assert_never(unreachable)


def render_withdrawn(console: Console, lowering_id: str, result: WithdrawLoweringResult) -> None:
    """Say what ``withdraw_lowering`` did, then the link as it now stands."""
    _print(console, withdrawn_text(lowering_id, result))
    if result.entry is not None:
        _print(console, "\n".join(entry_lines(result.entry)))
