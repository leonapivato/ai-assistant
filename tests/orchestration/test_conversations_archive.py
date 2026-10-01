"""Destruction reaches the transcript, and eviction does not (ADR-0225 §5, §6).

The archive's own behaviour is the store's and is pinned by the shared conformance
suites in ``tests/archive/``. What is here is the *lifecycle's*: what the two
deletion scopes destroy, what a failure of the archive's discard costs, and that the
retention horizon evicts an episode without destroying its transcript. Where the
entry is *written* — after the episode, before ``record_turn``, with the deletion
compensation behind it (ADR-0283 §7) — is the writer's, and its own suite
(``test_activation_writer.py``) owns it.

**Every case drives the real ``ConversationLifecycle`` over canonical fakes**, with
each conversation's past seeded as the writer leaves it: an episode on the
conversation's channel, its archive entry at the episode's address, and the
conversation's ``record_turn``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from channel_episodes import channel_ids, conversation_episode

from ai_assistant.core.errors import MemoryStoreError, TranscriptArchiveError
from ai_assistant.core.types import ExchangeDisposition, TranscriptEntry
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeTranscriptArchiveWriter,
)

AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
RETENTION = 30 * DAY

#: What every seeded exchange says, so an entry is recognisably the one seeded.
SAID = "the lender was Ravensworth"
ANSWERED = "you said it on a Tuesday"


class MovableClock:
    """A clock a case can step forward, so a horizon is reachable."""

    def __init__(self, start: datetime = AT) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._now += delta


class Wiring:
    """A lifecycle stage over three canonical fakes, all sharing one clock."""

    def __init__(self, *, retention: timedelta | None = RETENTION) -> None:
        self.clock = MovableClock()
        self.retention = retention
        self.memory = FakeMemoryStore(now=self.clock)
        self.conversations = FakeConversationStore(now=self.clock, retention=retention)
        self.archive = FakeTranscriptArchiveWriter()
        self.stage = self.lifecycle()

    def lifecycle(self, *, archive_enabled: bool = True) -> ConversationLifecycle:
        """A stage over this wiring's stores as they stand now."""
        return ConversationLifecycle(
            conversations=self.conversations,
            memory=self.memory,
            archive=self.archive,
            archive_enabled=archive_enabled,
            retention=self.retention,
            now=self.clock,
        )

    async def exchange(self, conversation_id: str, episode_id: str) -> str:
        """Seed one recorded exchange as the writer leaves it (ADR-0283 §7).

        The episode with the writer's expiry, its archive entry at the episode's own
        address, then ``record_turn``.
        """
        at = self.clock()
        expires_at = at + self.retention if self.retention is not None else None
        await self.memory.add(
            conversation_episode(conversation_id, episode_id, occurred_at=at, expires_at=expires_at)
        )
        await self.archive.append(
            TranscriptEntry(
                address=episode_id,
                conversation_id=conversation_id,
                occurred_at=at,
                asked=SAID,
                replied=ANSWERED,
                disposition=ExchangeDisposition.NO_ACTION_NEEDED,
            )
        )
        await self.conversations.record_turn(conversation_id, episode_id=episode_id, occurred_at=at)
        return episode_id


# --- the switch (§6) ----------------------------------------------------------


async def test_the_switch_does_not_stop_the_conversation_scoped_destroy() -> None:
    """§6: it gates the write alone, so what is held stays destroyable."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.exchange(conversation.id, "activation:one")
    off = wiring.lifecycle(archive_enabled=False)

    await off.delete(conversation.id)

    assert wiring.archive.recorded == {}


# --- eviction versus destruction (§5, §13 items 3 and 4) --------------------


async def test_an_entry_survives_the_expiry_and_reclaim_of_its_episode() -> None:
    """ADR-0225 §5: expiry evicts, and never destroys.

    The whole design in one case: the horizon governs the *working set* — what is
    retrieved, what is observed, what reaches a prompt, what an id resolves to — and
    destruction governs the *text*.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    episode = await wiring.exchange(conversation.id, "activation:one")

    wiring.clock.advance(RETENTION + DAY)
    assert await wiring.memory.get(episode) is None, "the episode is past its horizon"
    await wiring.memory.purge_expired()
    assert await wiring.stage.reclaim() == 1, "and the conversation record was reclaimed"

    assert len(wiring.archive.recorded) == 1, "the transcript stayed"


async def test_forgetting_a_conversation_destroys_its_transcript() -> None:
    """ADR-0225 §5: destruction is a user act, and it reaches the archive whole."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.exchange(conversation.id, "activation:one")
    await wiring.exchange(conversation.id, "activation:two")

    assert await wiring.stage.delete(conversation.id) is True

    assert wiring.archive.recorded == {}
    assert await channel_ids(wiring.memory, conversation.id) == []


async def test_a_reclaimed_conversation_still_yields_its_transcript_to_the_destroy() -> None:
    """§5, and §13 item 4: the destroy resolves inside the archive.

    The reclaim drops an emptied conversation's record on the horizon, after which
    ``forget-conversation`` refuses that id as unknown. If the cascade had been
    "delete what the conversation names", a user whose conversation had been
    reclaimed could *read* their transcript and could not *destroy* it — which is
    ADR-0004 §6's right made conditional on a sweep.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.exchange(conversation.id, "activation:one")
    wiring.clock.advance(RETENTION + DAY)
    await wiring.memory.purge_expired()
    assert await wiring.stage.reclaim() == 1
    assert await wiring.conversations.get(conversation.id) is None
    assert len(wiring.archive.recorded) == 1

    assert await wiring.archive.discard_conversation(conversation.id) == 1

    assert wiring.archive.recorded == {}


# --- the deletion failure paths (§5, §13 item 14) ---------------------------


async def test_a_failed_archive_discard_deletes_no_episode_and_drops_nothing() -> None:
    """ADR-0225 §5: the discard is the first action of §8's step 2.

    A discard that raises aborts the call there and no clause of §8 changes: every
    episode is still on the conversation's channel, so step 3's own condition is unmet,
    the tombstone survives, and the reclaim re-runs the whole of step 2 — this discard
    included.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    episode = await wiring.exchange(conversation.id, "activation:one")
    wiring.archive.fail()

    with pytest.raises(TranscriptArchiveError):
        await wiring.stage.delete(conversation.id)

    assert await wiring.memory.get(episode) is not None, "no episode was deleted"
    assert await channel_ids(wiring.memory, conversation.id) == [episode]
    assert conversation.id in await wiring.conversations.stamped_conversation_ids()


async def test_the_sweep_finishes_a_deletion_whose_archive_discard_had_failed() -> None:
    """§5: the tombstone stands and the re-run carries it through."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    episode = await wiring.exchange(conversation.id, "activation:one")
    wiring.archive.fail()
    with pytest.raises(TranscriptArchiveError):
        await wiring.stage.delete(conversation.id)

    wiring.archive = FakeTranscriptArchiveWriter(wiring.archive.recorded.values())
    recovered = wiring.lifecycle()
    wiring.clock.advance(2 * timedelta(hours=1))

    assert await recovered.sweep_deletions() == 1

    assert wiring.archive.recorded == {}
    assert await wiring.memory.get(episode) is None


async def test_a_second_sweep_accepts_an_already_empty_archive_as_a_no_op() -> None:
    """ADR-0225 §5, and §13 item 14's other side — the one the archive-first order creates.

    The archive discard *succeeds* and a ``MemoryStore.delete`` then raises part-way
    through step 2: the tombstone and the channel's episodes survive, no drop happens,
    and the sweep run again finds the archive already empty. Zero is the conforming
    answer and not a failure, so the second run carries the remaining episode
    deletions through to the drop.
    """
    refusals = {"count": 1}

    class Faulting(FakeMemoryStore):
        async def delete(self, record_id: str) -> bool:
            if refusals["count"]:
                refusals["count"] -= 1
                msg = "the store would not delete"
                raise MemoryStoreError(msg)
            return await super().delete(record_id)

    wiring = Wiring()
    wiring.memory = Faulting(now=wiring.clock)
    stage = wiring.lifecycle()
    conversation = await stage.begin(None)
    await wiring.exchange(conversation.id, "activation:one")
    await wiring.exchange(conversation.id, "activation:two")
    assert len(wiring.archive.recorded) == 2

    with pytest.raises(MemoryStoreError):
        await stage.delete(conversation.id)
    assert wiring.archive.recorded == {}, "the transcript went first and went whole"
    # The stamp hides a conversation from every presenting read, so the tombstone is
    # visible only through the sweep's own enumeration.
    assert conversation.id in await wiring.conversations.stamped_conversation_ids()
    assert len(await channel_ids(wiring.memory, conversation.id)) == 2

    wiring.clock.advance(2 * timedelta(hours=1))
    assert await stage.sweep_deletions() == 1, "the second run finishes it"
    assert await channel_ids(wiring.memory, conversation.id) == []
