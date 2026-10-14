"""The conversation lifecycle: every sequence that spans the conversation and memory stores.

ADR-0074 §9 assigns this list here rather than to the shared conformance suite,
and says why: "a conformance suite exercises one store against one contract; §8's
ordering and its serialisation span two stores and the coordinator between them".
Since ADR-0283 a conversation's membership and deletion have one source —
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
    ConversationStoreError,
    MemoryStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import Validity
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import (
        ChannelEpisodeId,
        ChannelIdentity,
    )

AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

RETENTION = 30 * DAY
GRACE = HOUR


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

    def __init__(
        self,
        *,
        clock: MovableClock | None = None,
        retention: timedelta | None = RETENTION,
        grace: timedelta = GRACE,
        memory: FakeMemoryStore | None = None,
        conversations: FakeConversationStore | None = None,
    ) -> None:
        self.clock = clock if clock is not None else MovableClock()
        self.retention = retention
        self.memory = memory if memory is not None else FakeMemoryStore(now=self.clock)
        self.conversations = (
            conversations
            if conversations is not None
            else FakeConversationStore(now=self.clock, retention=retention, tombstone_grace=grace)
        )
        self.stage = ConversationLifecycle(
            conversations=self.conversations,
            memory=self.memory,
            retention=retention,
            now=self.clock,
        )

    async def seed(  # noqa: PLR0913 — one keyword per axis a seeded episode varies
        self,
        conversation_id: str,
        episode_id: str,
        *,
        completed: bool = True,
        occurred_at: datetime | None = None,
        expires_at: datetime | None = None,
        validity: Validity | None = None,
        unexpiring: bool = False,
    ) -> str:
        """Put one episode on ``conversation_id``'s channel, as the writer leaves it.

        The episode first, then ``record_turn`` — ADR-0283 §7's order — so the
        conversation's ``last_turn_at`` is what a written turn leaves. The expiry is
        the writer's (``occurred_at`` plus the retention) unless a case names one or
        asks for none.
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
                expires_at=expires_at,
                validity=validity or Validity(),
            )
        )
        await self.conversations.record_turn(conversation_id, episode_id=episode_id, occurred_at=at)
        return episode_id


async def _seed_turns(wiring: Wiring, count: int) -> tuple[str, list[str]]:
    """Start a conversation and put ``count`` completed episodes on its channel."""
    conversation = await wiring.stage.begin(None)
    episodes = [
        await wiring.seed(conversation.id, f"activation:{conversation.id}-{index}")
        for index in range(count)
    ]
    return conversation.id, episodes


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


# --- deletion: the ordered steps (ADR-0283 §8:1, ADR-0293 §2:3) ---------


async def test_deletion_runs_its_steps_in_the_ratified_order() -> None:
    """§8:1, as ADR-0293 §2:3 left it: the stamp, then the record's drop.

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
        async def stamp_deleted(self, conversation_id: str) -> bool:
            log.append("stamp_deleted")
            return await super().stamp_deleted(conversation_id)

        async def drop_if_eligible(self, conversation_id: str) -> bool:
            log.append("drop_if_eligible")
            return await super().drop_if_eligible(conversation_id)

    memory = Memory(now=clock)
    wiring = Wiring(
        clock=clock,
        memory=memory,
        conversations=Conversations(now=clock, retention=RETENTION, tombstone_grace=GRACE),
    )
    conversation_id, episodes = await _seed_turns(wiring, 2)
    log.clear()

    assert await wiring.stage.delete(conversation_id) is True

    assert log == ["stamp_deleted", "drop_if_eligible"]
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
