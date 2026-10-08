"""Where a matter stands, worked out from the records for one reader (ADR-0300 §8).

No record stores where a matter stands (ADR-0300 §2:1). Each time a reader needs it,
:func:`story_standing` assembles it from the story store's clean view and the
episodes its members name:

* **What was done** (``done``), from the effect records of the story's current
  episodes. Effect records come with the phases' acting (§8), which fills the slot;
  nothing here reads one.
* **When things happened** (``recent`` and ``earlier``), a short timeline of the
  member episodes by each episode's own instant and latest understood meaning, most
  recent first, the newest :data:`~ai_assistant.core.types.STORY_STANDING_RECENT`
  one by one and the older ones summarised as counts.
* **The related matters** (``related``), the stories the story is part of, read
  with ``StoryStore.stories_of``, then the stories it contains, its story members,
  each by its id and member count, one level deep (ADR-0289 §4:5).

**Per reader** (§8, §11). Nothing is stored per view, so the reader is an argument
and each episode is shown only where it may be shown to that reader:

* :data:`OWNER_READER`, the owner reading directly through the story commands, is
  shown every live episode, an open one marked in progress: the owner's direct
  inspection reads every record, outside the eligibility filters of automatic
  model-facing reads (ADR-0275 §7, §10).
* A model-facing reader within an activation pass, planning once the phases build
  it, is named by that pass's audience posture, a
  :data:`~ai_assistant.orchestration.disclosure.TurnSupply`. It is shown an episode
  only where the pass's audience admits it, by the predicate every phase applies to
  what it reads (ADR-0282 §2:8), and never an open one, which is never a model input
  (ADR-0286 §6). An episode not shown is not counted either.

An episode resting on outside content is marked, by the rule ADR-0300 §4:3 marks a
note resting on an episode (§8, last normative).

This module is apart from :mod:`ai_assistant.orchestration.stories`, which is the
engine's own story surface and documents that no stage reads it: planning reads
where a matter stands (§8's table, §10), and the engine's story commands will read
it too, so both take it from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, final

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    STORY_STANDING_RECENT,
    EpisodicMemory,
    InputOrigin,
    RecordedChannelTrigger,
    StoryEntry,
    StoryMember,
    StoryMemberKind,
    StoryRelated,
    StoryRelation,
    StoryStanding,
    StoryStandingEarlier,
    StoryStandingEpisode,
    rests_on_recorded_external_content,
)
from ai_assistant.orchestration.disclosure import TurnSupply, admitted_to_understanding
from ai_assistant.orchestration.episode_reads import without_open_episodes
from ai_assistant.orchestration.stories import episode_address

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import MemoryStore, StoryStore
    from ai_assistant.core.types import MemoryRecord, StoryHeader


@final
@dataclass(frozen=True, slots=True)
class OwnerReader:
    """The owner, reading where a matter stands directly (ADR-0300 §8's table).

    Shown every live episode a story holds, an open one marked in progress, as the
    owner's direct inspection reads every record (ADR-0275 §7, §10).
    """


#: The one owner reader.
OWNER_READER: Final = OwnerReader()

#: Who is reading where a matter stands: the owner directly, or a model-facing reader
#: within an activation pass, named by that pass's audience posture (ADR-0300 §8, §11).
type StandingReader = OwnerReader | TurnSupply


async def story_standing(
    stories: StoryStore,
    memory: MemoryStore,
    story_id: str,
    *,
    reader: StandingReader,
) -> StoryStanding | None:
    """Assemble where a story's matter stands, for one reader (ADR-0300 §8:1).

    The clean view is read page by page, then every activation member's episode with
    one ``MemoryStore.get_many``, then the stories the story is part of. A story
    written between those reads is read as it stood at each, and nothing here is one
    snapshot of both stores; nothing needs to be, since nothing is stored from it.
    Each member and each related story is shown once all the same, as the latest
    read saw it: a member unlinked and linked again between two pages is kept at its
    later entry, and a story the reverse lookup names as one the story is part of is
    not also listed as one it contains.

    Args:
        stories: The story store.
        memory: The memory store holding the members' episodes.
        story_id: The story to read.
        reader: Who is reading, which decides the episodes shown.

    Returns:
        Where the matter stands, or ``None`` where the store holds no such story. A
        merged story's carries its header alone, naming where it went.

    Raises:
        ValueError: If ``story_id`` is malformed.
        StoryStoreError: If the story store cannot be read, or holds a story member
            it cannot read back.
        MemoryStoreError: If an episode cannot be read.
    """
    page = await stories.view(story_id, limit=MAX_STORY_PAGE)
    if page is None:
        return None
    if page.story.merged_into is not None:
        return StoryStanding(story=page.story)
    entries: dict[StoryMember, StoryEntry] = {}
    _keep_latest(entries, page.entries)
    cursor = page.next_cursor
    while cursor is not None:
        more = await stories.view(story_id, cursor=cursor, limit=MAX_STORY_PAGE)
        if more is None:
            break
        _keep_latest(entries, more.entries)
        cursor = more.next_cursor
    members = list(entries.values())
    recent, earlier = _timeline(await _shown(memory, members, reader))
    return StoryStanding(
        story=page.story,
        recent=recent,
        earlier=earlier,
        related=await _related(stories, page.story, members),
    )


def _keep_latest(entries: dict[StoryMember, StoryEntry], page: Sequence[StoryEntry]) -> None:
    """Add a page's entries in link order, a member read twice kept at its later entry."""
    for entry in page:
        entries.pop(entry.member, None)
        entries[entry.member] = entry


async def _shown(
    memory: MemoryStore, entries: Sequence[StoryEntry], reader: StandingReader
) -> list[tuple[EpisodicMemory, StoryEntry]]:
    """The episodes of ``entries``' activation members this reader may be shown.

    Each is paired with its member's entry, which names the activation and whose
    position breaks a tie between two episodes of one instant in favour of the one
    linked later.
    """
    members = {
        episode_address(entry.member.id): entry
        for entry in entries
        if entry.member.kind is StoryMemberKind.ACTIVATION
    }
    if not members:
        return []
    found: Mapping[str, MemoryRecord] = await memory.get_many(list(members))
    if not isinstance(reader, OwnerReader):
        found = without_open_episodes(found)
    episodes = [
        record for address in members if isinstance(record := found.get(address), EpisodicMemory)
    ]
    if not isinstance(reader, OwnerReader):
        episodes = list(admitted_to_understanding(reader, episodes))
    return [(record, members[record.id]) for record in episodes]


def _timeline(
    shown: Sequence[tuple[EpisodicMemory, StoryEntry]],
) -> tuple[tuple[StoryStandingEpisode, ...], StoryStandingEarlier | None]:
    """The newest episodes one by one, most recent first, and the rest as counts."""
    ordered = sorted(shown, key=lambda pair: (pair[0].occurred_at, pair[1].position), reverse=True)
    recent = tuple(
        _moment(record, entry.member.id) for record, entry in ordered[:STORY_STANDING_RECENT]
    )
    older = [record.occurred_at for record, _ in ordered[STORY_STANDING_RECENT:]]
    if not older:
        return recent, None
    return recent, StoryStandingEarlier(episodes=len(older), first_at=older[-1], last_at=older[0])


def _moment(record: EpisodicMemory, activation_id: str) -> StoryStandingEpisode:
    """One episode as the timeline shows it: its instant, its meaning and its marks.

    Reads the fields ADR-0284 §8:1's projection carries for these facts, the latest
    understanding's ``meaning``, the trigger's ``origin`` and the record's
    ``derived_from_external``, and no input, response or ``content``. The view is
    data for a reader, not a rendering: a reader that renders it into a prompt
    renders the meaning as quoted source data (ADR-0098 §2), marked where it is
    marked.
    """
    external = rests_on_recorded_external_content(record.provenance)
    processing = record.processing_record
    if processing is None:
        return StoryStandingEpisode(
            activation_id=activation_id,
            occurred_at=record.occurred_at,
            meaning=None,
            in_progress=False,
            outside=external,
        )
    trigger = processing.trigger
    origin = trigger.origin if isinstance(trigger, RecordedChannelTrigger) else None
    latest = processing.understanding[-1] if processing.understanding else None
    return StoryStandingEpisode(
        activation_id=activation_id,
        occurred_at=record.occurred_at,
        meaning=None if latest is None else latest.meaning,
        in_progress=processing.is_open,
        outside=origin is InputOrigin.OUTSIDE or external,
    )


async def _related(
    stories: StoryStore, story: StoryHeader, entries: Sequence[StoryEntry]
) -> tuple[StoryRelated, ...]:
    """The stories ``story`` is part of, newest first, then those it contains, in link order.

    The reverse lookup is read after ``entries``, so where a story was moved from
    inside ``story`` to around it between the two reads, the later read decides and
    it is listed once, as a story ``story`` is part of.
    """
    related: list[StoryRelated] = []
    member = StoryMember(kind=StoryMemberKind.STORY, id=story.story_id)
    for parent in await stories.stories_of(member):
        count = await _member_count(stories, parent.story_id, story.story_id)
        related.append(
            StoryRelated(
                relation=StoryRelation.PART_OF, story_id=parent.story_id, member_count=count
            )
        )
    parents = {item.story_id for item in related}
    for entry in entries:
        if entry.member.kind is StoryMemberKind.STORY and entry.member.id not in parents:
            count = await _member_count(stories, entry.member.id, story.story_id)
            related.append(
                StoryRelated(
                    relation=StoryRelation.CONTAINS, story_id=entry.member.id, member_count=count
                )
            )
    return tuple(related)


async def _member_count(stories: StoryStore, related_id: str, story_id: str) -> int:
    """A related story's current member count, read as ADR-0289 §4:5 reads a story member's.

    Raises:
        StoryStoreError: If the store names a related story it cannot read back.
    """
    view = await stories.view(related_id, limit=1)
    if view is None:
        msg = f"story {story_id!r} is related to story {related_id!r}, which it cannot read"
        raise StoryStoreError(msg)
    return view.member_count
