"""The capture/lifecycle stage: every sequence that spans both durable stores.

ADR-0074 §9 assigns this list here rather than to the shared conformance suite,
and says why: "a conformance suite exercises one store against one contract; §3's
insert, §8's ordering, its compensation and its serialisation span two stores and
the coordinator between them". Every case below is one where the guarantee is
either kept or silently lost, and **none of them is reachable from a suite that
only writes successfully**.

Both stores are canonical fakes from ``ai_assistant.testing``, so nothing here
imports a subsystem concrete (CLAUDE.md golden rule 1) — except the two cases that
have to survive a *reopen*, which is the whole point of a tombstone and needs a
persistent index.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    Provenance,
    Validity,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.orchestration.conversations import (
    CAPTURE_CONFIDENCE,
    ConversationLifecycle,
)
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from ai_assistant.core.types import MemoryRecord, MemoryWrite

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
    """A stage and the two stores behind it, all sharing one clock."""

    def __init__(  # noqa: PLR0913 — one knob per store seam a case may need to vary
        self,
        *,
        clock: MovableClock | None = None,
        retention: timedelta | None = RETENTION,
        grace: timedelta = GRACE,
        purge_batch: int = 100,
        memory: FakeMemoryStore | None = None,
        conversations: FakeConversationStore | None = None,
    ) -> None:
        self.clock = clock if clock is not None else MovableClock()
        self.memory = memory if memory is not None else FakeMemoryStore(now=self.clock)
        self.conversations = (
            conversations
            if conversations is not None
            else FakeConversationStore(
                now=self.clock,
                retention=retention,
                tombstone_grace=grace,
                purge_batch=purge_batch,
            )
        )
        self.stage = ConversationLifecycle(
            conversations=self.conversations,
            memory=self.memory,
            retention=retention,
            now=self.clock,
        )


async def _capture_turns(wiring: Wiring, count: int) -> tuple[str, list[str]]:
    """Start a conversation and capture ``count`` turns into it."""
    conversation = await wiring.stage.begin(None)
    episodes: list[str] = []
    for index in range(count):
        report = await wiring.stage.capture(conversation.id, content=f"turn {index}")
        assert report.episode_id is not None, "the fixture must actually record its turns"
        episodes.append(report.episode_id)
    return conversation.id, episodes


def _foreign_episode(episode_id: str) -> EpisodicMemory:
    """A record some other producer put in the reserved namespace (ADR-0074 §3)."""
    return EpisodicMemory(
        id=episode_id,
        content="a record capture did not write",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.EXTERNAL, confidence=0.5, last_updated=AT),
    )


# --- what capture writes, and what it stamps (§3, §4) --------------------


async def test_capture_writes_one_episode_carrying_exactly_what_section_4_ratifies() -> None:
    """§4: OBSERVED, a sub-1.0 constant, and *nothing judged*.

    Every omission here is ruled rather than incidental. ``importance`` is a
    judgement and salience is leg 7's; ``participants`` filled with constants would
    occupy, with noise, the field an observer means for the people an episode is
    *about*; ``validity`` stays open because supersession is a law about beliefs
    that contradict each other and two things that both happened never do; and
    ``evidence`` stays empty because an episode is the terminal citation — the thing
    other records cite — so requiring one would demand a regress.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    report = await wiring.stage.capture(
        conversation.id, content="The user asked: hello", outcome="no action was needed"
    )

    assert report.degraded is False
    assert report.episode_id is not None
    stored = await wiring.memory.get(report.episode_id)
    assert isinstance(stored, EpisodicMemory)
    assert stored.kind == MemoryKind.EPISODIC.value
    assert stored.content == "The user asked: hello"
    assert stored.outcome == "no action was needed"
    assert stored.occurred_at == AT
    assert stored.provenance.source is MemorySource.OBSERVED
    assert stored.provenance.confidence == CAPTURE_CONFIDENCE
    assert stored.provenance.confidence < 1.0, (
        "1.0 is the standing only the user's own word carries (ADR-0072 §3); an "
        "episode rendered beside an assertion at equal confidence teaches the false "
        "model ADR-0072 §6 exists to prevent"
    )
    assert stored.provenance.evidence == ()
    assert stored.importance == 0.0
    assert stored.participants == ()
    assert stored.validity == Validity()


async def test_an_unset_retention_stamps_a_finite_expiry() -> None:
    """§7: the horizon in force at capture becomes the episode's own deadline."""
    wiring = Wiring(retention=7 * DAY)
    conversation = await wiring.stage.begin(None)

    report = await wiring.stage.capture(conversation.id, content="x")

    assert report.episode_id is not None
    stored = await wiring.memory.get(report.episode_id)
    assert stored is not None
    assert stored.expires_at == AT + 7 * DAY


async def test_retention_set_to_none_stamps_no_expiry_at_all() -> None:
    """§7's ratified pair: "keep forever" is the user's deliberate choice.

    The half that catches an implementation which inherited a nullable duration's
    ``None`` default: without this case, one that read ``None`` as "expire
    immediately" or "expire at the default" would pass every other clause.
    """
    wiring = Wiring(retention=None)
    conversation = await wiring.stage.begin(None)

    report = await wiring.stage.capture(conversation.id, content="x")

    assert report.episode_id is not None
    stored = await wiring.memory.get(report.episode_id)
    assert stored is not None
    assert stored.expires_at is None


async def test_two_captures_derive_distinct_episode_ids() -> None:
    """§3: the id is a function of the conversation and an ordinal the store allocates.

    The clause that catches an implementation deriving the id from anything it does
    not allocate under the same exclusion — which would let two turns collide by
    construction rather than not collide by construction.
    """
    wiring = Wiring()
    _, episodes = await _capture_turns(wiring, 2)

    assert len(set(episodes)) == 2
    for episode_id in episodes:
        assert await wiring.memory.get(episode_id) is not None


async def test_an_episode_id_that_is_already_stored_fails_the_capture_loudly() -> None:
    """§3: with a derived id a conflict is a broken invariant, not a race.

    So it fails the capture and **overwrites nothing** — no retry, because a retry
    answers neither a broken ordinal invariant nor a foreign producer that took an
    id in the reserved namespace. The occupant here is deliberately foreign, which
    is the case the reservation rule forbids and this guard exists to catch.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    # Predict the id the first turn will derive, and squat on it.
    squatted = f"conv:{conversation.id}:1"
    await wiring.memory.add(_foreign_episode(squatted))

    report = await wiring.stage.capture(conversation.id, content="mine")

    assert report.degraded is True
    assert report.episode_id is None
    occupant = await wiring.memory.get(squatted)
    assert occupant is not None
    assert occupant.content == "a record capture did not write", "nothing was overwritten"
    assert occupant.provenance.source is MemorySource.EXTERNAL


async def test_an_append_refused_because_the_conversation_is_gone_writes_no_episode() -> None:
    """§8: a refused append needs no compensation, because nothing was written.

    The assertion worth making is the **negative** one — no record reached the
    memory store — which is what the intent-first ordering buys. Under the reverse
    order the same refusal would strand an episode already written.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.conversations.stamp_deleted(conversation.id)

    report = await wiring.stage.capture(conversation.id, content="too late")

    assert report.degraded is True
    assert report.episode_id is None
    assert await wiring.memory.export() == [], "nothing reached the memory store"


async def test_a_memory_store_fault_leaves_the_turn_recorded_with_no_episode() -> None:
    """§3: the honest form of "every turn is captured" — durable index, best-effort episode.

    Not a conflict: an embedder or database fault *after* a successful append. The
    turn keeps its index entry, no episode exists, the already-produced answer is
    still returned, and the degradation is reported. An implementation that
    propagated the error — turning a delivered answer into a failed turn — or that
    rolled the index entry back would pass every other failure case on this list.
    """

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the embedder is down"
            raise MemoryStoreError(msg)

    wiring = Wiring(memory=Faulting())
    conversation = await wiring.stage.begin(None)

    report = await wiring.stage.capture(conversation.id, content="answered anyway")

    assert report.degraded is True
    assert report.episode_id is None
    # The index entry stands: the turn happened, and the transcript shows a gap.
    assert [turn.ordinal for turn in await wiring.conversations.turns(conversation.id)] == [1]
    replayed = await wiring.stage.history(conversation.id)
    assert replayed.records == (), "an unresolvable episode id is a gap, not an error"


async def test_a_deletion_landing_mid_write_is_compensated() -> None:
    """§8: the *only* trigger compensation has, and the one elapsed time cannot decide.

    The append succeeded before the stamp; the episode write commits after it. So
    capture re-reads the conversation afterwards and destroys the episode it just
    wrote. Because the id is determined by its own conversation and ordinal, that
    delete can never destroy a record capture did not write.
    """
    stamped: list[str] = []

    class StampsMidWrite(FakeMemoryStore):
        """Commits the episode, then lets the deletion land before verification."""

        def __init__(self) -> None:
            super().__init__(now=clock)
            self.conversations: FakeConversationStore | None = None
            self.target: str | None = None

        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            written = await super().write_atomic(writes)
            assert self.conversations is not None
            assert self.target is not None
            await self.conversations.stamp_deleted(self.target)
            stamped.append(self.target)
            return written

    clock = MovableClock()
    memory = StampsMidWrite()
    wiring = Wiring(clock=clock, memory=memory)
    conversation = await wiring.stage.begin(None)
    memory.conversations = wiring.conversations
    memory.target = conversation.id

    report = await wiring.stage.capture(conversation.id, content="racing the deletion")

    assert stamped == [conversation.id], "the fixture must really have deleted mid-write"
    assert report.degraded is True
    assert report.episode_id is None
    assert await memory.export() == [], "the episode it wrote was destroyed"


async def test_a_failing_compensating_delete_is_reported_rather_than_raised() -> None:
    """§9.6: the turn still returns its answer, and the failure is not swallowed.

    The same race as above — the deletion lands after the episode write commits —
    but the compensating delete itself fails. What is left is an orphan the
    tombstone's own sweep will find while the grace holds, so the honest answer is
    to degrade and log rather than to raise: the answer is already delivered.
    """
    clock = MovableClock()

    class StampsThenRefusesToDelete(FakeMemoryStore):
        def __init__(self) -> None:
            super().__init__(now=clock)
            self.conversations: FakeConversationStore | None = None
            self.target: str | None = None
            self.refused = 0

        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            written = await super().write_atomic(writes)
            assert self.conversations is not None
            assert self.target is not None
            await self.conversations.stamp_deleted(self.target)
            return written

        async def delete(self, record_id: str) -> bool:
            self.refused += 1
            msg = "the store would not delete"
            raise MemoryStoreError(msg)

    memory = StampsThenRefusesToDelete()
    wiring = Wiring(clock=clock, memory=memory)
    conversation = await wiring.stage.begin(None)
    memory.conversations = wiring.conversations
    memory.target = conversation.id

    report = await wiring.stage.capture(conversation.id, content="racing the deletion")

    assert memory.refused == 1, "the compensation was attempted"
    assert report.degraded is True
    assert report.episode_id is None
    # The orphan is real and reachable: the tombstone still names it, so the sweep
    # destroys it for as long as the grace holds.
    assert await wiring.conversations.episodes_to_purge(conversation.id) != []


async def test_an_interruption_between_the_two_writes_leaves_the_ratified_residue() -> None:
    """§8, both orders: what a crash between the index entry and the episode leaves.

    Interrupted **after** the append: an index entry with no episode, which every
    reader renders as a gap — the same thing a deleted turn looks like, and a great
    deal better than the reverse, which is content no conversation admits to.
    Interrupted **after** a deletion's stamp: a tombstone that still names every
    episode, so a re-run finishes it.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    # Order one: the append lands, then the process dies.
    turn = await wiring.conversations.append(conversation.id, occurred_at=wiring.clock())
    assert await wiring.memory.get(turn.episode_id) is None
    assert (await wiring.stage.history(conversation.id)).records == ()
    assert await wiring.conversations.episodes_to_purge(conversation.id) == [turn.episode_id], (
        "the index still names the episode whose write never landed, which is what "
        "lets a deletion sweep reach a late write"
    )

    # Order two: a deletion stamps, then the process dies before the purge.
    await wiring.conversations.stamp_deleted(conversation.id)
    assert await wiring.conversations.stamped_conversation_ids() == [conversation.id]
    assert await wiring.conversations.episodes_to_purge(conversation.id) == [turn.episode_id]


# --- continuity: reading the tail back (§5) ------------------------------


async def test_history_returns_the_recent_turns_oldest_first() -> None:
    """§5: the conversation's recent turns, in order, as records the planner renders."""
    wiring = Wiring()
    conversation_id, episodes = await _capture_turns(wiring, 3)

    history = await wiring.stage.history(conversation_id)

    assert [record.id for record in history.records] == episodes
    assert history.degraded is False


async def test_history_skips_a_turn_whose_episode_no_longer_resolves() -> None:
    """§5: a gap, never an error — and the deleted turn is never resurrected."""
    wiring = Wiring()
    conversation_id, episodes = await _capture_turns(wiring, 3)
    assert await wiring.memory.delete(episodes[1]) is True

    history = await wiring.stage.history(conversation_id)

    assert [record.id for record in history.records] == [episodes[0], episodes[2]]
    assert history.degraded is False, "a gap is an ordinary state, not a degradation"


async def test_history_degrades_rather_than_failing_the_turn() -> None:
    """Losing continuity costs the answer its history, not its usefulness."""

    class Faulting(FakeMemoryStore):
        async def get(self, record_id: str) -> MemoryRecord | None:
            msg = "the store would not read"
            raise MemoryStoreError(msg)

    wiring = Wiring()
    conversation_id, _ = await _capture_turns(wiring, 1)
    broken = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=Faulting(now=wiring.clock),
        retention=RETENTION,
        now=wiring.clock,
    )

    history = await broken.history(conversation_id)

    assert history.records == ()
    assert history.degraded is True


# --- deletion: the three ordered steps (§8) ------------------------------


async def test_deleting_a_conversation_destroys_every_episode_across_every_batch() -> None:
    """§9: a fixture with one batch of turns passes a single-batch implementation.

    So this spans several, and asserts the record is dropped only once the drain
    returns empty — destroying one batch and dropping the record is the failure
    that clause exists to forbid.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, purge_batch=2)
    conversation_id, episodes = await _capture_turns(wiring, 7)

    assert await wiring.stage.delete(conversation_id) is True

    for episode_id in episodes:
        assert await wiring.memory.get(episode_id) is None
    assert await wiring.memory.export() == [], "every batch, not just the first"
    assert await wiring.conversations.get(conversation_id) is None
    # The tombstone deliberately outlives the deleting call: the grace is what keeps
    # the only record naming a pending intent alive past the deletion, so a capture
    # that commits and then dies is still swept (§8). It is not a bound and is not
    # offered as one.
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]

    clock.advance(GRACE)
    assert await wiring.stage.sweep_deletions() == 1
    assert await wiring.conversations.stamped_conversation_ids() == []


async def test_a_deletion_interrupted_between_two_batches_is_completed_by_a_re_run() -> None:
    """§9: the sweep is idempotent by re-walking, and the index still named everything.

    Nothing removes an index row until the record is dropped, so a run that dies
    part-way is re-run from the beginning and every delete it repeats is a no-op on
    an id already gone. The assertion that matters is the second one: when the
    re-run resumed, the index still named **every** episode, including the ones the
    first pass had already destroyed.
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
    wiring = Wiring(clock=clock, memory=memory, purge_batch=2)
    conversation_id, episodes = await _capture_turns(wiring, 7)
    clock.advance(GRACE)
    memory.arm = True

    with pytest.raises(MemoryStoreError):
        await wiring.stage.delete(conversation_id)

    # The tombstone survived, and still names every episode — the ones already
    # destroyed included, since rows go only when the record is dropped.
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]
    assert await wiring.conversations.episodes_to_purge(conversation_id, limit=100) == episodes

    memory.arm = False
    clock.advance(GRACE)  # the stamp landed after the first advance, so time it out
    assert await wiring.stage.sweep_deletions() == 1

    assert await wiring.memory.export() == []
    assert await wiring.conversations.stamped_conversation_ids() == []


async def test_the_sweeps_read_a_tombstone_no_presenting_read_will_show() -> None:
    """§9: the pair that keeps a tombstone from being a readable record.

    Asserted through the stage, because this is the property the *sweep* depends
    on: the coordinator must be handed the ids it is about to destroy while every
    surface a user reaches still says the conversation is gone.
    """
    wiring = Wiring()
    conversation_id, episodes = await _capture_turns(wiring, 2)
    await wiring.conversations.stamp_deleted(conversation_id)

    assert await wiring.conversations.get(conversation_id) is None
    assert await wiring.stage.recent() == []
    assert await wiring.stage.digest(conversation_id) is None
    with pytest.raises(UnknownConversationError):
        await wiring.conversations.turns(conversation_id)
    assert await wiring.conversations.episodes_to_purge(conversation_id) == episodes


async def test_a_repeat_deletion_reports_it_did_not_stamp_and_still_finishes_the_sweep() -> None:
    """§8's protocol is explicitly re-runnable, so a repeat is a no-op and not an error."""
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, _ = await _capture_turns(wiring, 1)

    assert await wiring.stage.delete(conversation_id) is True  # inside the grace: no drop yet
    assert await wiring.conversations.stamped_conversation_ids() == [conversation_id]
    clock.advance(GRACE)

    assert await wiring.stage.delete(conversation_id) is False, "already stamped"
    assert await wiring.conversations.stamped_conversation_ids() == []


async def test_deleting_something_that_is_already_gone_is_not_an_error() -> None:
    """ADR-0076 §2: a conversation that is gone is a deletion that completed."""
    wiring = Wiring()

    assert await wiring.stage.delete("nobody") is False


# --- the start-up sweep (ADR-0076) ---------------------------------------


async def test_the_deletion_sweep_finishes_what_a_previous_run_left() -> None:
    """ADR-0076: before this read existed, nothing could *find* a crashed deletion.

    The stamp hides a conversation from every presenting read, so a process that
    died between the stamp and the drop left episodes that were never destroyed and
    an index that outlived its grace indefinitely.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    first, first_episodes = await _capture_turns(wiring, 2)
    second, second_episodes = await _capture_turns(wiring, 1)
    live, live_episodes = await _capture_turns(wiring, 1)
    await wiring.conversations.stamp_deleted(first)
    await wiring.conversations.stamp_deleted(second)
    clock.advance(GRACE)

    assert await wiring.stage.sweep_deletions() == 2

    for episode_id in [*first_episodes, *second_episodes]:
        assert await wiring.memory.get(episode_id) is None
    assert await wiring.memory.get(live_episodes[0]) is not None, "an unstamped one is untouched"
    assert await wiring.conversations.get(live) is not None


async def test_the_deletion_sweep_drains_every_batch_of_tombstones() -> None:
    """ADR-0076 §4.5: finishing one batch and stopping is the failure to forbid."""
    clock = MovableClock()
    wiring = Wiring(clock=clock, purge_batch=2)
    ids = []
    for _ in range(7):
        conversation_id, _episodes = await _capture_turns(wiring, 1)
        ids.append(conversation_id)
    for conversation_id in ids:
        await wiring.conversations.stamp_deleted(conversation_id)
    clock.advance(GRACE)

    assert await wiring.stage.sweep_deletions() == 7

    assert await wiring.conversations.stamped_conversation_ids() == []
    assert await wiring.memory.export() == []


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

        async def episodes_to_purge(
            self, conversation_id: str, *, limit: int | None = None, after_id: str | None = None
        ) -> list[str]:
            reached.append(conversation_id)
            if conversation_id == self.vanish:
                msg = "no such conversation"
                raise UnknownConversationError(msg)
            return await super().episodes_to_purge(conversation_id, limit=limit, after_id=after_id)

    conversations = FinishedByAnother(now=clock, retention=RETENTION, tombstone_grace=GRACE)
    wiring = Wiring(clock=clock, conversations=conversations)
    started = []
    for _ in range(3):
        conversation_id, _episodes = await _capture_turns(wiring, 1)
        started.append(conversation_id)
    ids = sorted(started)
    for conversation_id in ids:
        await conversations.stamp_deleted(conversation_id)
    conversations.vanish = ids[0]  # the *first* the walk will reach, id ascending
    clock.advance(GRACE)

    dropped = await wiring.stage.sweep_deletions()

    # The drain calls `episodes_to_purge` more than once per conversation, so compare
    # the *order they were first reached in* rather than the raw call log.
    visited = list(dict.fromkeys(reached))
    assert visited == ids, "the sweep carried on to every remaining id"
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
        async def episodes_to_purge(
            self, conversation_id: str, *, limit: int | None = None, after_id: str | None = None
        ) -> list[str]:
            msg = "the index is unreadable"
            raise ConversationStoreError(msg)

    conversations = Broken(now=clock, retention=RETENTION, tombstone_grace=GRACE)
    wiring = Wiring(clock=clock, conversations=conversations)
    conversation_id, _ = await _capture_turns(wiring, 1)
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
    still in the ``MemoryStore`` — then open a **fresh** store over the same file and
    run the stage's start-up sweep. Every conformance clause can pass against a
    method nothing calls; this is the one that proves the tombstone survives the
    process boundary it exists for.
    """
    clock = MovableClock()
    path = tmp_path / "conversations.db"
    memory = FakeMemoryStore(now=clock)

    first = SqliteConversationStore(path=path, now=clock, tombstone_grace=GRACE)
    try:
        stage = ConversationLifecycle(
            conversations=first, memory=memory, retention=RETENTION, now=clock
        )
        conversation = await stage.begin(None)
        report = await stage.capture(conversation.id, content="recorded before the crash")
        assert report.episode_id is not None
        assert await first.stamp_deleted(conversation.id) is True
        # ...and here the process dies: no episode purged, no record dropped.
    finally:
        first.close()

    assert await memory.get(report.episode_id) is not None, "the episode outlived the crash"
    clock.advance(GRACE)

    reopened = SqliteConversationStore(path=path, now=clock, tombstone_grace=GRACE)
    try:
        restarted = ConversationLifecycle(
            conversations=reopened, memory=memory, retention=RETENTION, now=clock
        )

        assert await restarted.sweep_deletions() == 1

        assert await memory.get(report.episode_id) is None, "the leaked episode was destroyed"
        assert await reopened.stamped_conversation_ids() == []
        assert await reopened.get(conversation.id) is None
    finally:
        reopened.close()


# --- retention reclaim: observes, never destroys (§7) --------------------


async def test_reclaim_drops_an_emptied_idle_conversation_without_destroying_anything() -> None:
    """§7: the record goes because it is empty and idle; the episodes left on their own."""
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation_id, episodes = await _capture_turns(wiring, 2)

    clock.advance(7 * DAY + MINUTE)  # past both the episodes' expiry and the horizon
    assert await wiring.memory.get(episodes[0]) is None, "the episodes expired on their own"

    assert await wiring.stage.reclaim() == 1
    assert await wiring.conversations.get(conversation_id) is None


async def test_reclaim_never_destroys_a_live_episode() -> None:
    """§7, §9: the sweep that asks for nothing must not carry anything out.

    A conversation past its horizon whose episode is still live: reclaim's
    precondition is that **no** turn resolves, so nothing is dropped and — the
    load-bearing half — nothing is destroyed either. Stated as one sequence with the
    deletion sweep, a live episode would be destroyed for the crime of belonging to
    an old conversation.
    """
    clock = MovableClock()
    # Retention is unset on the *stage's clock path* by giving the episode no
    # expiry, so it stays live while the conversation ages past the horizon.
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation_id, episodes = await _capture_turns(wiring, 1)
    kept = await wiring.memory.get(episodes[0])
    assert kept is not None
    await wiring.memory.add(kept.model_copy(update={"expires_at": None}))

    clock.advance(30 * DAY)

    assert await wiring.stage.reclaim() == 0
    assert await wiring.conversations.get(conversation_id) is not None
    assert await wiring.memory.get(episodes[0]) is not None, "reclaim destroys nothing"


async def test_reclaim_inspects_every_batch_before_deciding_a_conversation_is_empty() -> None:
    """§7: an implementation that inspected only the first batch would orphan the rest.

    The live episode sits **beyond** the first batch, which is the case the
    single-batch fixture cannot catch — and which the multi-batch *deletion* test
    does not catch either, since deletion destroys what it finds rather than asking
    whether anything survives.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY, purge_batch=2)
    conversation_id, episodes = await _capture_turns(wiring, 5)
    survivor = await wiring.memory.get(episodes[4])
    assert survivor is not None
    await wiring.memory.add(survivor.model_copy(update={"expires_at": None}))

    clock.advance(30 * DAY)

    assert await wiring.stage.reclaim() == 0
    assert await wiring.conversations.get(conversation_id) is not None
    assert await wiring.memory.get(episodes[4]) is not None


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
        conversations=conversations, memory=memory, retention=started_under, now=clock
    )
    conversation = await started.begin(None)  # emptied by construction: no turn ever landed

    clock.advance(10 * DAY)
    conversations.retune(reclaimed_under)
    reclaiming = ConversationLifecycle(
        conversations=conversations, memory=memory, retention=reclaimed_under, now=clock
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


async def test_a_turn_held_past_the_horizon_is_answered_but_not_recorded() -> None:
    """§7: the accepted mid-turn window, pinned rather than rediscovered as a bug.

    A conversation idle for the whole horizon, revived by a continuation that then
    takes longer than that horizon to produce an answer: reclaim fires mid-turn, the
    record is dropped, and the capture append behind it is refused. The user gets
    their answer and no turn is recorded — reported, never silent. Pinning it stops
    a later reader mistaking the window for a bug, and a later implementer from
    inventing the lease this ADR declines.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation = await wiring.stage.begin(None)

    clock.advance(7 * DAY)
    await wiring.stage.begin(conversation.id)  # the turn begins; activity is marked
    clock.advance(7 * DAY + MINUTE)  # ...and the turn outlasts the whole horizon
    assert await wiring.stage.reclaim() == 1

    report = await wiring.stage.capture(conversation.id, content="answered, far too late")

    assert report.degraded is True
    assert report.episode_id is None


# --- the composed export (§9) --------------------------------------------


async def test_the_user_facing_export_drops_a_turn_whose_episode_is_gone() -> None:
    """§9: this is a capture-stage test, not a store one.

    The store snapshot legitimately still carries the rows. An implementation that
    handed the raw snapshot to the user would pass every store-level export
    assertion while leaking when the user was talking and how often.
    """
    wiring = Wiring()
    conversation_id, episodes = await _capture_turns(wiring, 3)
    assert await wiring.memory.delete(episodes[1]) is True

    exported = await wiring.stage.export()

    assert [turn.episode_id for turn in exported.conversations.turns] == [
        episodes[0],
        episodes[2],
    ]
    assert [one.id for one in exported.conversations.conversations] == [conversation_id]
    assert {record.id for record in exported.memories} == {episodes[0], episodes[2]}


async def test_a_conversation_whose_episodes_have_all_expired_exports_as_nothing() -> None:
    """§9: not an empty shell with a timeline.

    Exporting the rows would say *that* an exchange happened and *when*, for content
    §7 has already removed from every read.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock, retention=7 * DAY)
    conversation_id, _ = await _capture_turns(wiring, 2)

    clock.advance(7 * DAY + MINUTE)

    exported = await wiring.stage.export()

    assert exported.conversations.turns == ()
    assert [one.id for one in exported.conversations.conversations] == []
    assert conversation_id not in {one.id for one in exported.conversations.conversations}


async def test_a_conversation_that_never_had_a_turn_still_exports() -> None:
    """§9's rule is about a conversation *whose episodes have all expired*.

    One that never recorded a turn has no timeline to leak, and the store's own
    contract already holds that an empty conversation is state the user holds. The
    boundary is stated here so a later reader finds the decision rather than
    re-deriving it from the filter's shape.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    exported = await wiring.stage.export()

    assert [one.id for one in exported.conversations.conversations] == [conversation.id]
    assert exported.conversations.turns == ()


@pytest.mark.parametrize("whole_conversation", [False, True], ids=["one-turn", "conversation"])
async def test_a_deletion_racing_the_export_never_strands_a_turn(
    *, whole_conversation: bool
) -> None:
    """§9: the property filtering against *the same artifact* buys.

    ``MemoryStore.export`` is taken first, then the deletion lands, then the
    conversation snapshot is taken. Filtering against a **live** read would drop
    nothing — the memory half still carries the episode — while filtering against
    the artifact keeps the two halves agreeing. Either way the artifact never
    carries a turn whose episode it does not also carry, which is the one thing that
    cannot happen in any race.
    """
    clock = MovableClock()
    deleted: list[str] = []

    class DeletesMidExport(FakeMemoryStore):
        """Lets a deletion land between the two halves of the export."""

        def __init__(self) -> None:
            super().__init__(now=clock)
            self.on_export: object | None = None

        async def export(self) -> list[MemoryRecord]:
            records = await super().export()
            if self.on_export is not None:
                await self.on_export()  # type: ignore[operator]  # a test hook
                self.on_export = None
            return records

    memory = DeletesMidExport()
    wiring = Wiring(clock=clock, memory=memory)
    conversation_id, episodes = await _capture_turns(wiring, 2)

    async def _delete() -> None:
        if whole_conversation:
            await wiring.stage.delete(conversation_id)
        else:
            await memory.delete(episodes[0])
        deleted.append(conversation_id)

    memory.on_export = _delete

    exported = await wiring.stage.export()

    assert deleted == [conversation_id], "the fixture must really have raced the export"
    carried = {record.id for record in exported.memories}
    assert all(turn.episode_id in carried for turn in exported.conversations.turns), (
        "the artifact must never claim an exchange whose content it cannot show"
    )
    indexed = {turn.conversation_id for turn in exported.conversations.turns}
    assert {one.id for one in exported.conversations.conversations} <= indexed | {conversation_id}


# --- serialisation across two engines (§8) -------------------------------


async def test_a_capture_and_a_deletion_of_one_conversation_serialise() -> None:
    """§8: through **two stages sharing one pair of stores**, not one.

    A lock inside a single coordinator passes the one-coordinator version of this
    test and fails the topology the engine already supports — "another engine over
    the same durable stores" — which is the fault this clause exists to catch. The
    guarantee is the *store's*, so two stages over it get it for free, and that is
    the point being asserted.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, _ = await _capture_turns(wiring, 1)
    other = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=wiring.memory,
        retention=RETENTION,
        now=clock,
    )

    captured, _ = await asyncio.gather(
        wiring.stage.capture(conversation_id, content="racing"),
        other.delete(conversation_id),
    )

    if captured.episode_id is None:
        assert captured.degraded is True
    else:  # the append won the race; the post-write verification then compensated
        assert await wiring.memory.get(captured.episode_id) is None, (
            "an episode written into a conversation being deleted must not survive it"
        )


async def test_a_capture_landing_inside_the_grace_is_swept_and_one_after_it_is_the_residue() -> (
    None
):
    """§8: the window this ADR accepts, and the reach the grace buys.

    Inside the grace the tombstone still names the late episode, so the reclaim
    finds and destroys it. After the grace the record is gone and the episode is an
    orphan — the accepted residue, which is **visible and destroyable** through the
    surfaces the user already has, not invisible. And the reclaim is idempotent.
    """
    clock = MovableClock()
    wiring = Wiring(clock=clock)
    conversation_id, episodes = await _capture_turns(wiring, 1)
    await wiring.conversations.stamp_deleted(conversation_id)

    # Inside the grace: the sweep still reaches the episode the index names.
    assert await wiring.stage.sweep_deletions() == 0, "the grace has not elapsed"
    assert await wiring.memory.get(episodes[0]) is None, "step 2 destroys regardless of grace"

    clock.advance(GRACE)
    assert await wiring.stage.sweep_deletions() == 1
    assert await wiring.stage.sweep_deletions() == 0, "a re-run is a no-op"

    # After the record is dropped, a capture that commits has nowhere to record
    # itself: the append is refused, which is the loud half of the residue.
    late = await wiring.stage.capture(conversation_id, content="far too late")
    assert late.degraded is True
    assert late.episode_id is None
