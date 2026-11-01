"""Presentation for the person-model commands (ADR-0338 §8:1-§8:3).

The command line's half of the About you panel: the fields, the change log, what the
assistant keeps in mind with its fill and what it left out, the pins no longer current,
the style memories and the suggestions, and what each write did. Rendering only: the
slot's order and fill, what it left out and why, which pins are no longer current and
every wording shown are the engine's (ADR-0338 §4:8, §6), so this module states what it
answered and computes none of it.

**Every value the engine supplies is escaped** by
:func:`~ai_assistant.interfaces.story_inspection.escaped` and printed with markup off,
so a wording carrying a line break, an ANSI escape or a Rich tag cannot pose as a line
this adapter wrote. Ids are quoted as a shell takes them, so each can be pasted into
the command that acts on it.

**The words are the page's.** Each table here has a twin in the gateway's ``app.js``,
and ``tests/interfaces/gateway/test_bundle.py`` holds the two to one wording, so a
person reading their model in the browser and at the terminal reads the same sentences.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import (
    DEFAULT_ASSISTANT_NAME,
    LeftOutReason,
    PersonActHow,
    PersonModelEditRefusal,
    PersonModelRefusal,
    PersonModelWriteKind,
    ProfileField,
    SuggestionKind,
)
from ai_assistant.interfaces.story_inspection import escaped, quoted

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from rich.console import Console

    from ai_assistant.core.types import (
        KeptMemoryView,
        LeftOutMemory,
        PersonModelAct,
        PersonModelEdit,
        PersonModelView,
        ProfileChange,
        StalePinView,
        StyleMarkView,
        SuggestionView,
    )

#: What a hub whose person model is off says, as the panel says it (ADR-0338 §11:2).
OFF: Final = (
    "The person model is not switched on on this hub yet, so there is nothing here to "
    "show or change."
)

#: What a person-model read says where the hub holds no such person.
NO_PROFILE: Final = "I hold no profile for you."

#: What each field is called (ADR-0338 §3's table), as the panel calls it.
FIELD_WORDS: Final[Mapping[ProfileField, str]] = MappingProxyType(
    {
        ProfileField.NAME: "Your name",
        ProfileField.ADDRESS: "What I call you",
        ProfileField.ASSISTANT_NAME: "What you call me",
        ProfileField.TIME_ZONE: "Your time zone",
        ProfileField.LANGUAGE: "The language I write to you in",
    }
)

#: What an empty field means (ADR-0338 §3:9): not set, and where the table gives
#: emptiness a meaning, that meaning, never a default presented as the person's own.
UNSET_WORDS: Final[Mapping[ProfileField, str]] = MappingProxyType(
    {
        ProfileField.NAME: "Not set.",
        ProfileField.ADDRESS: "Not set.",
        ProfileField.ASSISTANT_NAME: f"Not set: I go by {DEFAULT_ASSISTANT_NAME}.",
        ProfileField.TIME_ZONE: "Not set: I use the hub's own time zone.",
        ProfileField.LANGUAGE: "Not set.",
    }
)

#: How a change to a field was made (ADR-0338 §3:5). A change made on the panel and one
#: made here are the same act, the engine's panel act, so the words name both.
HOW_WORDS: Final[Mapping[PersonActHow, str]] = MappingProxyType(
    {
        PersonActHow.PANEL: "by you, on the panel or the command line",
        PersonActHow.APPROVAL: "by your yes to my question",
        PersonActHow.SUGGESTION: "by accepting my suggestion",
        PersonActHow.SEED: "by the hub, when it was first set up",
    }
)

#: How a change made by a yes on a card is said, before the request it names (ADR-0362
#: §2:1, ADR-0338 §3:5 as it amends it). ``HOW_WORDS``' approval is the question form's,
#: which stored acts still hold; the question path is retired (ADR-0361 §8:5), so a yes
#: whose act names a request was a tap on that request's card, and no question was shown.
CARD_YES_WORDS: Final = "by your yes on the card for request"

#: Why the slot left a memory out (ADR-0338 §6:2, §6:4).
LEFT_OUT_WORDS: Final[Mapping[LeftOutReason, str]] = MappingProxyType(
    {
        LeftOutReason.BUDGET: "Left out: there is no room left for it in what I keep in mind.",
        LeftOutReason.OUTSIDE_CONTENT: (
            "Left out: it rests on outside content, which I keep in mind only once you have "
            "confirmed its wording."
        ),
    }
)

#: Why a write was refused, by the refusal's own name: the store's, and the two the
#: engine gives before any write (ADR-0338 §4:2, §6:3). Each is the whole sentence.
REFUSAL_WORDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        PersonModelRefusal.UNKNOWN_PERSON.value: (
            "I hold no profile for you, so nothing was changed."
        ),
        PersonModelRefusal.INVALID_VALUE.value: "That value was not saved.",
        PersonModelRefusal.INVALID_ACT.value: (
            "That change cannot be made this way, so nothing was changed."
        ),
        PersonModelRefusal.UNKNOWN_RECORD.value: (
            "That is no longer there, so nothing was changed."
        ),
        PersonModelRefusal.ALREADY_DECIDED.value: (
            "That suggestion was already accepted or dismissed."
        ),
        PersonModelEditRefusal.NOT_CURRENT.value: (
            "That memory is no longer current, so it was not pinned."
        ),
        PersonModelEditRefusal.OVER_BUDGET.value: (
            "Pinning it would take what I keep in mind over its budget, so it was not "
            "pinned. Unpin something first."
        ),
    }
)

#: What each act did, where it wrote and where it changed nothing.
DONE_WORDS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "set": ("Saved.", "That is what it already was, so nothing changed."),
        "clear": ("Cleared.", "It was not set, so nothing changed."),
        "pin": (
            "Pinned. I keep it in mind in every conversation, and your pin confirms this "
            "wording as yours.",
            "It was already pinned.",
        ),
        "unpin": (
            "Unpinned. The memory itself is kept.",
            "No pin showed that memory, so nothing changed.",
        ),
        "unmark": (
            "Removed. I will not mark it again; the memory itself is kept.",
            "That was already removed.",
        ),
        "accept": ("Accepted.", "It was already pinned."),
        "dismiss": ("Dismissed. I will not suggest it again.", "Dismissed."),
    }
)

#: What a pin confirms, said before it is made (ADR-0338 §4:3).
PIN_CONFIRMS: Final = (
    "Pinning keeps it in mind in every conversation, and confirms this wording as yours."
)


def _print(console: Console, text: str) -> None:
    console.print(text, markup=False, emoji=False, highlight=False, soft_wrap=True)


def render_said(console: Console, said: str) -> None:
    """Print one sentence this module's tables hold, or an act's outcome built from them."""
    _print(console, said)


def render_off(console: Console) -> None:
    """Say the hub keeps no person model, as a state rather than a fault (§11:2)."""
    _print(console, OFF)


def render_no_memory(console: Console, memory_id: str) -> None:
    """Say no live memory has exactly the id a pin named, so nothing was pinned (§4:2).

    Exactly: the belief read normalises an id and the person model does not (§10:4), so
    a read that answered for another id than the one typed is no read of that memory,
    and its wording is not shown for a pin to confirm (§4:3).

    Args:
        console: Where to write.
        memory_id: The id as typed.
    """
    _print(
        console,
        f"No live memory has exactly the id {quoted(memory_id)}, so nothing was pinned. Only a "
        "current memory may be pinned; 'assistant beliefs' lists them.",
    )


def render_pin_prompt(console: Console, content: str) -> None:
    """Show the wording a pin would confirm, and that it would (ADR-0338 §4:3).

    Args:
        console: Where to write.
        content: The memory's wording, as the hub holds it.
    """
    _print(console, f"“{escaped(content)}”")
    _print(console, PIN_CONFIRMS)


def _value(value: str | None) -> str:
    """A field's value as a sentence shows it: quoted and escaped, or not set."""
    return "not set" if value is None else f"“{escaped(value)}”"


def edit_text(act: str, edit: PersonModelEdit) -> tuple[bool, str]:
    """What a write did, in words, and whether it did what was asked.

    Args:
        act: Which act it was: a key of :data:`DONE_WORDS`.
        edit: What the engine answered.

    Returns:
        ``True`` where it wrote or changed nothing as the contract says such a write
        does, ``False`` where it was refused; and the sentence.
    """
    if edit.refused is not None:
        return False, REFUSAL_WORDS[edit.refused.value]
    write = edit.write
    if write is None:  # pragma: no cover — the edit's own validator sets one of the two
        return False, REFUSAL_WORDS[PersonModelRefusal.INVALID_ACT.value]
    if write.kind is PersonModelWriteKind.REFUSED:
        refusal = write.refusal
        said = REFUSAL_WORDS[refusal.value] if refusal is not None else ""
        if write.reason is not None:
            said = f"{said} The rule is: {escaped(write.reason)}."
        return False, said
    written, unchanged = DONE_WORDS[act]
    return True, written if write.kind is PersonModelWriteKind.WRITTEN else unchanged


def _page_note(console: Console, shown: int, total: int, offset: int) -> None:
    """Say which of a list's entries this page shows, where it shows fewer than all."""
    if shown < total:
        first = offset + 1 if shown else offset
        _print(console, f"  (showing {first}-{offset + shown} of {total})")


def pasteable(command: str, value: str) -> str:
    """A command a person can paste to act on ``value``, or why it cannot be shown.

    **The shell's quoting and the terminal's escaping are two questions.** The id is
    quoted by :func:`shlex.quote`, so a ``$``, a backtick, a quote or a space in it
    reaches the command as itself and expands to nothing, and follows ``--``, so one
    beginning with a hyphen is not read as an option; and a command is offered only
    where every character of the id prints as itself, because an escaped character
    would paste as a different id. Where one does not, the id is shown escaped and no
    command is offered: a wrong command is worse than none.

    Args:
        command: The ``assistant about`` command that takes it.
        value: The id, verbatim.

    Returns:
        The command, or a sentence naming the id it cannot offer one for.
    """
    if value.isprintable():
        # `--` ends the options, so an id that begins with a hyphen is an id.
        return f"{command} with: assistant about {command} -- {shlex.quote(value)}"
    return f"{quoted(value)} cannot be pasted as a command here"


def _kept_line(kept: KeptMemoryView | LeftOutMemory) -> str:
    what = "pinned" if kept.pinned else "how you like me to speak"
    line = f"  - {what} · “{escaped(kept.content)}”"
    return f"{line} · {pasteable('unpin', kept.memory_id)}" if kept.pinned else line


def _stale_line(stale: StalePinView) -> str:
    outside = " · it rested on outside content" if stale.rests_on_outside_content else ""
    return (
        f"  - “{escaped(stale.content)}” · pinned {stale.pin.pinned_at.isoformat()}{outside}"
        f" · {pasteable('unpin', stale.pin.memory_id)}"
    )


def _mark_line(mark: StyleMarkView) -> str:
    gone = " · no longer current" if mark.shows is None else ""
    return f"  - “{escaped(mark.content)}”{gone} · {pasteable('remove-style', mark.mark.id)}"


def _suggestion_line(view: SuggestionView) -> str:
    proposed = view.suggestion.proposed
    outside = " · it rests on outside content" if view.rests_on_outside_content else ""
    if proposed.kind is SuggestionKind.PIN:
        what = (
            f"keep in mind “{escaped(view.content or '')}”, which pins it and confirms "
            "this wording as yours"
        )
    else:
        field = proposed.field
        label = FIELD_WORDS[field] if field is not None else ""
        what = f"{label}: {_value(proposed.value)}"
    named = view.suggestion.id
    return f"  - {what}{outside} · {pasteable('accept', named)} · {pasteable('dismiss', named)}"


@dataclass(frozen=True, slots=True)
class _Listed:
    """One of the model's lists as a section renders it: its page beside its total."""

    heading: str
    lines: Sequence[str]
    total: int
    empty: str = ""


def _section(console: Console, listed: _Listed, *, offset: int) -> None:
    _print(console, listed.heading)
    if listed.total == 0:
        _print(console, f"  {listed.empty}")
        return
    for one in listed.lines:
        _print(console, one)
    _page_note(console, len(listed.lines), listed.total, offset)


def render_model(console: Console, view: PersonModelView, *, offset: int) -> None:
    """Render one page of a person's model, every list beside its total (§8:1).

    Args:
        console: Where to write.
        view: The model the engine answered.
        offset: The page's offset, which every list was read from.
    """
    _print(console, "About you")
    for field in ProfileField:
        held = view.profile.value(field)
        said = UNSET_WORDS[field] if held is None else _value(held)
        _print(console, f"  {FIELD_WORDS[field]}: {said}")
    listed = [
        _Listed(
            f"What I keep in mind (using {view.kept_chars} of the {view.budget_chars} "
            "characters I keep in mind)",
            [_kept_line(one) for one in view.kept],
            view.kept_total,
            "Nothing yet.",
        ),
        _Listed(
            "Left out of what I keep in mind",
            [f"{_kept_line(one)} · {LEFT_OUT_WORDS[one.reason]}" for one in view.left_out],
            view.left_out_total,
        ),
        _Listed(
            "Pins no longer current: each memory no longer holds, and nothing replaced it",
            [_stale_line(one) for one in view.no_longer_current],
            view.no_longer_current_total,
        ),
        _Listed(
            "How you like me to speak",
            [_mark_line(one) for one in view.style_marks],
            view.style_marks_total,
            "Nothing yet.",
        ),
        _Listed(
            "My suggestions (accept or dismiss with: assistant about accept|dismiss <suggestion>)",
            [_suggestion_line(one) for one in view.suggestions],
            view.suggestions_total,
            "None.",
        ),
    ]
    for one in listed:
        # A list that may be empty without saying so is shown only where it holds one:
        # the left-out memories and the pins no longer current.
        if one.total or one.empty:
            _section(console, one, offset=offset)


def how_words(act: PersonModelAct) -> str:
    """How a change was made, in words: a yes on a card by the request it names (§2:1).

    An act names a request exactly where a ticket ran its call, so that act is said as a
    yes on the request's card, the id quoted as the rest of this module's are; every
    other act, a stored yes to a question included, by ``HOW_WORDS``.
    """
    if act.request is not None:
        return f"{CARD_YES_WORDS} {quoted(act.request)}"
    return HOW_WORDS[act.how]


def render_changes(console: Console, changes: Sequence[ProfileChange], *, full: bool) -> None:
    """Render one page of the change log, the most recent first (ADR-0338 §3:5).

    Args:
        console: Where to write.
        changes: The page.
        full: Whether the page was full, so there may be more past it.
    """
    _print(console, "Changes to your profile, the most recent first")
    if not changes:
        _print(console, "  No change on this page.")
        return
    for change in changes:
        _print(
            console,
            f"  {FIELD_WORDS[change.field]}: {_value(change.old)} → {_value(change.new)}"
            f" · {change.at.isoformat()} · {how_words(change.act)}",
        )
    if full:
        _print(console, "  That is a full page; there may be more. Ask for the next with --offset.")


__all__ = [
    "CARD_YES_WORDS",
    "DONE_WORDS",
    "FIELD_WORDS",
    "HOW_WORDS",
    "LEFT_OUT_WORDS",
    "NO_PROFILE",
    "OFF",
    "PIN_CONFIRMS",
    "REFUSAL_WORDS",
    "UNSET_WORDS",
    "edit_text",
    "how_words",
    "pasteable",
    "render_changes",
    "render_model",
    "render_no_memory",
    "render_off",
    "render_pin_prompt",
    "render_said",
]
