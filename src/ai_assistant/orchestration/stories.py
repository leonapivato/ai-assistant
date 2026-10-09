"""The engine's side of the story surface (ADR-0289 §4).

Four things the engine adds to the story store, and nothing else:

* **The existence check** (:func:`unknown_activation`). Before a create or a link
  naming an activation member, each activation's record is read at
  ``activation:<activation_id>`` through ``MemoryStore.get``, and the write is
  refused where none is there. An open episode is a record there (ADR-0286 §6), so a
  running activation can be linked. A merge, a split or a move (ADR-0300 §3:14)
  checks nothing: each moves members a story already holds, so an activation whose
  episode has since been forgotten moves with the rest. The story store itself reads
  no other store (§1).
* **The resolved view** (:func:`resolved_view`). Each activation member is resolved
  to its episode's ``EpisodeSummary``, or marked forgotten where no record is there
  any more; each story member to its id and its current member count, one level deep.
* **The payload fit** (:func:`fitted`). A page too large for the contract's payload
  limit is re-read at a smaller page size, so the caller gets the largest page that
  fits with a cursor resuming after it, rather than a refusal.
* **The owner's page** (:func:`owner_page`, ADR-0303 §10:2). A story's current page
  and its mark, and its newest notes with whether each is pending, under ADR-0303 §3's
  default for the owner as reader: decided by
  :class:`~ai_assistant.orchestration.story_privacy.PageVisibility`, the one statement
  of that rule.

Shared by :class:`~ai_assistant.orchestration.engine.Engine` and the canonical fake
engine, so the two cannot answer one call two ways. No stage, phase, rule or prompt
reads the surface's checks, views or fits (§4): what understanding is shown of a story,
and what its stage writes, are :mod:`~ai_assistant.orchestration.story_links`' (ADR-0300
§6), which shares only :func:`episode_address`, the one spelling of an episode's address.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ai_assistant.core.episode_encoding import summary_of
from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    EpisodicMemory,
    StoryMember,
    StoryMemberKind,
    StoryMemberView,
    StoryPageView,
    StoryPageViewNote,
    StoryRefusal,
    StoryRefusalReason,
    StoryView,
)
from ai_assistant.orchestration.payloads import canonical_payload, check_payload
from ai_assistant.orchestration.story_privacy import PageVisibility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.protocols import MemoryStore, StoryStore
    from ai_assistant.core.types import StoryNote, StoryPageState


def episode_address(activation_id: str) -> str:
    """The address of an activation's episode (ADR-0283 §2)."""
    return f"activation:{activation_id}"


async def unknown_activation(
    memory: MemoryStore, members: Sequence[StoryMember]
) -> StoryRefusal | None:
    """Refuse the first activation member with no record at its episode's address.

    Read through :meth:`~ai_assistant.core.protocols.MemoryStore.get_many`, which
    never disagrees with ``get`` (ADR-0086 §6), so a whole member list is judged
    against one state of the memory store.

    Args:
        memory: The memory store the engine holds.
        members: The members a create or a link names.

    Returns:
        A ``unknown_activation`` refusal naming the first member with no record, or
        ``None`` where every activation member has one.
    """
    activations = [member for member in members if member.kind is StoryMemberKind.ACTIVATION]
    if not activations:
        return None
    found = await memory.get_many([episode_address(member.id) for member in activations])
    for member in activations:
        if not isinstance(found.get(episode_address(member.id)), EpisodicMemory):
            return StoryRefusal(reason=StoryRefusalReason.UNKNOWN_ACTIVATION, member=member)
    return None


async def resolved_view(
    stories: StoryStore,
    memory: MemoryStore,
    story_id: str,
    *,
    cursor: int | None,
    limit: int,
) -> StoryView | None:
    """Read one page of a story's view and resolve its members (ADR-0289 §4).

    Raises:
        StoryStoreError: If the story store cannot be read, or holds a story member
            it cannot read back — a store that contradicts itself.
        MemoryStoreError: If an activation's record cannot be read.
    """
    page = await stories.view(story_id, cursor=cursor, limit=limit)
    if page is None:
        return None
    addresses = [
        episode_address(entry.member.id)
        for entry in page.entries
        if entry.member.kind is StoryMemberKind.ACTIVATION
    ]
    found = await memory.get_many(addresses) if addresses else {}
    members: list[StoryMemberView] = []
    for entry in page.entries:
        if entry.member.kind is StoryMemberKind.ACTIVATION:
            record = found.get(episode_address(entry.member.id))
            episode = summary_of(record) if isinstance(record, EpisodicMemory) else None
            count = None
        else:
            inner = await stories.view(entry.member.id, limit=1)
            if inner is None:
                msg = f"story {story_id!r} holds story {entry.member.id!r}, which it cannot read"
                raise StoryStoreError(msg)
            episode = None
            count = inner.member_count
        members.append(
            StoryMemberView(
                position=entry.position,
                member=entry.member,
                linked_at=entry.linked_at,
                actor=entry.actor,
                episode=episode,
                forgotten=entry.member.kind is StoryMemberKind.ACTIVATION and episode is None,
                member_count=count,
            )
        )
    return StoryView(
        story=page.story,
        member_count=page.member_count,
        members=tuple(members),
        next_cursor=page.next_cursor,
    )


#: How many of a story's notes the owner's page view lists, newest first (ADR-0303
#: §10:2). ADR-0303 makes it a composition-root constant; until the lane that rebuilds
#: the view (§12:3) wires it there, both engines read this default. Twenty notes at
#: their bound of 2,000 characters is about 40,000 characters, beside a page capped at
#: 8,000, well inside a frame's payload limit.
STORY_PAGE_VIEW_NOTES: Final = 20

#: How many times the owner's page is read before the reads are given up as never
#: agreeing. Each attempt brackets the notes between two reads of the page's state, and
#: one that a write lands inside is read again. The window is a few reads long, so a
#: store written inside it this many times running is answered with the store error the
#: read already declares, rather than with a view no one read.
_PAGE_READS: Final = 5


async def owner_page(
    stories: StoryStore,
    memory: MemoryStore,  # noqa: ARG001 — the episodes §3:7's walk reads, once it is built
    story_id: str,
    *,
    notes: int = STORY_PAGE_VIEW_NOTES,
) -> StoryPageView | None:
    """Read a story's page as the owner is shown it (ADR-0303 §10:2).

    The current page and what is pending on it are one read of the story store; the
    story's notes are then read page by page, and the newest ``notes`` of them listed,
    each with whether it is pending. The notes are read between two reads of the page's
    state, and the view is built only where the two are the same read, ``as_of``
    included: every write that adds, carries or takes in a note advances the counter
    ``as_of`` reports (ADR-0300 §3:8), so two reads naming one ``as_of`` bracket a
    listing no such write landed inside, and each note listed is shown pending exactly
    as it stood. A write to another story advances it too, and costs a read again, not
    a wrong answer. The owner may be shown a record placed for the
    owner alone, so every note is shown (§3:6), and so is the page under
    :class:`~ai_assistant.orchestration.story_privacy.PageVisibility`'s interim rule;
    §3:7's walk, which withholds a page an open or forgotten episode stands behind, is
    ADR-0303 §12:3's lane's, and reads ``memory``.

    Returns:
        The page, or ``None`` where the store holds no such story. A merged story's
        carries its header alone.

    Raises:
        StoryStoreError: If the story store cannot be read, or the story was written
            between every one of :data:`_PAGE_READS` bracketed reads.
        MemoryStoreError: If an episode cannot be read.
    """
    for _ in range(_PAGE_READS):
        state = await stories.current_page(story_id)
        if state is None:
            return None
        if state.story.merged_into is not None:
            return StoryPageView(story=state.story)
        held = await _all_notes(stories, story_id)
        if await stories.current_page(story_id) == state:
            return _page_view(state, held, notes=notes)
    msg = "the story was written while its page was read, every time it was read"
    raise StoryStoreError(msg)


def _page_view(state: StoryPageState, held: list[StoryNote], *, notes: int) -> StoryPageView:
    """The owner's view of a page read as ``state`` stood, with every note it held."""
    page = state.page
    visibility = PageVisibility(activations=frozenset(), owner_notes=True)
    shown = page is not None and visibility.page()
    newest = [note for note in reversed(held) if visibility.note(note)][:notes]
    pending = {note.note_id for note in state.pending_notes}
    return StoryPageView(
        story=state.story,
        version=None if page is None else page.version,
        tidied_at=None if page is None else page.written_at,
        lines=page.lines if shown and page is not None else (),
        outside=page.outside if shown and page is not None else False,
        withheld=page is not None and not shown,
        notes=tuple(
            StoryPageViewNote(note=note, pending=note.note_id in pending) for note in newest
        ),
        more_notes=max(0, len(held) - len(newest)),
    )


async def _all_notes(stories: StoryStore, story_id: str) -> list[StoryNote]:
    """Every note the story holds, in the order they were written, read page by page."""
    found: list[StoryNote] = []
    cursor: int | None = None
    while True:
        listed = await stories.notes(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if listed is None:
            return found
        found.extend(listed.notes)
        following = listed.next_cursor
        if following is None or following == cursor:
            return found
        cursor = following


async def fitted[P](
    read: Callable[[int], Awaitable[P | None]],
    limit: int,
    *,
    max_bytes: int,
    subject: str,
) -> P | None:
    """The largest page ``read`` returns at or below ``limit`` that fits the payload limit.

    The page at ``limit`` is returned as it is where it fits. Otherwise smaller page
    sizes are read by bisection and the largest that fits is returned, carrying the
    cursor the store gave it — so the caller resumes after the last item it was
    handed and loses nothing. Where not even one item fits, the oversized page earns
    the ordinary structured size refusal.

    Raises:
        OversizedValueError: If a page of one item does not fit.
    """
    page = await read(limit)
    if page is None or len(canonical_payload(page)) <= max_bytes:
        return page
    best: P | None = None
    low, high = 1, limit - 1
    while low <= high:
        size = (low + high) // 2
        candidate = await read(size)
        if candidate is None:
            return None
        if len(canonical_payload(candidate)) <= max_bytes:
            best = candidate
            low = size + 1
        else:
            high = size - 1
    if best is None:
        check_payload(page, max_bytes=max_bytes, subject=subject)
        msg = "an oversized page was unexpectedly admitted"
        raise AssertionError(msg)
    return best
