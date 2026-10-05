"""The conversation lifecycle: every sequence that spans the conversation and memory stores.

ADR-0074 §9 assigns this list here rather than to the shared conformance suite,
and says why: "a conformance suite exercises one store against one contract; §8's
ordering and its serialisation span two stores and the coordinator between them".
Since ADR-0283 a conversation's history, membership and deletion have one source —
the episodes on its channel — so every case below seeds that channel directly
(``channel_episodes.conversation_episode``) and asserts what the stage reads from it
or destroys on it. How an episode is *written* is the writer's, and its own suite
(``test_activation_writer.py``) owns it.

Both stores are canonical fakes from ``ai_assistant.testing``, so nothing here
imports a subsystem concrete (CLAUDE.md golden rule 1) — except the case that has to
survive a *reopen*, which is the whole point of a tombstone and needs a persistent
conversation store.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from channel_episodes import channel_ids, conversation_episode

from ai_assistant.core.errors import (
    AssistantError,
    ConversationStoreError,
    MemoryStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    ActionPlan,
    Goal,
    GoalBrief,
    GoalInterpretation,
    Ground,
    MemorySource,
    ParkedBinding,
    ParkedRead,
    ParkedReadDisposition,
    Provenance,
    SpokenDelivery,
    SpokenDeliveryState,
    Validity,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.orchestration.conversations import (
    HISTORY_REPLAY_BOUND,
    ConversationLifecycle,
    ParkingOrigin,
)
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeParkedReads,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.types import ChannelEpisodeId, ChannelEpisodePage, ChannelIdentity

AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

RETENTION = 30 * DAY
GRACE = HOUR

UNSTAMPED = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
COMPLETE = SpokenDelivery(
    state=SpokenDeliveryState.COMPLETE,
    played=timedelta(seconds=9, milliseconds=800),
    rendered=timedelta(seconds=9, milliseconds=800),
)


class MovableClock:
    """A clock a case can step forward, so a horizon is reachable in a test."""

    def __init__(self, start: datetime = AT) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._now += delta


class Wiring:
    """A stage and the stores behind it, all sharing one clock."""

    def __init__(  # noqa: PLR0913 — one knob per store seam a case may need to vary
        self,
        *,
        clock: MovableClock | None = None,
        retention: timedelta | None = RETENTION,
        grace: timedelta = GRACE,
        memory: FakeMemoryStore | None = None,
        conversations: FakeConversationStore | None = None,
        parked_reads: FakeParkedReads | None = None,
    ) -> None:
        self.clock = clock if clock is not None else MovableClock()
        self.retention = retention
        self.memory = memory if memory is not None else FakeMemoryStore(now=self.clock)
        self.conversations = (
            conversations
            if conversations is not None
            else FakeConversationStore(now=self.clock, retention=retention, tombstone_grace=grace)
        )
        # ``None`` unless a case asks for one: a stage wired without one carries out
        # §8 exactly as it did before ADR-0244 — which is the arm below that holds
        # the absence.
        self.parked_reads = parked_reads
        self.stage = ConversationLifecycle(
            conversations=self.conversations,
            memory=self.memory,
            retention=retention,
            now=self.clock,
            parked_reads=parked_reads,
        )

    async def seed(  # noqa: PLR0913 — one keyword per axis a seeded episode varies
        self,
        conversation_id: str,
        episode_id: str,
        *,
        completed: bool = True,
        delivery: SpokenDelivery | None = None,
        occurred_at: datetime | None = None,
        parks: ParkedBinding | None = None,
        expires_at: datetime | None = None,
        validity: Validity | None = None,
        unexpiring: bool = False,
    ) -> str:
        """Put one episode on ``conversation_id``'s channel, as the writer leaves it.

        The episode first, then ``record_turn`` — ADR-0283 §7's order — so the
        conversation's ``last_turn_at`` and its delivery row are what a written turn
        leaves. The expiry is the writer's (``occurred_at`` plus the retention)
        unless a case names one or asks for none.
        """
        at = occurred_at if occurred_at is not None else self.clock()
        if expires_at is None and not unexpiring and self.retention is not None:
            expires_at = at + self.retention
        await self.memory.add(
            conversation_episode(
                conversation_id,
                episode_id,
                occurred_at=at,
                completed=completed,
                parks=parks,
                expires_at=expires_at,
                validity=validity or Validity(),
            )
        )
        await self.conversations.record_turn(
            conversation_id, episode_id=episode_id, occurred_at=at, delivery=delivery
        )
        return episode_id


async def _seed_turns(wiring: Wiring, count: int) -> tuple[str, list[str]]:
    """Start a conversation and put ``count`` completed episodes on its channel."""
    conversation = await wiring.stage.begin(None)
    episodes = [
        await wiring.seed(conversation.id, f"activation:{conversation.id}-{index}")
        for index in range(count)
    ]
    return conversation.id, episodes


# --- continuity: reading the channel back (ADR-0283 §4:1) ----------------


async def test_history_returns_the_channels_episodes_oldest_first() -> None:
    """§4:1: the conversation's recent episodes, in number order, as records."""
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, 3)

    history = await wiring.stage.history(conversation_id)

    assert [record.id for record in history.records] == episodes
    assert history.degraded is False


async def test_the_order_is_the_episodes_numbers_and_never_their_instants() -> None:
    """§1: a channel's order is its episodes' numbers, never a timestamp.

    The later-written episode carries the *earlier* instant, so an implementation
    that sorted by ``occurred_at`` would replay the conversation backwards.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    first = await wiring.seed(conversation.id, "activation:first", occurred_at=AT + HOUR)
    second = await wiring.seed(conversation.id, "activation:second", occurred_at=AT)

    history = await wiring.stage.history(conversation.id)

    assert [record.id for record in history.records] == [first, second]


async def test_history_reads_a_pass_that_ended_before_capture() -> None:
    """ADR-0284 §6:2: a pass that ended early is on the channel and in its history.

    Superseding ADR-0283 §4:1's eligibility filter: no read filters on status, so
    the episode is replayed in its place with its status, and the digest counts it.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    kept = await wiring.seed(conversation.id, "activation:kept")
    await wiring.seed(conversation.id, "activation:ended-early", completed=False)
    last = await wiring.seed(conversation.id, "activation:last")

    history = await wiring.stage.history(conversation.id)

    assert [record.id for record in history.records] == [kept, "activation:ended-early", last]
    assert await channel_ids(wiring.memory, conversation.id) == [
        kept,
        "activation:ended-early",
        last,
    ]
    digest = await wiring.stage.digest(conversation.id)
    assert digest is not None
    assert digest.recorded_turns == 3


async def test_history_skips_a_deleted_episode_without_resurrecting_it() -> None:
    """§4:1: a gap, never an error — the read is already filtered by liveness."""
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, 3)
    assert await wiring.memory.delete(episodes[1]) is True

    history = await wiring.stage.history(conversation_id)

    assert [record.id for record in history.records] == [episodes[0], episodes[2]]
    assert history.degraded is False, "a gap is an ordinary state, not a degradation"


async def test_history_reads_the_newest_episodes_within_the_replay_bound() -> None:
    """§4:1: the replay bound is the page, and the page is the channel's newest."""
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, HISTORY_REPLAY_BOUND + 5)

    history = await wiring.stage.history(conversation_id)

    assert [record.id for record in history.records] == episodes[-HISTORY_REPLAY_BOUND:]


async def test_a_run_of_failed_passes_takes_its_place_in_the_replay_page() -> None:
    """ADR-0284 §6:2: the page is the channel's newest episodes, failed ones included.

    A bound's worth of completed episodes followed by five a pass ended early left:
    the five are the newest the conversation has, so they are in the page and the
    five oldest are not.
    """
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, HISTORY_REPLAY_BOUND)
    for index in range(5):
        await wiring.seed(conversation_id, f"activation:ended-{index}", completed=False)

    history = await wiring.stage.history(conversation_id)

    ended = [f"activation:ended-{index}" for index in range(5)]
    assert [record.id for record in history.records] == (episodes + ended)[-HISTORY_REPLAY_BOUND:]


async def test_history_pairs_each_episode_with_its_delivery() -> None:
    """§10, ADR-0205 §5: a delivery fact travels with the episode it qualifies.

    A spoken turn's row starts ``UNKNOWN`` and a device's report stamps it; a typed
    turn has no row at all and is simply absent from the mapping.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    spoken = await wiring.seed(conversation.id, "activation:spoken", delivery=UNSTAMPED)
    typed = await wiring.seed(conversation.id, "activation:typed")
    unreported = await wiring.seed(conversation.id, "activation:unreported", delivery=UNSTAMPED)
    assert await wiring.conversations.record_delivery(
        conversation.id, episode_id=spoken, delivery=COMPLETE
    )

    history = await wiring.stage.history(conversation.id)

    assert [record.id for record in history.records] == [spoken, typed, unreported]
    assert dict(history.deliveries) == {spoken: COMPLETE, unreported: UNSTAMPED}


async def test_a_delivery_whose_episode_is_outside_the_page_is_never_carried() -> None:
    """§10: one ``deliveries`` call, for exactly the episodes the page returned."""

    class Recording(FakeConversationStore):
        def __init__(self) -> None:
            super().__init__(now=clock, retention=RETENTION)
            self.asked: list[tuple[str, ...]] = []

        async def deliveries(
            self, conversation_id: str, *, episode_ids: Sequence[str]
        ) -> Mapping[str, SpokenDelivery]:
            self.asked.append(tuple(episode_ids))
            return await super().deliveries(conversation_id, episode_ids=episode_ids)

    clock = MovableClock()
    conversations = Recording()
    wiring = Wiring(clock=clock, conversations=conversations)
    conversation = await wiring.stage.begin(None)
    old = await wiring.seed(conversation.id, "activation:old", delivery=UNSTAMPED)
    newest = [
        await wiring.seed(conversation.id, f"activation:new-{index}")
        for index in range(HISTORY_REPLAY_BOUND)
    ]

    history = await wiring.stage.history(conversation.id)

    assert conversations.asked == [tuple(newest)]
    assert old not in history.deliveries


async def test_history_of_a_conversation_with_no_episodes_asks_for_no_deliveries() -> None:
    """§10: an empty page reads nothing further."""

    class Recording(FakeConversationStore):
        def __init__(self) -> None:
            super().__init__(now=clock, retention=RETENTION)
            self.asked = 0

        async def deliveries(
            self, conversation_id: str, *, episode_ids: Sequence[str]
        ) -> Mapping[str, SpokenDelivery]:
            self.asked += 1
            return await super().deliveries(conversation_id, episode_ids=episode_ids)

    clock = MovableClock()
    conversations = Recording()
    wiring = Wiring(clock=clock, conversations=conversations)
    conversation = await wiring.stage.begin(None)

    history = await wiring.stage.history(conversation.id)

    assert history.records == ()
    assert history.degraded is False
    assert conversations.asked == 0


async def test_history_of_a_stamped_conversation_is_degraded_and_reads_no_channel() -> None:
    """§4:1: a ``get`` that answers nothing for a stamped conversation comes first."""

    class Watching(FakeMemoryStore):
        reads = 0

        async def channel_episodes(
            self,
            channel: ChannelIdentity,
            *,
            after: int | None = None,
            limit: int,
        ) -> ChannelEpisodePage:
            self.reads += 1
            return await super().channel_episodes(channel, after=after, limit=limit)

    clock = MovableClock()
    memory = Watching(now=clock)
    wiring = Wiring(clock=clock, memory=memory)
    conversation_id, _ = await _seed_turns(wiring, 1)
    await wiring.conversations.stamp_deleted(conversation_id)
    memory.reads = 0

    history = await wiring.stage.history(conversation_id)

    assert history.records == ()
    assert history.degraded is True
    assert memory.reads == 0


@pytest.mark.parametrize("failing", ["memory", "conversations"])
async def test_history_degrades_rather_than_failing_the_turn(failing: str) -> None:
    """Losing continuity costs the answer its history, not its usefulness.

    Each store faults the one read history makes of it: the channel read, and the
    delivery read that follows it.
    """

    class FaultingMemory(FakeMemoryStore):
        fail = False

        async def channel_episodes(
            self,
            channel: ChannelIdentity,
            *,
            after: int | None = None,
            limit: int,
        ) -> ChannelEpisodePage:
            if self.fail:
                msg = "the store would not read"
                raise MemoryStoreError(msg)
            return await super().channel_episodes(channel, after=after, limit=limit)

    class FaultingConversations(FakeConversationStore):
        fail = False

        async def deliveries(
            self, conversation_id: str, *, episode_ids: Sequence[str]
        ) -> Mapping[str, SpokenDelivery]:
            if self.fail:
                msg = "the index would not read"
                raise ConversationStoreError(msg)
            return await super().deliveries(conversation_id, episode_ids=episode_ids)

    clock = MovableClock()
    memory = FaultingMemory(now=clock)
    conversations = FaultingConversations(now=clock, retention=RETENTION)
    wiring = Wiring(clock=clock, memory=memory, conversations=conversations)
    conversation_id, _ = await _seed_turns(wiring, 1)
    if failing == "memory":
        memory.fail = True
    else:
        conversations.fail = True

    history = await wiring.stage.history(conversation_id)

    assert history.records == ()
    assert history.degraded is True


# --- the digest a deletion ceremony shows (ADR-0283 §4:2) ----------------


async def test_the_digest_counts_every_episode_on_the_channel() -> None:
    """§4:2: the count is the channel's, completed or not, and no other conversation's."""
    wiring = Wiring()
    conversation_id, _ = await _seed_turns(wiring, 2)
    await wiring.seed(conversation_id, "activation:ended-early", completed=False)
    other_id, _ = await _seed_turns(wiring, 4)

    digest = await wiring.stage.digest(conversation_id)

    assert digest is not None
    assert digest.id == conversation_id
    assert digest.recorded_turns == 3
    assert digest.last_turn_at == AT
    other = await wiring.stage.digest(other_id)
    assert other is not None
    assert other.recorded_turns == 4


async def test_the_digest_of_a_conversation_with_no_episodes_counts_none() -> None:
    """§4:2: an emptied conversation still shows, with nothing to destroy but itself."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    digest = await wiring.stage.digest(conversation.id)

    assert digest is not None
    assert digest.recorded_turns == 0
    assert digest.last_turn_at is None


# --- where a parked confirmation was parked (ADR-0283 §5) ----------------

BINDING = ParkedBinding(execution_id="execution-1", step_id="step-1")


async def test_a_resume_finds_its_conversation_through_the_parking_episode() -> None:
    """§5: recovered through ``episode_parking``, never passed."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.seed(conversation.id, "activation:before")
    parking = await wiring.seed(conversation.id, "activation:parking", parks=BINDING)

    origin = await wiring.stage.conversation_of_binding(BINDING)

    assert origin == ParkingOrigin(conversation_id=conversation.id, episode_id=parking)


async def test_a_binding_no_live_episode_parked_finds_no_conversation() -> None:
    """§5: no live parking episode keeps ADR-0275 §6:5's degraded behaviour."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    parking = await wiring.seed(conversation.id, "activation:parking", parks=BINDING)
    assert (
        await wiring.stage.conversation_of_binding(
            ParkedBinding(execution_id="execution-1", step_id="another-step")
        )
        is None
    )
    assert await wiring.memory.delete(parking) is True

    assert await wiring.stage.conversation_of_binding(BINDING) is None


async def test_a_binding_parked_in_a_deleted_conversation_finds_none() -> None:
    """§5: recording a resumption under a stamped conversation would assert one gone."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.seed(conversation.id, "activation:parking", parks=BINDING)
    await wiring.conversations.stamp_deleted(conversation.id)

    assert await wiring.stage.conversation_of_binding(BINDING) is None


# --- deletion: the ordered steps (ADR-0283 §8:1, ADR-0293 §2:3) ---------


async def test_deletion_runs_its_steps_in_the_ratified_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8:1, as ADR-0293 §2:3 left it: the parked-reads drop, then the record's drop.

    No channel is walked and no episode deleted: deleting a conversation forgets
    nothing.
    """
    log: list[str] = []
    clock = MovableClock()

    class Memory(FakeMemoryStore):
        async def channel_episode_ids(
            self, channel: ChannelIdentity, *, after: int | None = None, limit: int
        ) -> tuple[ChannelEpisodeId, ...]:
            held = await super().channel_episode_ids(channel, after=after, limit=limit)
            log.append(f"channel_episode_ids(after={after}) -> {len(held)}")
            return held

        async def delete(self, record_id: str) -> bool:
            log.append(f"delete({record_id})")
            return await super().delete(record_id)

    class Conversations(FakeConversationStore):
        async def drop_if_eligible(self, conversation_id: str) -> bool:
            log.append("drop_if_eligible")
            return await super().drop_if_eligible(conversation_id)

    # ``FakeParkedReads`` is final, so its one call here is spied on the instance.
    parks = FakeParkedReads()
    drop = parks.drop_for_conversation

    async def spied_drop(conversation_id: str, /) -> int:
        log.append("drop_for_conversation")
        return await drop(conversation_id)

    monkeypatch.setattr(parks, "drop_for_conversation", spied_drop)
    memory = Memory(now=clock)
    wiring = Wiring(
        clock=clock,
        memory=memory,
        parked_reads=parks,
        conversations=Conversations(now=clock, retention=RETENTION, tombstone_grace=GRACE),
    )
    conversation_id, episodes = await _seed_turns(wiring, 2)
    log.clear()

    assert await wiring.stage.delete(conversation_id) is True

    assert log == ["drop_for_conversation", "drop_if_eligible"]
    assert await channel_ids(memory, conversation_id) == episodes


async def test_deleting_a_conversation_keeps_every_episode_on_its_channel() -> None:
    """ADR-0293 §2:3: the conversation goes, and none of the episodes on its place."""
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, episodes = await _seed_turns(wiring, 2)

    assert await wiring.stage.delete(conversation_id) is True

    assert await wiring.conversations.get(conversation_id) is None
    assert await channel_ids(wiring.memory, conversation_id) == episodes
    # The tombstone outlives the deleting call by its grace, as it did (§8).
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]
    clock.advance(GRACE)
    assert await wiring.stage.sweep_deletions() == 1
    assert await wiring.conversations.stamped_conversation_ids() == []
    assert await channel_ids(wiring.memory, conversation_id) == episodes


async def test_forgetting_a_conversation_forgets_every_episode_on_its_channel() -> None:
    """ADR-0293 §2:4: completed or not, expired but unpurged, or not yet valid.

    The enumeration is what the store physically holds; a read filtered by liveness
    or validity in its place would leave the last two behind (ADR-0275 §6:6).
    Another conversation's episodes are untouched, and the conversation stands.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation = await wiring.stage.begin(None)
    await wiring.seed(conversation.id, "activation:completed")
    await wiring.seed(conversation.id, "activation:failed", completed=False)
    await wiring.seed(conversation.id, "activation:expired", expires_at=AT + MINUTE)
    await wiring.seed(
        conversation.id, "activation:not-yet-valid", validity=Validity(valid_from=AT + DAY)
    )
    other_id, other_episodes = await _seed_turns(wiring, 1)
    clock.advance(HOUR)  # the expired one is now past its horizon and not yet purged
    assert len(await channel_ids(wiring.memory, conversation.id)) == 4

    assert await wiring.stage.forget(conversation.id) is True

    assert await channel_ids(wiring.memory, conversation.id) == []
    assert await channel_ids(wiring.memory, other_id) == other_episodes
    assert await wiring.conversations.get(conversation.id) is not None, "§5:6: it stands"
    assert await wiring.stage.forget(conversation.id) is False, "nothing left to forget"


async def test_forgetting_reaches_a_deleted_conversations_episodes() -> None:
    """ADR-0293 §2:5: whether or not the conversation still stands in the medium."""
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, _ = await _seed_turns(wiring, 2)
    await wiring.stage.delete(conversation_id)
    clock.advance(GRACE)
    await wiring.stage.sweep_deletions()

    assert await wiring.stage.forget(conversation_id) is True

    assert await channel_ids(wiring.memory, conversation_id) == []


async def test_forgetting_interrupted_part_way_is_completed_by_a_re_run() -> None:
    """ADR-0293 §2:4: idempotent by re-walking the channel.

    A run that dies part-way leaves the episodes it had not yet reached on the
    channel; the re-run walks from the beginning and finds only those.
    """
    clock = MovableClock()
    interrupt = 3

    class DiesMidSweep(FakeMemoryStore):
        def __init__(self) -> None:
            super().__init__(now=clock)
            self.deleted = 0
            self.arm = False

        async def delete(self, record_id: str) -> bool:
            if self.arm and self.deleted >= interrupt:
                msg = "the process died mid-sweep"
                raise MemoryStoreError(msg)
            self.deleted += 1
            return await super().delete(record_id)

    memory = DiesMidSweep()
    wiring = Wiring(clock=clock, memory=memory)
    conversation_id, episodes = await _seed_turns(wiring, 7)
    memory.arm = True

    with pytest.raises(MemoryStoreError):
        await wiring.stage.forget(conversation_id)

    assert await channel_ids(memory, conversation_id) == episodes[interrupt:]

    memory.arm = False
    assert await wiring.stage.forget(conversation_id) is True

    assert await channel_ids(memory, conversation_id) == []
    assert await wiring.conversations.get(conversation_id) is not None


async def test_the_sweep_reaches_a_tombstone_no_presenting_read_will_show() -> None:
    """§8: the coordinator still finds what it is about to destroy.

    Every surface a user reaches says the conversation is gone, while the stamped
    enumeration and the channel still hold what the sweep needs.
    """
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, 2)
    await wiring.conversations.stamp_deleted(conversation_id)

    assert await wiring.conversations.get(conversation_id) is None
    assert await wiring.stage.recent() == []
    assert await wiring.stage.digest(conversation_id) is None
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]
    assert await channel_ids(wiring.memory, conversation_id) == episodes


async def test_a_repeat_deletion_reports_it_did_not_stamp_and_still_finishes_the_sweep() -> None:
    """§8's protocol is explicitly re-runnable, so a repeat is a no-op and not an error."""
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, _ = await _seed_turns(wiring, 1)

    assert await wiring.stage.delete(conversation_id) is True  # inside the grace: no drop yet
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]
    clock.advance(GRACE)

    assert await wiring.stage.delete(conversation_id) is False, "already stamped"
    assert await wiring.conversations.stamped_conversation_ids() == []


async def test_deleting_something_that_is_already_gone_is_not_an_error() -> None:
    """ADR-0076 §2: a conversation that is gone is a deletion that completed."""
    wiring = Wiring()

    assert await wiring.stage.delete("nobody") is False


async def test_the_legacy_route_interrupted_part_way_leaves_the_conversation_standing() -> None:
    """``delete_and_forget`` forgets first, so a run that dies leaves nothing hidden.

    The route ADR-0293 §Decision:2 keeps: forgetting fails part-way, the conversation
    is not yet stamped and stays listed with what its place still holds, and the
    user's repeat finishes both halves (ADR-0074 §8's survivable crash, by a residue
    the user can still reach rather than a tombstone a sweep must find).
    """
    clock = MovableClock()
    interrupt = 2

    class DiesMidForget(FakeMemoryStore):
        def __init__(self) -> None:
            super().__init__(now=clock)
            self.deleted = 0
            self.arm = False

        async def delete(self, record_id: str) -> bool:
            if self.arm and self.deleted >= interrupt:
                msg = "the process died mid-forget"
                raise MemoryStoreError(msg)
            self.deleted += 1
            return await super().delete(record_id)

    memory = DiesMidForget()
    wiring = Wiring(clock=clock, memory=memory)
    conversation_id, episodes = await _seed_turns(wiring, 4)
    memory.arm = True

    with pytest.raises(MemoryStoreError):
        await wiring.stage.delete_and_forget(conversation_id)

    assert await wiring.conversations.get(conversation_id) is not None, "still reachable"
    assert await wiring.conversations.stamped_conversation_ids() == []
    assert await channel_ids(memory, conversation_id) == episodes[interrupt:]

    memory.arm = False
    assert await wiring.stage.delete_and_forget(conversation_id) is True
    assert await channel_ids(memory, conversation_id) == []
    assert await wiring.conversations.get(conversation_id) is None


async def test_an_episode_landing_after_the_stamp_is_kept() -> None:
    """ADR-0293 §2:7: a capture racing the deletion keeps its episode.

    The sweep drops the record once the grace has passed, destroys nothing, and is
    idempotent once the record is dropped.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, _ = await _seed_turns(wiring, 1)
    assert await wiring.stage.delete(conversation_id) is True
    await wiring.memory.add(conversation_episode(conversation_id, "activation:late"))

    assert await wiring.stage.sweep_deletions() == 0, "the grace has not elapsed"
    assert await wiring.memory.get("activation:late") is not None, "deleting forgets nothing"

    clock.advance(GRACE)
    assert await wiring.stage.sweep_deletions() == 1
    assert await wiring.stage.sweep_deletions() == 0, "a re-run is a no-op"


# --- the parked reads a deletion takes with it (ADR-0244 §3) -------------


def _park(park_id: str, conversation_id: str, decision_id: str) -> ParkedRead:
    """An ``OPEN`` park of ``conversation_id``, with its three content fields present."""
    return ParkedRead(
        id=park_id,
        conversation_id=conversation_id,
        decision_id=decision_id,
        parameters={"origin": "search.example", "query": "bell tower porto"},
        goal=GoalBrief.of(
            Goal(
                id=f"goal-{park_id}",
                interpretation=(
                    GoalInterpretation(
                        revision=1,
                        outcome="what is that bell tower in Porto",
                        outcome_ground=Ground.USER_STATED,
                        outcome_span="what is that bell tower in Porto",
                        recorded_at=AT,
                        raised_by="t-1",
                    ),
                ),
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                ),
                created_at=AT,
            )
        ),
        goal_id=f"goal-{park_id}",
        plan=ActionPlan(
            id=f"plan-{park_id}",
            goal_id=f"goal-{park_id}",
            steps=(),
            created_at=AT,
            rationale="answer from what is already here, and look the tower up",
        ),
        parked_at=AT,
        expires_at=AT + DAY,
        disposition=ParkedReadDisposition.OPEN,
    )


async def test_a_deletion_drops_this_conversations_parks_and_no_others() -> None:
    """ADR-0244 §3: the conversation's deletion sequence drops its parks.

    "Every park of that conversation, open or terminal, content and terminal facts
    alike" — a terminal one holds no content, so what a deletion removes there is six
    scalar facts, and leaving them would let a decision stay excluded from
    ``grantable_decisions`` (§5's eighth condition) for a conversation that no longer
    exists. Another conversation's park is untouched, which is the half a store-wide
    drop would break.
    """
    parks = FakeParkedReads()
    wiring = Wiring(parked_reads=parks)
    conversation_id, _ = await _seed_turns(wiring, 1)
    other_id, _ = await _seed_turns(wiring, 1)
    await parks.park(_park("park-1", conversation_id, "decision-1"))
    await parks.settle("park-1", disposition=ParkedReadDisposition.DENIED, at=AT)
    await parks.park(_park("park-2", conversation_id, "decision-2"))
    await parks.park(_park("park-3", other_id, "decision-3"))

    assert await wiring.stage.delete(conversation_id) is True

    assert await parks.get("park-1") is None, "the terminal row went too"
    assert await parks.get("park-2") is None
    assert await parks.park_of_decision("decision-2") is None
    assert (await parks.get("park-3")) is not None, "another conversation is untouched"


async def test_the_parks_of_a_conversation_another_sweep_already_dropped_still_go() -> None:
    """The placement argument: the parks are dropped whatever the record's state.

    A call arriving for a conversation another sweep already dropped still reaches
    the parks, which is the one route to them ADR-0244 §3 names besides the deadline —
    so the drop sits inside step 2, ahead of anything that depends on the record.
    """
    parks = FakeParkedReads()
    wiring = Wiring(parked_reads=parks)
    await parks.park(_park("park-1", "conversation-another-sweep-finished", "decision-1"))

    assert await wiring.stage.delete("conversation-another-sweep-finished") is False

    assert await parks.get("park-1") is None


async def test_the_start_up_sweep_drops_the_parks_a_crashed_deletion_left() -> None:
    """The drop is inside step 2, so the re-run carries it (ADR-0076, ADR-0244 §3).

    A deletion interrupted after its stamp leaves the tombstone, and the sweep re-walks
    the whole of step 2 — the parks included, because they are dropped there rather than
    after the conditional drop. Placed after step 3 instead, the drop would be
    unreachable to this sweep: ``drop_if_eligible`` removes the record and the tombstone
    with it, and nothing enumerates the conversation again.
    """
    clock = MovableClock()
    parks = FakeParkedReads()
    wiring = Wiring(clock=clock, parked_reads=parks)
    conversation_id, _ = await _seed_turns(wiring, 1)
    await parks.park(_park("park-1", conversation_id, "decision-1"))
    # The stamp with nothing after it: a process that died between §8's step 1 and its
    # step 2, which is the state ADR-0076 exists to find.
    assert await wiring.conversations.stamp_deleted(conversation_id) is True
    clock.advance(GRACE)

    assert await wiring.stage.sweep_deletions() == 1

    assert await parks.get("park-1") is None


async def test_a_park_store_fault_aborts_step_two_and_the_tombstone_stands() -> None:
    """The residue of a partial failure is one the user can still reach and destroy.

    The parks are dropped before the record, so a store that cannot be written leaves
    the tombstone standing, which is what makes the next sweep finish it; the episodes
    are not the deletion's to touch either way (ADR-0293 §2:3).
    """
    parks = FakeParkedReads()
    wiring = Wiring(parked_reads=parks)
    conversation_id, episodes = await _seed_turns(wiring, 1)
    parks.fail_writes()

    with pytest.raises(AssistantError):
        await wiring.stage.delete(conversation_id)

    assert await wiring.memory.get(episodes[0]) is not None, "nothing below the drop ran"
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]


async def test_a_stage_with_no_park_store_deletes_exactly_as_it_did_before() -> None:
    """``None`` drops nothing because there is nothing to drop (ADR-0244 §18's lane order).

    A deployment that wired no store holds no park for any conversation, so the sequence
    is what it was before this decision — and the absence is an ordinary state rather
    than a degradation.
    """
    wiring = Wiring()
    conversation_id, episodes = await _seed_turns(wiring, 1)

    assert await wiring.stage.delete(conversation_id) is True

    assert await wiring.memory.get(episodes[0]) is not None, "deleting forgets nothing"
    assert await wiring.conversations.get(conversation_id) is None


# --- the start-up sweep (ADR-0076) ---------------------------------------


async def test_the_deletion_sweep_finishes_what_a_previous_run_left() -> None:
    """ADR-0076: before this read existed, nothing could *find* a crashed deletion.

    The stamp hides a conversation from every presenting read, so a process that
    died between the stamp and the drop left a record that outlived its grace
    indefinitely. It destroys no episode (ADR-0293 §2:3).
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    first, first_episodes = await _seed_turns(wiring, 2)
    second, second_episodes = await _seed_turns(wiring, 1)
    live, live_episodes = await _seed_turns(wiring, 1)
    await wiring.conversations.stamp_deleted(first)
    await wiring.conversations.stamp_deleted(second)
    clock.advance(GRACE)

    assert await wiring.stage.sweep_deletions() == 2

    for episode_id in [*first_episodes, *second_episodes, *live_episodes]:
        assert await wiring.memory.get(episode_id) is not None
    assert await wiring.conversations.stamped_conversation_ids() == []
    assert await wiring.conversations.get(live) is not None


async def test_the_deletion_sweep_drains_every_batch_of_tombstones() -> None:
    """ADR-0076 §4.5: finishing one batch and stopping is the failure to forbid."""

    class SmallBatches(FakeConversationStore):
        async def stamped_conversation_ids(
            self, *, limit: int | None = None, after_id: str | None = None
        ) -> list[str]:
            return await super().stamped_conversation_ids(limit=2, after_id=after_id)

    clock = MovableClock()
    wiring = Wiring(
        clock=clock,
        conversations=SmallBatches(now=clock, retention=RETENTION, tombstone_grace=GRACE),
    )
    ids = []
    for _ in range(7):
        conversation_id, _episodes = await _seed_turns(wiring, 1)
        ids.append(conversation_id)
    for conversation_id in ids:
        await wiring.conversations.stamp_deleted(conversation_id)
    clock.advance(GRACE)

    assert await wiring.stage.sweep_deletions() == 7

    assert await wiring.conversations.stamped_conversation_ids() == []
    assert len(await wiring.memory.export()) == 7, "deleting forgets nothing"


async def test_a_sweep_continues_past_a_conversation_someone_else_finished() -> None:
    """ADR-0076 §3's companion: the unknown-id no-op, and the ids *after* it.

    Two sweepers over one pair of stores: the first enumerates a batch, the second
    completes and drops one of the ids in it, and the first then reaches that id.
    Without treating it as a no-op the start-up sweep is abandoned by the very
    concurrency ``drop_if_eligible``'s re-check was supposed to make safe — and the
    ids after it in the batch are the ones that stay unreclaimed.
    """
    clock = MovableClock()
    reached: list[str] = []

    class FinishedByAnother(FakeConversationStore):
        """Behaves as if a second sweeper dropped ``vanish`` mid-walk."""

        vanish: str | None = None

        async def drop_if_eligible(self, conversation_id: str) -> bool:
            reached.append(conversation_id)
            if conversation_id == self.vanish:
                msg = "no such conversation"
                raise UnknownConversationError(msg)
            return await super().drop_if_eligible(conversation_id)

    conversations = FinishedByAnother(now=clock, retention=RETENTION, tombstone_grace=GRACE)
    wiring = Wiring(clock=clock, conversations=conversations)
    started = []
    for _ in range(3):
        conversation_id, _episodes = await _seed_turns(wiring, 1)
        started.append(conversation_id)
    ids = sorted(started)
    for conversation_id in ids:
        await conversations.stamp_deleted(conversation_id)
    conversations.vanish = ids[0]  # the *first* the walk will reach, id ascending
    clock.advance(GRACE)

    dropped = await wiring.stage.sweep_deletions()

    assert reached == ids, "the sweep carried on to every remaining id"
    assert dropped == 2, "the vanished one was a no-op, the other two were finished"
    assert await conversations.stamped_conversation_ids() == [ids[0]]


async def test_a_genuine_store_fault_aborts_the_sweep_and_is_reported() -> None:
    """ADR-0076 §2's other half: a subclass raised for everything buys less than nothing.

    A sweep that swallowed real store faults to keep running would report success
    over work it never did, so anything that is not "this one is already gone"
    propagates.
    """
    clock = MovableClock()

    class Broken(FakeConversationStore):
        async def drop_if_eligible(self, conversation_id: str) -> bool:
            msg = "the index is unreadable"
            raise ConversationStoreError(msg)

    conversations = Broken(now=clock, retention=RETENTION, tombstone_grace=GRACE)
    wiring = Wiring(clock=clock, conversations=conversations)
    conversation_id, _ = await _seed_turns(wiring, 1)
    await conversations.stamp_deleted(conversation_id)
    clock.advance(GRACE)

    with pytest.raises(ConversationStoreError) as raised:
        await wiring.stage.sweep_deletions()

    assert "unreadable" in str(raised.value)
    assert not isinstance(raised.value, UnknownConversationError), (
        "a store fault is not 'this one is already gone', and a sweep that read it "
        "as one would abandon every id after it, quietly"
    )
    assert await conversations.stamped_conversation_ids() == [conversation_id], (
        "the tombstone stands, so the next run can finish what this one could not"
    )


@pytest.mark.integration
async def test_a_crashed_deletion_is_finished_after_the_index_is_reopened(tmp_path: Path) -> None:
    """ADR-0076 §3, in the case #447 was found in: "at engine start", across a reopen.

    Persist an interrupted §8 sequence — a stamped conversation whose episodes are
    still on its channel — then open a **fresh** store over the same file and run the
    stage's start-up sweep. Every conformance clause can pass against a method
    nothing calls; this is the one that proves the tombstone survives the process
    boundary it exists for.
    """
    clock = MovableClock()
    path = tmp_path / "conversations.db"
    memory = FakeMemoryStore(now=clock)

    first = SqliteConversationStore(path=path, now=clock, tombstone_grace=GRACE)
    try:
        stage = ConversationLifecycle(
            conversations=first,
            memory=memory,
            retention=RETENTION,
            now=clock,
        )
        conversation = await stage.begin(None)
        await memory.add(conversation_episode(conversation.id, "activation:before-the-crash"))
        assert await first.stamp_deleted(conversation.id) is True
        # ...and here the process dies: no episode deleted, no record dropped.
    finally:
        first.close()

    assert await memory.get("activation:before-the-crash") is not None, "it outlived the crash"
    clock.advance(GRACE)

    reopened = SqliteConversationStore(path=path, now=clock, tombstone_grace=GRACE)
    try:
        restarted = ConversationLifecycle(
            conversations=reopened,
            memory=memory,
            retention=RETENTION,
            now=clock,
        )

        assert await restarted.sweep_deletions() == 1

        assert await memory.get("activation:before-the-crash") is not None, (
            "deleting forgets nothing (ADR-0293 §2:3)"
        )
        assert await reopened.stamped_conversation_ids() == []
        assert await reopened.get(conversation.id) is None
    finally:
        reopened.close()


# --- retention reclaim: observes, never destroys (ADR-0283 §8:2) ---------


async def test_reclaim_drops_an_emptied_idle_conversation_without_destroying_anything() -> None:
    """§8:2: the record goes because its channel is empty and it is idle.

    The episodes left on their own — expired, then purged by the memory store's own
    sweep — and reclaim destroyed none of them.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation_id, episodes = await _seed_turns(wiring, 2)

    clock.advance(7 * DAY + MINUTE)  # past both the episodes' expiry and the horizon
    assert await wiring.memory.get(episodes[0]) is None, "the episodes expired on their own"
    assert await wiring.memory.purge_expired() == 2

    assert await wiring.stage.reclaim() == 1
    assert await wiring.conversations.get(conversation_id) is None


@pytest.mark.parametrize("held", ["live", "expired-unpurged", "not-yet-valid"])
async def test_reclaim_keeps_a_conversation_whose_channel_holds_an_episode(held: str) -> None:
    """§8:2: "holds" is ``channel_episode_ids``' sense, and reclaim destroys nothing.

    A live episode, one expired but not yet purged, and one not yet valid each delay
    the reclaim — and the load-bearing half is that none of them is destroyed for the
    crime of belonging to an old conversation.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation = await wiring.stage.begin(None)
    if held == "live":
        episode = await wiring.seed(conversation.id, "activation:held", unexpiring=True)
    elif held == "expired-unpurged":
        episode = await wiring.seed(conversation.id, "activation:held")
    else:
        episode = await wiring.seed(
            conversation.id,
            "activation:held",
            unexpiring=True,
            validity=Validity(valid_from=AT + 365 * DAY),
        )

    clock.advance(30 * DAY)

    assert await wiring.stage.reclaim() == 0
    assert await wiring.conversations.get(conversation.id) is not None
    assert await channel_ids(wiring.memory, conversation.id) == [episode], (
        "reclaim destroys nothing"
    )


class RetunableStore(FakeConversationStore):
    """A store whose retention horizon a case can move, as a setting change would.

    The horizon is a ``Settings`` value read at reclaim time rather than a deadline
    stamped on the record (ADR-0074 §7), so the only way to exercise that is to
    change it between the conversation's creation and the reclaim — which is what an
    operator editing the setting does.
    """

    def retune(self, retention: timedelta | None) -> None:
        """Move the horizon, as a changed setting does."""
        self._retention = retention


@pytest.mark.parametrize(
    ("started_under", "reclaimed_under", "expected"),
    [(7 * DAY, 30 * DAY, 0), (30 * DAY, 7 * DAY, 1)],
    ids=["lengthened", "shortened"],
)
async def test_reclaim_judges_against_the_horizon_in_force_when_it_runs(
    started_under: timedelta, reclaimed_under: timedelta, expected: int
) -> None:
    """§7: the conversation record follows the setting, not a deadline of its own.

    A store moved from a 7-day horizon to a 30-day one keeps an emptied
    conversation's index until day 30 though its episodes left on day 7; moved the
    other way, it drops it sooner. **Both directions belong here**, because an
    implementation that stamped a per-conversation deadline at creation would pass a
    fixed-setting suite and diverge exactly at this pair.
    """
    clock = MovableClock()
    conversations = RetunableStore(now=clock, retention=started_under, tombstone_grace=GRACE)
    memory = FakeMemoryStore(now=clock)
    started = ConversationLifecycle(
        conversations=conversations,
        memory=memory,
        retention=started_under,
        now=clock,
    )
    conversation = await started.begin(None)  # emptied by construction: no turn ever landed

    clock.advance(10 * DAY)
    conversations.retune(reclaimed_under)
    reclaiming = ConversationLifecycle(
        conversations=conversations,
        memory=memory,
        retention=reclaimed_under,
        now=clock,
    )

    assert await reclaiming.reclaim() == expected
    assert (await conversations.get(conversation.id) is None) is bool(expected)


async def test_reclaim_is_switched_off_when_retention_is_unset() -> None:
    """§7: "keep the episodes forever" is not a setting under which records vanish.

    The pair with the stamping case is what stops an implementation reading ``None``
    as "no horizon, so everything is past it".
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=None)
    conversation = await wiring.stage.begin(None)

    clock.advance(1000 * DAY)

    assert await wiring.stage.reclaim() == 0
    assert await wiring.conversations.get(conversation.id) is not None
