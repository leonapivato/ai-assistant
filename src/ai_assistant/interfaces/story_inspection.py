"""Presentation for the owner's story commands (ADR-0289 §5).

Rendering and read assembly only. Which writes are allowed, what a loop is and
whether a member exists are the story store's and the engine's to decide (ADR-0289
§§3-4); this module states what they answered.

**Every value the engine supplies is quoted** by :func:`quoted`: JSON-escaped, and
any character that is still not printable escaped as well, so an id carrying a line
break, an ANSI escape or a C1 control cannot pose as a line this adapter wrote.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    StoryChange,
    StoryMemberKind,
    StoryRefusalReason,
)
from ai_assistant.interfaces.episode_inspection import summary_fields
from ai_assistant.wire.errors import ProtocolError

if TYPE_CHECKING:
    from rich.console import Console

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        StoryHeader,
        StoryLogLine,
        StoryLogPage,
        StoryMember,
        StoryMemberView,
        StoryOutcome,
        StoryPage,
        StoryRefusal,
    )

#: What each change-log line's change reads as. Spelled out per member so a member
#: added to the closed enumeration fails the coverage test until it is rendered.
CHANGE_TEXT: dict[StoryChange, str] = {
    StoryChange.CREATED: "created",
    StoryChange.ADDED: "added",
    StoryChange.REMOVED: "removed",
    StoryChange.MERGED_INTO: "merged into",
    StoryChange.ABSORBED: "absorbed",
    StoryChange.SPLIT_OFF: "split, the other side being",
}


def escaped(value: str) -> str:
    """Escape an engine-supplied value so it stays on one line and acts on nothing.

    ``json.dumps`` escapes the C0 controls, the quote and the backslash; anything it
    leaves that :meth:`str.isprintable` rejects — a C1 control, a line or paragraph
    separator, a format character — is escaped too.
    """
    return "".join(
        ch if ch.isprintable() else f"\\u{ord(ch):04x}"
        for ch in json.dumps(value, ensure_ascii=False)[1:-1]
    )


def quoted(value: str) -> str:
    """An engine-supplied id, :func:`escaped` and in double quotes, as a shell takes it."""
    return f'"{escaped(value)}"'


def _print(console: Console, text: str) -> None:
    console.print(text, markup=False, emoji=False, highlight=False, soft_wrap=True)


def member_text(member: StoryMember) -> str:
    """A member as the owner writes it: its kind, then its id."""
    return f"{member.kind.value} {quoted(member.id)}"


def refusal_text(refusal: StoryRefusal) -> str:
    """Say why a write was refused, naming the reason and what it was refused over."""
    story = "the story" if refusal.story_id is None else f"story {quoted(refusal.story_id)}"
    match refusal.reason:
        case StoryRefusalReason.NO_MEMBERS:
            detail = "no member was named"
        case StoryRefusalReason.UNKNOWN_STORY:
            detail = f"there is no {story}"
        case StoryRefusalReason.MERGED_STORY:
            target = quoted(refusal.merged_into or "")
            detail = f"{story} was merged into story {target}"
        case StoryRefusalReason.SELF_MERGE:
            detail = f"{story} cannot be merged into itself"
        case StoryRefusalReason.LOOP:
            chain = " contains ".join(quoted(item) for item in (*refusal.loop, refusal.loop[0]))
            detail = f"story {quoted(refusal.loop[0])} would contain itself: {chain}"
        case StoryRefusalReason.NOT_A_MEMBER:
            member = "a member" if refusal.member is None else member_text(refusal.member)
            detail = f"{member} is not a member of {story}"
        case StoryRefusalReason.UNKNOWN_ACTIVATION:
            member = "an activation" if refusal.member is None else member_text(refusal.member)
            detail = f"{member} has no episode record"
        case _:  # pragma: no cover — exhaustive over a closed enumeration
            assert_never(refusal.reason)
    return f"Refused ({refusal.reason.value}): {detail}."


def render_outcome(console: Console, applied: str, outcome: StoryOutcome) -> bool:
    """Render a write's outcome; return whether it was applied.

    Args:
        console: Where to render.
        applied: What the write did, said of the story it leaves standing, e.g.
            ``"Created story"``.
        outcome: The engine's answer.

    Returns:
        ``True`` where the write was applied, ``False`` where it was refused.
    """
    if outcome.refusal is not None:
        _print(console, refusal_text(outcome.refusal))
        return False
    story = quoted(outcome.story_id or "")
    lines = "line" if outcome.logged == 1 else "lines"
    text = f"{applied} {story}; {outcome.logged} change-log {lines} appended."
    if not outcome.logged:
        text += " Nothing changed: every member named was passed over."
    _print(console, text)
    return True


def render_listing(console: Console, page: StoryPage) -> None:
    """Render a page of stories, newest first, with its continuation."""
    if not page.stories:
        _print(console, "No stories.")
    for header in page.stories:
        text = f"Story {quoted(header.story_id)}  created {header.created_at.isoformat()}"
        if header.merged_into is not None:
            text += f"  merged into {quoted(header.merged_into)}"
        _print(console, text)
    if page.next_cursor is not None:
        _print(console, f"Next cursor: {page.next_cursor}")
        console.print("Use --cursor to read the next page.")


@dataclass(frozen=True, slots=True)
class StoryRead:
    """A story read whole: its header, members and change log (ADR-0289 §5:2).

    Attributes:
        header: The story's header.
        member_count: Its current member count, as the view stated it.
        members: Every member, in link order; empty for a merged story.
        log: Every change-log line, oldest first; empty for a merged story.
    """

    header: StoryHeader
    member_count: int
    members: tuple[StoryMemberView, ...]
    log: tuple[StoryLogLine, ...]


def _advanced(previous: int | None, following: int) -> int:
    """Refuse a continuation that does not move forward, which would never end."""
    if previous is not None and following <= previous:
        raise ProtocolError("story continuation did not advance; incomplete story discarded")
    return following


async def read_story(engine: AssistantEngine, story_id: str) -> StoryRead | None:
    """Read a story's change log and members page by page, to the end.

    A merged story is read no further than the first log page that names where it
    went, which is all its view renders (ADR-0289 §5:2): a merged story takes no
    further write (§3), so nothing after that page can change.

    **A story that changes while it is read is discarded, not rendered.** Every write
    that changes a story appends to its change log in the same transaction as the
    clean view (§2), so the log's last sequence number is the story's version. The
    whole log is read first, then every member page, and then the log is asked for
    anything after the last line read: a line there means a write landed while the
    members were read, and a view stitched across it would state a membership the
    story never had beside a log that says otherwise. Each member page must also
    carry the log's header and one member count, and the members must number it.

    Returns:
        The read, or ``None`` where the engine holds no such story.

    Raises:
        ProtocolError: If the story changed while it was read, or a continuation did
            not advance.
    """
    log = await engine.story_log(story_id, limit=MAX_STORY_PAGE)
    if log is None:
        return None
    header = log.story
    if header.merged_into is not None:
        return StoryRead(header, 0, (), ())
    lines = await _whole_log(engine, story_id, log)
    member_count, members = await _whole_view(engine, story_id, header)
    after = await engine.story_log(story_id, cursor=lines[-1].sequence, limit=1)
    if after is None or after.story != header or after.lines:
        raise _changed()
    return StoryRead(header, member_count, members, lines)


async def _whole_log(
    engine: AssistantEngine, story_id: str, first: StoryLogPage
) -> tuple[StoryLogLine, ...]:
    """Every line of a story's log, from its first page on; never empty."""
    lines = list(first.lines)
    page = first
    while page.next_cursor is not None:
        cursor = page.next_cursor
        following = await engine.story_log(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if following is None or following.story != first.story:
            raise _changed()
        if following.next_cursor is not None:
            _advanced(cursor, following.next_cursor)
        lines.extend(following.lines)
        page = following
    if not lines:  # pragma: no cover — every story's log opens with its creation (§3)
        raise _changed()
    return tuple(lines)


async def _whole_view(
    engine: AssistantEngine, story_id: str, header: StoryHeader
) -> tuple[int, tuple[StoryMemberView, ...]]:
    """A story's member count and every member, each page checked against the header."""
    members: list[StoryMemberView] = []
    member_count: int | None = None
    cursor: int | None = None
    while True:
        page = await engine.story(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if page is None or page.story != header:
            raise _changed()
        if member_count is not None and page.member_count != member_count:
            raise _changed()
        member_count = page.member_count
        members.extend(page.members)
        if page.next_cursor is None:
            break
        cursor = _advanced(cursor, page.next_cursor)
    if len(members) != member_count:
        raise _changed()
    return member_count, tuple(members)


def _changed() -> ProtocolError:
    return ProtocolError("story changed while it was read; incomplete story discarded")


def _member_line(view: StoryMemberView) -> str:
    """One member: an episode's one-line summary, forgotten, or a story and its count.

    An activation member renders the facts the episode list renders for its row, on
    one line, through :func:`summary_fields`, so an open episode reads in progress
    (ADR-0289 §5:2). A story member is nested one level deep: its id and its current
    member count, never its own members.
    """
    if view.member.kind is StoryMemberKind.STORY:
        count = view.member_count or 0
        noun = "member" if count == 1 else "members"
        return f"  Story {quoted(view.member.id)}: {count} {noun}"
    if view.episode is None:
        return f"  Activation {quoted(view.member.id)}: forgotten"
    fields = " | ".join(
        f"{label}: {escaped(value)}" for label, value in summary_fields(view.episode)
    )
    return f"  Episode {quoted(view.episode.position.episode_id)} | {fields}"


def _log_line(line: StoryLogLine) -> str:
    """One change-log line: its sequence, instant, actor, change and what it names."""
    text = (
        f"  #{line.sequence} {line.at.isoformat()} {line.actor.value}: {CHANGE_TEXT[line.change]}"
    )
    if line.member is not None:
        text += f" {member_text(line.member)}"
    if line.other_story is not None:
        text += f" story {quoted(line.other_story)}"
    if line.trigger is not None:
        text += f" (triggered by activation {quoted(line.trigger)})"
    return text


def render_story(console: Console, read: StoryRead) -> None:
    """Render the story view of ADR-0289 §5:2.

    A merged story renders only the line naming the story it was merged into.
    Otherwise its header, each member in link order, then the change log, oldest
    first.
    """
    header = read.header
    if header.merged_into is not None:
        _print(
            console,
            f"Story {quoted(header.story_id)} was merged into story {quoted(header.merged_into)}.",
        )
        return
    lines = [
        f"Story {quoted(header.story_id)}",
        f"Created: {header.created_at.isoformat()}",
        f"Members: {read.member_count}",
        *(_member_line(view) for view in read.members),
        "Change log, oldest first:",
        *(_log_line(line) for line in read.log),
    ]
    _print(console, "\n".join(lines))
