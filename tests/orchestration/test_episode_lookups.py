"""The episode look-ups' reads and their runner, driven over stub stores (ADR-0358 §6-§10).

The search of past episodes, kept per band as recall's searches are, under the
threshold and the audience; the matters each episode belongs to; the origin's older
history, from a conversation's transcript or a channel's earlier episodes; one episode's
full record, each record it names read again; and :class:`LookUps` running each under
the round's scope and holding what it read for the glue.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from test_planning import _earlier, _episode, _relayed

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    ActionRequest,
    BeliefBand,
    CallShowed,
    CapabilityEffect,
    CapabilityResult,
    ChannelEpisode,
    ChannelEpisodePage,
    ChannelIdentity,
    DeletedMessage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    LabelKind,
    MemoryKind,
    MemoryRecord,
    MemorySearchResult,
    MessageAuthor,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProposedCall,
    RecordedCall,
    ShownRecord,
    ShownRecordKind,
    StoryHeader,
    StoryMember,
    StorySummary,
    StorySummaryLine,
    StorySummaryState,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
    TranscriptMessage,
    TranscriptPage,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.episode_lookups import EpisodeLookUpReads, OlderSource
from ai_assistant.orchestration.lookups import (
    LOOK_UP_LABEL_ARGUMENTS,
    READ_EPISODE,
    READ_OLDER_HISTORY,
    SEARCH_EPISODES,
    LookUps,
)
from ai_assistant.orchestration.planning import (
    CallOutcomeKind,
    EpisodeRead,
    EpisodesFound,
    OlderHistory,
    PlaceAuthor,
    offered_tools,
)
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pytest

_AT: Final = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="chat-1")


def _scored(record: EpisodicMemory, score: float | None) -> EpisodicMemory:
    return record.model_copy(update={"score": score})


class _Memory:
    """A ``MemoryStore`` stub: each band's search, the records by id, a channel's tail."""

    def __init__(
        self,
        *,
        bands: Mapping[BeliefBand, Sequence[MemoryRecord]] | None = None,
        held: Sequence[MemoryRecord] = (),
        channel: Sequence[EpisodicMemory] = (),
        raises: Exception | None = None,
    ) -> None:
        self.bands = dict(bands or {})
        self.held = {one.id: one for one in held}
        self.channel = list(channel)
        self.raises = raises
        self.searched: list[tuple[str, tuple[MemoryKind, ...], tuple[BeliefBand, ...]]] = []
        self.limits: list[int] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        if self.raises is not None:
            raise self.raises
        self.searched.append((query, tuple(kinds or ()), tuple(bands or ())))
        (band,) = tuple(bands or ())
        return MemorySearchResult(records=tuple(self.bands.get(band, ()))[:limit])

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        return {one: self.held[one] for one in record_ids if one in self.held}

    async def channel_episodes(
        self, channel: ChannelIdentity, *, after: int | None = None, limit: int
    ) -> ChannelEpisodePage:
        del after
        assert channel == LINE
        self.limits.append(limit)
        entries = tuple(
            ChannelEpisode(number=at, record=one) for at, one in enumerate(self.channel, 1)
        )
        return ChannelEpisodePage(entries=entries[-limit:], total=len(entries))


class _Stories:
    """A ``StoryStore`` stub: the stories each activation is in, and their summaries."""

    def __init__(
        self,
        of: Mapping[str, Sequence[str]],
        summaries: Mapping[str, StorySummary | None],
        merged: frozenset[str] = frozenset(),
    ) -> None:
        self.of = of
        self.summaries = summaries
        self.merged = merged

    async def stories_of(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        return tuple(
            StoryHeader(
                story_id=one,
                created_at=_AT,
                merged_into="story:other" if one in self.merged else None,
            )
            for one in self.of.get(member.id, ())
        )

    async def current_summary(self, story_id: str) -> StorySummaryState | None:
        if story_id not in self.summaries:
            return None
        return StorySummaryState(
            story=StoryHeader(story_id=story_id, created_at=_AT, merged_into=None),
            summary=self.summaries[story_id],
            pending_notes=(),
            pending_episodes=(),
            as_of=1,
        )


def _summary(*lines: str, version: int = 1, outside: bool = False) -> StorySummary:
    return StorySummary(
        version=version,
        written_at=_AT,
        lines=tuple(StorySummaryLine(text=one) for one in lines),
        outside=outside,
    )


def _message(position: int, author: MessageAuthor, text: str) -> TranscriptMessage:
    return TranscriptMessage(
        conversation_id="conv-1",
        position=position,
        written_at=_AT + timedelta(minutes=position),
        author=author,
        text=text,
        device_id="dev-1" if author is MessageAuthor.USER else None,
        message_id=f"m{position}" if author is MessageAuthor.USER else None,
    )


class _Conversations:
    """A ``ConversationStore`` stub: a transcript and which activation took each in."""

    def __init__(
        self,
        entries: Sequence[TranscriptMessage | DeletedMessage],
        taken: Mapping[int, str] | None = None,
    ) -> None:
        self.entries = list(entries)
        self.taken = dict(taken or {})

    async def transcript(
        self, conversation_id: str, *, before: int | None = None, limit: int = 50
    ) -> TranscriptPage | None:
        below = [one for one in self.entries if before is None or one.position < before]
        return TranscriptPage(
            conversation_id=conversation_id, entries=tuple(below[-limit:]), as_of=1
        )

    async def taken_in(
        self, conversation_id: str, *, positions: Sequence[int]
    ) -> Mapping[int, str]:
        del conversation_id
        return {one: self.taken[one] for one in positions if one in self.taken}


def _reads(memory_store: Any = None, **fields: Any) -> EpisodeLookUpReads:
    values: dict[str, Any] = {
        "memory": memory_store if memory_store is not None else _Memory(),
        "stories": None,
        "conversations": None,
        "threshold": 0.5,
        "limit": 6,
        "search_page": 2,
        "history_page": 2,
        "full_page": 20,
        "excerpt_chars": 500,
    }
    values.update(fields)
    return EpisodeLookUpReads(**values)


# --- §7: a search of past episodes -------------------------------------------------------


async def test_a_search_asks_each_band_for_episodes_and_keeps_what_clears_the_threshold() -> None:
    """§7:1, ADR-0281 §3:2-§3:3: per band, episodic records only, at or above the threshold."""
    kept = _scored(_episode("activation:kept"), 0.9)
    low = _scored(_episode("activation:low"), 0.1)
    unscored = _scored(_episode("activation:unscored"), None)
    later = _scored(_episode("activation:later"), 0.6)
    store = _Memory(
        bands={BeliefBand.ASSERTED: (kept, low, unscored), BeliefBand.DERIVED: (later,)}
    )

    found = await _reads(store).search("dentist", 1, audience=BOUNDED, owner_records=True)

    assert [one.record.id for one in found.episodes] == ["activation:kept", "activation:later"]
    assert store.searched == [
        ("dentist", (MemoryKind.EPISODIC,), (band,))
        for band in (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)
    ]
    assert not found.more


async def test_a_search_comes_in_pages() -> None:
    """§6:6: a page at a time, the result saying whether there are more."""
    records = [_scored(_episode(f"activation:{at}"), 0.9) for at in range(3)]
    store = _Memory(bands={BeliefBand.ASSERTED: records})

    first = await _reads(store).search("x", 1, audience=BOUNDED, owner_records=True)
    second = await _reads(store).search("x", 2, audience=BOUNDED, owner_records=True)

    assert [one.record.id for one in first.episodes] == ["activation:0", "activation:1"]
    assert first.more
    assert [one.record.id for one in second.episodes] == ["activation:2"]
    assert not second.more


async def test_a_search_on_an_unbounded_pass_asks_for_no_episode() -> None:
    """§7:3, ADR-0281 §4:2."""
    store = _Memory(bands={BeliefBand.ASSERTED: (_scored(_episode("activation:a"), 0.9),)})

    found = await _reads(store).search("x", 1, audience=UNBOUNDED, owner_records=True)

    assert found == EpisodesFound(unbounded=True)
    assert store.searched == []


async def test_each_episode_found_names_its_matters_as_the_audience_may_see_them() -> None:
    """§8:1, ADR-0307 §6:4: each matter's first line where the summary may be shown.

    A merged story is passed over; on a pass without owner-only records the summary is
    withheld.
    """
    store = _Memory(bands={BeliefBand.ASSERTED: (_scored(_episode("activation:a"), 0.9),)})
    stories = _Stories(
        of={"a": ("story:dentist", "story:merged", "story:new")},
        summaries={
            "story:dentist": _summary("The dentist.", "More.", version=3),
            "story:merged": _summary("Gone."),
            "story:new": None,
        },
        merged=frozenset({"story:merged"}),
    )
    reads = _reads(store, stories=stories)

    (shown,) = (await reads.search("x", 1, audience=BOUNDED, owner_records=True)).episodes
    (hidden,) = (await reads.search("x", 1, audience=BOUNDED, owner_records=False)).episodes

    dentist, new = shown.matters
    assert (dentist.story_id, dentist.summary_version, dentist.first_line) == (
        "story:dentist",
        3,
        "The dentist.",
    )
    assert (new.story_id, new.summary_version, new.first_line) == ("story:new", None, None)
    assert hidden.matters[0].withheld
    assert hidden.matters[0].first_line is None


# --- §9: the origin's older history -------------------------------------------------------


async def test_a_place_with_no_window_has_no_older_history_to_read() -> None:
    """§9:4: an event's place has no window."""
    assert await _reads().older(None, 1, audience=BOUNDED) == OlderHistory(readable=False)


async def test_a_conversations_older_history_is_its_transcript_before_the_window() -> None:
    """§9:2-§9:3: newest page first, a deleted message or one already shown not at all.

    A user's message is linked to the activation that took it in.
    """
    entries: list[TranscriptMessage | DeletedMessage] = [
        _message(1, MessageAuthor.USER, "oldest"),
        _message(2, MessageAuthor.ASSISTANT, "an old reply"),
        DeletedMessage(conversation_id="conv-1", position=3),
        _message(4, MessageAuthor.USER, "replied to, shown"),
        _message(5, MessageAuthor.USER, "in the window"),
    ]
    conversations = _Conversations(entries, taken={1: "old-activation"})
    source = OlderSource(conversation_id="conv-1", before=5, shown=frozenset({4, 5}))
    reads = _reads(conversations=conversations)

    first = await reads.older(source, 1, audience=BOUNDED)
    second = await reads.older(source, 2, audience=BOUNDED)
    third = await reads.older(source, 3, audience=BOUNDED)

    assert first.items == ()
    assert first.more
    assert [(one.author, one.text, one.episode_id) for one in second.items] == [
        (PlaceAuthor.USER, "oldest", "activation:old-activation"),
        (PlaceAuthor.ASSISTANT, "an old reply", None),
    ]
    assert not second.more
    assert third == OlderHistory(readable=True, page=3)


async def test_a_lines_older_history_is_its_earlier_episodes_on_the_channel() -> None:
    """§9:2, ADR-0323 §10:1: older than the oldest the window showed, newest first."""
    channel = [_episode(f"activation:{at}") for at in range(4)]
    store = _Memory(channel=channel)
    source = OlderSource(channel=LINE, episodes=frozenset({"activation:2", "activation:3"}))

    older = await _reads(store).older(source, 1, audience=BOUNDED)

    assert [one.id for one in older.episodes] == ["activation:1", "activation:0"]
    assert not older.more


async def test_a_lines_older_history_past_what_can_be_read_says_it_cannot() -> None:
    """§9:4: past the largest page the store reads, it cannot be read here."""
    channel = [_episode(f"activation:{at}") for at in range(1100)]
    store = _Memory(channel=channel)
    source = OlderSource(channel=LINE, episodes=frozenset({"activation:never-there"}))

    older = await _reads(store).older(source, 1, audience=BOUNDED)

    assert older == OlderHistory(readable=False)
    assert store.limits[-1] == 1000


# --- §10: one episode's full record -------------------------------------------------------


def _with_entries(record: EpisodicMemory, *entries: RecordedCall) -> EpisodicMemory:
    processing = record.processing_record
    assert processing is not None
    whole = EpisodeProcessingRecord.model_validate(
        {**processing.model_dump(), "call_records": [one.model_dump() for one in entries]}
    )
    return record.model_copy(update={"processing_record": whole})


async def test_the_full_view_reads_each_record_it_names_again_as_held_now() -> None:
    """§10:6, §6:3: a memory forgotten since is left out, as is one the store lost."""
    searched = _earlier(
        "round:one",
        calls=(ProposedCall(call_id="c1", name="search_memory", arguments={"query": "x"}),),
    )
    showed = CallShowed(
        parts=(
            ShownRecord(kind=ShownRecordKind.MEMORY, id="said"),
            ShownRecord(kind=ShownRecordKind.MEMORY, id="forgotten"),
            ShownRecord(kind=ShownRecordKind.STORY, id="story:dentist", summary_version=1),
        )
    )
    record = _with_entries(
        _episode("activation:full", rounds=(searched,)),
        RecordedCall(
            round="round:one",
            call_id="c1",
            capability="search_memory",
            effect=False,
            outcome=CallOutcomeKind.DONE,
            recorded_at=_AT,
            showed=showed,
        ),
    )
    said = memory("said", "dentist with Dr Rao", said_support(when=_AT, added_at=_AT))
    stories = _Stories(of={}, summaries={"story:dentist": _summary("The dentist now.", version=2)})
    reads = _reads(_Memory(held=(record, said)), stories=stories)

    read = await reads.full("activation:full", 1, audience=BOUNDED, owner_records=True)

    assert read.projection is not None
    assert read.projection.full_view
    assert set(read.memories) == {"said"}
    assert read.stories["story:dentist"].first_line == "The dentist now."
    assert read.stories["story:dentist"].summary_version == 2


async def test_an_episode_the_store_no_longer_holds_is_no_longer_kept() -> None:
    """§10:9."""
    read = await _reads().full("activation:gone", 1, audience=BOUNDED, owner_records=True)

    assert read == EpisodeRead(episode_id="activation:gone", page_size=20)


async def test_an_open_episode_is_still_running() -> None:
    """§10:2, ADR-0286: only a frozen episode is read; an open one is still running."""
    frozen = _episode("activation:live")
    assert frozen.processing_record is not None
    open_record = EpisodeProcessingRecord.model_validate(
        {
            **frozen.processing_record.model_dump(),
            "status": None,
            "reason": None,
            "ended_at": None,
            "stages": [],
            "understanding_omitted": None,
        }
    )
    live = frozen.model_copy(update={"processing_record": open_record, "outcome": None})

    read = await _reads(_Memory(held=(live,))).full(
        "activation:live", 1, audience=BOUNDED, owner_records=True
    )

    assert read.running
    assert read.projection is None


# --- the runner -------------------------------------------------------------------------


def _call(tool: Any, *, decision: str = "d1", **parameters: Any) -> ToolCall:
    request = ActionRequest(tool=tool, parameters=parameters)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    allowed = PermissionDecision.from_request(request, ruling, id=decision, decided_at=_AT)
    return ToolCall(request=request, decision=allowed)


def test_the_episode_look_ups_read_own_records_and_return_no_outside_text() -> None:
    """§6:1, §6:4: own records, never leaving the hub, safe to repeat, no outside text."""
    for one in (SEARCH_EPISODES, READ_EPISODE, READ_OLDER_HISTORY):
        assert one.effect is CapabilityEffect.OWN_RECORDS
        assert not one.leaves_hub
        assert not one.outcome_can_be_unknown
        assert one.safe_to_repeat
        assert one.result is CapabilityResult.NO_OUTSIDE_TEXT
    assert LOOK_UP_LABEL_ARGUMENTS["read_episode"] == {"episode": LabelKind.EPISODE}
    offered = offered_tools((SEARCH_EPISODES, READ_EPISODE, READ_OLDER_HISTORY))
    assert {one.name for one in offered} == {
        "search_episodes",
        "read_episode",
        "read_older_history",
    }


async def test_each_episode_look_up_reads_under_the_scope_and_holds_what_it_read() -> None:
    """§6:2: under the pass's audience; what it read held by its decision for the glue."""
    store = _Memory(bands={BeliefBand.ASSERTED: (_scored(_episode("activation:a"), 0.9),)})
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5, episodes=_reads(store))
    source = OlderSource(conversation_id="conv-1", before=None)

    with LookUps.scope(audience=BOUNDED, owner_records=True, older=source) as scope:
        searched = await look_ups.run(_call(SEARCH_EPISODES, decision="d1", query="dentist"))
        older = await look_ups.run(_call(READ_OLDER_HISTORY, decision="d2"))
        full = await look_ups.run(_call(READ_EPISODE, decision="d3", episode="activation:a"))

    for answer in (searched, older, full):
        assert isinstance(answer, ToolResult)
        assert answer.outcome is ToolOutcome.SUCCEEDED
    assert isinstance(scope.found["d1"], EpisodesFound)
    assert isinstance(scope.found["d2"], OlderHistory)
    assert isinstance(scope.found["d3"], EpisodeRead)


async def test_an_episode_look_up_outside_a_scope_reads_nothing_and_is_not_done() -> None:
    """§6:2."""
    store = _Memory()
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5, episodes=_reads(store))

    answer = await look_ups.run(_call(SEARCH_EPISODES, query="dentist"))

    assert isinstance(answer, ToolResult)
    assert answer.outcome is ToolOutcome.FAILED
    assert answer.failure is not None
    assert answer.failure.kind is ToolFailureKind.INTERNAL
    assert store.searched == []


async def test_a_blank_query_is_not_done() -> None:
    """A search names what it searches for; a blank query reads nothing."""
    store = _Memory()
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5, episodes=_reads(store))

    with LookUps.scope(audience=BOUNDED, owner_records=True):
        answer = await look_ups.run(_call(SEARCH_EPISODES, query="   "))

    assert isinstance(answer, ToolResult)
    assert answer.failure is not None
    assert answer.failure.kind is ToolFailureKind.INVALID_REQUEST
    assert store.searched == []


async def test_an_unreadable_store_makes_an_episode_look_up_not_done() -> None:
    reads = _reads(_Memory(raises=MemoryStoreError("down")))
    look_ups = LookUps(memory=FakeMemoryStore(), views=None, search_limit=5, episodes=reads)

    with LookUps.scope(audience=BOUNDED, owner_records=True) as scope:
        answer = await look_ups.run(_call(SEARCH_EPISODES, query="x"))

    assert isinstance(answer, ToolResult)
    assert answer.failure is not None
    assert answer.failure.kind is ToolFailureKind.UNAVAILABLE
    assert scope.found == {}


# --- review round 1 -------------------------------------------------------------------


async def test_an_older_message_of_a_relayed_input_is_marked_from_its_held_episode() -> None:
    """ADR-0351 §5:7, §9:3: read off the linked episode as held, whatever the windows hold."""
    entries: list[TranscriptMessage | DeletedMessage] = [
        _message(1, MessageAuthor.USER, "the dentist's own words"),
        _message(2, MessageAuthor.USER, "in the window"),
    ]
    conversations = _Conversations(entries, taken={1: "relay"})
    relayed = _relayed(_episode("activation:relay"))
    reads = _reads(_Memory(held=(relayed,)), conversations=conversations)
    source = OlderSource(conversation_id="conv-1", before=2, shown=frozenset({2}))

    older = await reads.older(source, 1, audience=BOUNDED)

    (item,) = older.items
    assert item.episode_id == "activation:relay"
    assert older.relayed == frozenset({"activation:relay"})
    assert older.withheld(item)


async def test_the_full_view_reads_the_matters_its_episode_belongs_to() -> None:
    """§8:1: by ``stories_of``, whatever the record referenced."""
    record = _episode("activation:full")
    stories = _Stories(
        of={"full": ("story:dentist",)}, summaries={"story:dentist": _summary("The dentist.")}
    )
    reads = _reads(_Memory(held=(record,)), stories=stories)

    read = await reads.full("activation:full", 1, audience=BOUNDED, owner_records=True)

    (matter,) = read.matters
    assert (matter.story_id, matter.first_line) == ("story:dentist", "The dentist.")


async def test_a_lines_older_history_reads_further_back_until_its_page_is_there() -> None:
    """§9:1: the channel grew since the window was read; the page is read from further back."""
    channel = [_episode(f"activation:{at}") for at in range(23)]
    store = _Memory(channel=channel)
    source = OlderSource(channel=LINE, episodes=frozenset({"activation:18", "activation:19"}))

    older = await _reads(store).older(source, 1, audience=BOUNDED)

    assert older.readable
    assert [one.id for one in older.episodes] == ["activation:17", "activation:16"]
    assert older.more


async def test_a_lines_older_history_reads_back_past_episodes_the_audience_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§9:1, §6:3: a page of admitted episodes, however many the audience refuses."""
    import ai_assistant.orchestration.episode_lookups as module  # noqa: PLC0415

    refused = {"activation:15", "activation:16", "activation:17"}

    def admitted(audience: object, records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        del audience
        return [one for one in records if one.id not in refused]

    monkeypatch.setattr(module, "admitted_to_understanding", admitted)
    channel = [_episode(f"activation:{at}") for at in range(20)]
    source = OlderSource(channel=LINE, episodes=frozenset({"activation:18", "activation:19"}))

    older = await _reads(_Memory(channel=channel)).older(source, 1, audience=UNBOUNDED)

    assert older.readable
    assert [one.id for one in older.episodes] == ["activation:14", "activation:13"]


# --- review round 7 -------------------------------------------------------------------


def _opened(record: EpisodicMemory) -> EpisodicMemory:
    """``record`` as its activation holds it while it runs: open, nothing frozen yet."""
    processing = record.processing_record
    assert processing is not None
    open_record = EpisodeProcessingRecord.model_validate(
        {
            **processing.model_dump(),
            "status": None,
            "reason": None,
            "ended_at": None,
            "stages": [],
        }
    )
    return record.model_copy(update={"processing_record": open_record, "outcome": None})


async def test_an_older_message_of_a_relayed_input_still_running_is_withheld() -> None:
    """ADR-0351 §5:7, §5:11: an open episode is never projected, and its relay mark is
    read off its latest understanding version all the same."""
    entries: list[TranscriptMessage | DeletedMessage] = [
        _message(1, MessageAuthor.USER, "the dentist's own words"),
        _message(2, MessageAuthor.USER, "in the window"),
    ]
    conversations = _Conversations(entries, taken={1: "relay"})
    running = _opened(_relayed(_episode("activation:relay")))
    assert running.processing_record is not None
    assert running.processing_record.is_open
    reads = _reads(_Memory(held=(running,)), conversations=conversations)
    source = OlderSource(conversation_id="conv-1", before=2, shown=frozenset({2}))

    older = await reads.older(source, 1, audience=BOUNDED)

    (item,) = older.items
    assert older.relayed == frozenset({"activation:relay"})
    assert older.withheld(item)


async def test_a_lines_older_history_cannot_be_read_once_the_windows_episodes_are_gone() -> None:
    """§9:1, §9:4: with the episodes the window showed gone, nothing marks where the
    older history ends, so a later arrival is never taken for an older one."""
    channel = [_episode(f"activation:{at}") for at in (0, 1, 4, 5)]
    source = OlderSource(channel=LINE, episodes=frozenset({"activation:2", "activation:3"}))

    older = await _reads(_Memory(channel=channel)).older(source, 1, audience=BOUNDED)

    assert older == OlderHistory(readable=False)


def _at(record: EpisodicMemory, minutes: int) -> EpisodicMemory:
    """``record``, its activation started ``minutes`` from ``_AT``."""
    processing = record.processing_record
    assert processing is not None
    started = _AT + timedelta(minutes=minutes)
    return record.model_copy(
        update={
            "occurred_at": started,
            "processing_record": processing.model_copy(
                update={"started_at": started, "ended_at": started}
            ),
        }
    )


async def test_a_lines_older_history_where_the_window_showed_none_started_before_this() -> None:
    """§9:1: where the window showed no episode, one that started after this activation
    did came after the window was read, and is not older; without that start, none is
    known older."""
    channel = [_at(_episode("activation:old"), -10), _at(_episode("activation:new"), 5)]
    store = _Memory(channel=channel)

    older = await _reads(store).older(OlderSource(channel=LINE, started=_AT), 1, audience=BOUNDED)
    unknown = await _reads(store).older(OlderSource(channel=LINE), 1, audience=BOUNDED)

    assert older.readable
    assert [one.id for one in older.episodes] == ["activation:old"]
    assert not older.more
    assert unknown == OlderHistory(readable=False)
