"""Planning's episode look-ups' reads: past episodes, one whole, and the older history.

ADR-0358 §7-§10. Each is a read of the assistant's own records (§6:1), run by
:class:`~ai_assistant.orchestration.lookups.LookUps` through acting's own-records seam
under the pass's audience (§6:2), which reaches these reads through
:class:`EpisodeLookUpReads`. They read; they write nothing and call no model.

**A search of past episodes** (§7). One memory-store search per band for episodic
records, ``ASSERTED`` then ``ATTESTED`` then ``DERIVED`` (ADR-0072 §5), as recall's band
searches are made (ADR-0281 §3:2-§3:3): a record is kept only where its score is at or
above the recall threshold and the audience predicate admits it (ADR-0282 §2:7), until the
composition root's limit is filled. On a pass of unbounded audience no episode is asked
for (ADR-0281 §4:2, §7:3). Each episode kept comes with the matters it belongs to, read by
``StoryStore.stories_of`` as recall reads them, each with its summary's first line where
the pass may be shown the summary (§8:1, ADR-0307 §6:4).

**The origin's older history** (§9). Read from where the place window came from
(:class:`OlderSource`): the medium's history, a conversation's transcript before the
oldest message its window showed, a page at a time, newest page first, each message by
its author, a user's linked to the activation that took it in where the conversation's
bookkeeping records one, and a deleted message not at all; or, for a kind whose window is
the place's recent episodes (ADR-0323 §10:1), the earlier episodes on that channel and
place, each admitted by the audience predicate. A place with no window, as an event's,
cannot be read here (§9:4).

**One episode's full record** (§10). Read by its stored id, the audience predicate
applied: one the store no longer holds, or that the predicate refuses, is no longer kept;
one still open is still running (§10:2). Its projection is the full view
(:func:`~ai_assistant.core.episode_encoding.project_episode` with ``full_view``, which only
this look-up sets, §11:5), under the pass's owner-only placement (§10:5), and every record
it names by reference is read again, as it is held now, the predicate applied (§10:6).

**It logs nothing of what it reads** (ADR-0275 §8): its runner logs stage and
code-owned reason only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.episode_encoding import project_episode
from ai_assistant.core.types import (
    BeliefBand,
    DeletedMessage,
    EpisodicMemory,
    Memory,
    MemoryKind,
    MessageAuthor,
    ShownRecord,
    ShownRecordKind,
    StoryMember,
    StoryMemberKind,
)
from ai_assistant.orchestration.disclosure import UnboundedAudienceSupply, admitted_to_understanding
from ai_assistant.orchestration.planning import (
    EpisodeRead,
    EpisodesFound,
    EpisodeShown,
    MatterShown,
    OlderHistory,
    PlaceAuthor,
    PlaceItem,
)
from ai_assistant.orchestration.stories import episode_address
from ai_assistant.orchestration.story_privacy import SummaryVisibility, activation_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ai_assistant.core.protocols import ConversationStore, MemoryStore, StoryStore
    from ai_assistant.core.types import (
        ChannelEpisode,
        ChannelIdentity,
        EpisodeProjection,
        MemoryRecord,
        StorySummaryState,
        TranscriptMessage,
    )
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = ["EpisodeLookUpReads", "OlderSource"]

#: ADR-0072 §5's consumer-side precedence, the order the bands are searched in.
_BANDS: Final = (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)

#: The largest page ``MemoryStore.channel_episodes`` reads.
_CHANNEL_PAGE_MAX: Final = 1000


@dataclass(frozen=True, slots=True)
class OlderSource:
    """Where an activation's place window came from, which its older history is read from.

    ADR-0358 §9:2. Exactly one of the two sources is set: a conversation, whose window is
    read from the medium, or a channel whose kind's window is the place's recent episodes
    (ADR-0323 §10:1). A place with no window has no source.

    Attributes:
        conversation_id: The conversation whose transcript the window was read from.
        before: The position of the oldest of the conversation's recent messages the
            window showed, the input's included, below which its older history lies;
            ``None`` where it showed none.
        shown: The positions of every message the window showed, the earlier ones a
            reply named included, which the older history does not show again.
        channel: The channel and place whose recent episodes the window was read from.
        episodes: The ids of the episodes that window showed items of.

    Raises:
        ValueError: If neither source is set, or both are.
    """

    conversation_id: str | None = None
    before: int | None = None
    shown: frozenset[int] = frozenset()
    channel: ChannelIdentity | None = None
    episodes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        """One source, a conversation or a channel's episodes."""
        if (self.conversation_id is None) == (self.channel is None):
            msg = "an older history is read from a conversation or a channel's episodes"
            raise ValueError(msg)


class EpisodeLookUpReads:
    """The episode look-ups' reads over the memory, story and conversation stores."""

    def __init__(  # noqa: PLR0913 — three stores and the composition root's five numbers
        self,
        *,
        memory: MemoryStore,
        stories: StoryStore | None,
        conversations: ConversationStore | None,
        threshold: float,
        limit: int,
        search_page: int,
        history_page: int,
        full_page: int,
        excerpt_chars: int,
    ) -> None:
        """Wire the reads to their stores and the composition root's numbers.

        Args:
            memory: The memory store episodes are searched in and read from.
            stories: The story store the matters an episode belongs to are read from,
                or ``None`` where none is wired, and then no matter is named.
            conversations: The conversation store a conversation's older history is
                read from, or ``None`` where none is wired.
            threshold: The recall threshold, set for the embedder (ADR-0281 §3).
            limit: The most episodes one search keeps (§7:1).
            search_page: How many of them one page shows (§6:6).
            history_page: How many older items, or earlier episodes, one page shows.
            full_page: How many of a full view's parts one page shows.
            excerpt_chars: The bound a full view's texts are cut to (ADR-0284 §8:1).

        Raises:
            ValueError: If a number that counts is below 1.
        """
        if min(limit, search_page, history_page, full_page, excerpt_chars) < 1:
            msg = "the episode look-ups' limit, pages and excerpt bound are at least 1"
            raise ValueError(msg)
        self._memory = memory
        self._stories = stories
        self._conversations = conversations
        self._threshold = threshold
        self._limit = limit
        self._search_page = search_page
        self._history_page = history_page
        self._full_page = full_page
        self._excerpt_chars = excerpt_chars

    # --- §7: a search of past episodes ---

    async def search(
        self, query: str, page: int, *, audience: TurnSupply, owner_records: bool
    ) -> EpisodesFound:
        """One page of the past episodes found for ``query``, each with its matters.

        Raises:
            MemoryStoreError: If the store cannot be searched.
            StoryStoreError: If the story store cannot be read.
        """
        if isinstance(audience, UnboundedAudienceSupply):
            return EpisodesFound(page=page, unbounded=True)
        kept: dict[str, EpisodicMemory] = {}
        for band in _BANDS:
            if len(kept) >= self._limit:
                break
            found = await self._memory.search(
                query, limit=self._limit, kinds=(MemoryKind.EPISODIC,), bands=(band,)
            )
            for record in admitted_to_understanding(audience, found.records):
                if len(kept) >= self._limit:
                    break
                if self._kept(record) and record.id not in kept:
                    assert isinstance(record, EpisodicMemory)  # noqa: S101 — `_kept` checks it
                    kept[record.id] = record
        records = list(kept.values())
        start = (page - 1) * self._search_page
        shown = records[start : start + self._search_page]
        visibility = SummaryVisibility(owner_records=owner_records)
        episodes = [
            EpisodeShown(record=record, matters=await self._matters(record, visibility))
            for record in shown
        ]
        return EpisodesFound(
            episodes=tuple(episodes),
            page=page,
            more=len(records) > start + self._search_page,
        )

    def _kept(self, record: MemoryRecord) -> bool:
        """A frozen episode at or above the threshold: a NaN score is not, nor none."""
        if not isinstance(record, EpisodicMemory):
            return False
        processing = record.processing_record
        if processing is not None and processing.is_open:
            return False
        score = record.score
        return score is not None and score >= self._threshold

    async def _matters(
        self, record: EpisodicMemory, visibility: SummaryVisibility
    ) -> tuple[MatterShown, ...]:
        """The matters an episode belongs to, as recall reads them (ADR-0300 §7:1, §8:1).

        Only for an episode whose stored id is its activation's episode; one merged into
        another is passed over, and one the store no longer holds left out.

        Raises:
            StoryStoreError: If the story store cannot be read.
        """
        activation = activation_of(record)
        if self._stories is None or activation is None or record.id != episode_address(activation):
            return ()
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation)
        matters: list[MatterShown] = []
        for header in await self._stories.stories_of(member):
            if header.merged_into is not None:
                continue
            state = await self._stories.current_summary(header.story_id)
            if state is not None:
                matters.append(_matter(state, visibility))
        return tuple(matters)

    # --- §9: the origin's older history ---

    async def older(
        self, source: OlderSource | None, page: int, *, audience: TurnSupply
    ) -> OlderHistory:
        """One page of the origin's older history, newest page first.

        Raises:
            ConversationStoreError: If the conversation store cannot be read.
            MemoryStoreError: If the memory store cannot be read.
        """
        if source is None:
            return OlderHistory(readable=False)
        if source.conversation_id is not None:
            if self._conversations is None:
                return OlderHistory(readable=False)
            return await self._medium(source, source.conversation_id, page)
        assert source.channel is not None  # noqa: S101 — the source's validator holds it
        return await self._earlier_episodes(source, source.channel, page, audience)

    async def _medium(self, source: OlderSource, conversation_id: str, page: int) -> OlderHistory:
        """A conversation's messages before the oldest its window showed (§9:2-§9:3).

        Read a page at a time below the oldest message the window showed, newest page
        first: each message by its author, a user's message linked to the activation that
        took it in, and a deleted message, or one the window already showed, not at all.

        Raises:
            ConversationStoreError: If the store cannot be read.
        """
        assert self._conversations is not None  # noqa: S101 — checked by the caller
        if source.before is None:
            return OlderHistory(readable=True, page=page)
        cursor = source.before
        entries: Sequence[TranscriptMessage | DeletedMessage] = ()
        more = False
        for turn in range(page):
            read = await self._conversations.transcript(
                conversation_id, before=cursor, limit=self._history_page + 1
            )
            if read is None or not read.entries:
                return OlderHistory(readable=True, page=page)
            entries = read.entries[-self._history_page :]
            more = len(read.entries) > self._history_page
            cursor = entries[0].position
            if not more and turn < page - 1:
                return OlderHistory(readable=True, page=page)
        messages = [
            one
            for one in entries
            if not isinstance(one, DeletedMessage) and one.position not in source.shown
        ]
        links = await self._conversations.taken_in(
            conversation_id,
            positions=[one.position for one in messages if one.author is MessageAuthor.USER],
        )
        return OlderHistory(
            readable=True,
            items=tuple(_item(one, links) for one in messages),
            page=page,
            more=more,
        )

    async def _earlier_episodes(
        self, source: OlderSource, channel: ChannelIdentity, page: int, audience: TurnSupply
    ) -> OlderHistory:
        """The episodes on the window's channel and place older than any it showed (§9:2).

        The channel's tail is read, growing until it reaches the oldest episode the
        window showed or the whole channel, as ``MemoryStore.channel_episodes`` reads
        only from the tail or forward; past the largest page it reads, the older history
        cannot be read here (§9:4).

        Raises:
            MemoryStoreError: If the store cannot be read.
        """
        limit = min(_CHANNEL_PAGE_MAX, len(source.episodes) + page * self._history_page + 1)
        while True:
            read = await self._memory.channel_episodes(channel, limit=limit)
            entries: Sequence[ChannelEpisode] = read.entries
            first = next(
                (at for at, one in enumerate(entries) if one.record.id in source.episodes), None
            )
            whole = len(entries) < limit
            if first is not None or whole or limit >= _CHANNEL_PAGE_MAX:
                break
            limit = min(_CHANNEL_PAGE_MAX, limit * 2)
        if first is None and not whole:
            return OlderHistory(readable=False, page=page)
        older = entries if first is None else entries[:first]
        truncated = read.total > len(entries)
        records = [
            record
            for record in admitted_to_understanding(
                audience, [one.record for one in reversed(older)]
            )
            if isinstance(record, EpisodicMemory)
        ]
        start = (page - 1) * self._history_page
        shown = records[start : start + self._history_page]
        if not shown and truncated:
            return OlderHistory(readable=False, page=page)
        return OlderHistory(
            readable=True,
            episodes=tuple(shown),
            page=page,
            more=len(records) > start + self._history_page or truncated,
        )

    # --- §10: one episode's full record ---

    async def full(
        self, episode_id: str, page: int, *, audience: TurnSupply, owner_records: bool
    ) -> EpisodeRead:
        """One page of an episode's full record, each record it names read as held now.

        Raises:
            MemoryStoreError: If the memory store cannot be read.
            StoryStoreError: If the story store cannot be read.
        """
        held = await self._memory.get_many([episode_id])
        record = held.get(episode_id)
        if not isinstance(record, EpisodicMemory) or not admitted_to_understanding(
            audience, (record,)
        ):
            return EpisodeRead(episode_id=episode_id, page=page, page_size=self._full_page)
        processing = record.processing_record
        if processing is not None and processing.is_open:
            return EpisodeRead(
                episode_id=episode_id, running=True, page=page, page_size=self._full_page
            )
        projection = project_episode(
            record, excerpt_chars=self._excerpt_chars, owner_records=owner_records, full_view=True
        )
        named = _named(projection)
        records = await self._again(
            [one.id for one in named if one.kind is not ShownRecordKind.STORY], audience
        )
        visibility = SummaryVisibility(owner_records=owner_records)
        stories: dict[str, MatterShown] = {}
        if self._stories is not None:
            for one in named:
                if one.kind is ShownRecordKind.STORY and one.id not in stories:
                    state = await self._stories.current_summary(one.id)
                    if state is not None:
                        stories[one.id] = _matter(state, visibility)
        return EpisodeRead(
            episode_id=episode_id,
            record=record,
            projection=projection,
            memories={key: one for key, one in records.items() if isinstance(one, Memory)},
            stories=stories,
            episodes=frozenset(
                key
                for key, one in records.items()
                if isinstance(one, EpisodicMemory) and key != episode_id
            ),
            page=page,
            page_size=self._full_page,
        )

    async def _again(self, ids: Iterable[str], audience: TurnSupply) -> dict[str, MemoryRecord]:
        """The records ``ids`` name, as held now, the audience predicate applied (§10:6).

        Raises:
            MemoryStoreError: If the store cannot be read.
        """
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}
        held = await self._memory.get_many(wanted)
        admitted = admitted_to_understanding(audience, [held[one] for one in wanted if one in held])
        return {one.id: one for one in admitted}


def _named(projection: EpisodeProjection) -> tuple[ShownRecord, ...]:
    """Every record a full view names by reference: what recall found, what calls showed."""
    named: list[ShownRecord] = [one for run in projection.recalled for one in run.found]
    for call in projection.calls:
        if call.showed is not None:
            named.extend(one for one in call.showed.parts if isinstance(one, ShownRecord))
    return tuple(named)


def _matter(state: StorySummaryState, visibility: SummaryVisibility) -> MatterShown:
    """A matter, as an audience may be shown it (ADR-0307 §6:4, ADR-0304 §4)."""
    summary = state.summary
    shown = summary is not None and visibility.summary()
    return MatterShown(
        story_id=state.story.story_id,
        summary_version=None if summary is None else summary.version,
        first_line=(
            summary.lines[0].text if shown and summary is not None and summary.lines else None
        ),
        outside=shown and summary is not None and summary.outside,
        withheld=summary is not None and not shown,
    )


def _item(message: TranscriptMessage, links: Mapping[int, str]) -> PlaceItem:
    """One older message, as the place window shows an item (§9:3, ADR-0303 §7:1)."""
    linked = links.get(message.position)
    return PlaceItem(
        author=PlaceAuthor.USER if message.author is MessageAuthor.USER else PlaceAuthor.ASSISTANT,
        text=message.text,
        at=message.written_at,
        episode_id=None if linked is None else episode_address(linked),
    )
