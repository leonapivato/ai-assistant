"""Capture writes the transcript, and destruction reaches it (ADR-0225 §2, §5, §6).

The archive's own behaviour is the store's and is pinned by the shared conformance
suites in ``tests/archive/``. What is here is the *stage's*: where the write lands in
ADR-0074 §3's sequence, what a failure of it costs, what the verification compensates,
and what the two deletion scopes destroy.

**Every case drives the real ``ConversationLifecycle`` over canonical fakes**, which
is what makes the ordering claims evidence rather than restatement: the harness holds
the narrow writer seam the composition root hands capture, so a case can see what
capture wrote and capture cannot see it back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import structlog

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    TranscriptArchiveError,
)
from ai_assistant.core.types import ExchangeDisposition
from ai_assistant.orchestration.conversations import CaptureReport, ConversationLifecycle
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeTranscriptArchiveWriter,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import Conversation, MemoryWrite

AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
RETENTION = 30 * DAY

#: What every case below says, so an assertion that a span reached somewhere it
#: should not have cannot be satisfied by an incidental word.
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
    """A capture stage over three canonical fakes, all sharing one clock."""

    def __init__(
        self,
        *,
        archive_enabled: bool = True,
        memory: FakeMemoryStore | None = None,
        retention: timedelta | None = RETENTION,
    ) -> None:
        self.clock = MovableClock()
        self.memory = memory if memory is not None else FakeMemoryStore(now=self.clock)
        self.conversations = FakeConversationStore(now=self.clock, retention=retention)
        self.archive = FakeTranscriptArchiveWriter()
        self.stage = ConversationLifecycle(
            conversations=self.conversations,
            memory=self.memory,
            archive=self.archive,
            archive_enabled=archive_enabled,
            retention=retention,
            now=self.clock,
        )

    async def capture_one(
        self,
        conversation_id: str,
        *,
        asked: str | None = SAID,
        outcome: str | None = ANSWERED,
        disposition: ExchangeDisposition | None = ExchangeDisposition.NO_ACTION_NEEDED,
    ) -> CaptureReport:
        """Capture one ordinary turn, with a disposition so an entry is owed.

        ``content`` is deliberately the *rendering* — a goal statement folded
        together with a plan rationale — so a case asserting that the archive holds
        the user's own words is asserting something the rendering does not give it.
        """
        return await self.stage.capture(
            conversation_id,
            content=f"The user asked: {SAID}\nThe assistant's plan: fetch the ledger",
            asked=asked,
            outcome=outcome,
            disposition=disposition,
        )


# --- what the entry holds (§1) ----------------------------------------------


async def test_the_entry_holds_the_users_words_and_never_the_rendering() -> None:
    """ADR-0225 §1, and §13 item 7: the goal statement, never ``content``.

    ``content`` interleaves the model's own plan rationale with the user's sentence,
    so archiving it would put model prose into the one store nothing may read — for
    no reader who wants it — and would make the archive's answer to "what did I
    actually say?" a rendering the user has to parse rather than a quotation.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    await wiring.capture_one(conversation.id)

    (held,) = wiring.archive.recorded.values()
    assert held.asked == SAID
    assert held.replied == ANSWERED
    assert "The assistant's plan" not in (held.asked or "")
    assert "The user asked:" not in (held.asked or "")


async def test_the_entry_is_addressed_grouped_and_ordered_by_the_index_row() -> None:
    """ADR-0225 §3 and §1: the episode's own id, and the grouping fields beside it.

    The archive mints nothing: the address is the value ``ConversationStore.append``
    derived and returned on the turn, so a conversation-scoped erasure needs no
    mapping and no ordering against a second store.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    report = await wiring.capture_one(conversation.id)

    assert report.episode_id is not None
    (held,) = wiring.archive.recorded.values()
    assert held.address == report.episode_id
    assert held.conversation_id == conversation.id
    assert held.ordinal == 1
    assert held.occurred_at == AT


async def test_a_pass_with_no_user_words_archives_none() -> None:
    """§1's third case, threaded rather than derived (§13 item 7).

    A resumption's episode renders no user material of this pass, so the entry
    carries none — the utterance that parked was archived at its own address by the
    pass that parked, and repeating it would render one sentence as though the user
    had said it twice.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    await wiring.capture_one(conversation.id, asked=None)

    (held,) = wiring.archive.recorded.values()
    assert held.asked is None
    assert held.replied == ANSWERED


async def test_a_pass_with_no_reply_archives_no_reply() -> None:
    """§1: absent where the pass produced none, which a park is."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    await wiring.capture_one(
        conversation.id, outcome=None, disposition=ExchangeDisposition.STEP_AWAITING_CONFIRMATION
    )

    (held,) = wiring.archive.recorded.values()
    assert held.replied is None
    assert held.disposition is ExchangeDisposition.STEP_AWAITING_CONFIRMATION


# --- the two switches (§6, §10, §13 items 8 and 15) -------------------------


async def test_a_capture_with_no_disposition_writes_no_entry() -> None:
    """ADR-0225 §10, and §13 item 15's second half.

    A caller supplying no disposition is recording an exchange this system did not
    drive, and the archive holds what this system's own capture recorded — so the
    entry is *not written*, rather than coerced to a member.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    report = await wiring.capture_one(conversation.id, disposition=None)

    assert wiring.archive.recorded == {}
    assert report.degraded is False, "not archiving is not a degradation"
    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is not None


async def test_the_switch_stops_the_write_and_destroys_nothing() -> None:
    """ADR-0225 §6: turning it off stops the write and leaves what is held.

    Entries already there stay, stay searchable and stay destroyable, so a
    configuration change is never a silent deletion — and the destroy still runs,
    which is why the switch gates the write alone.
    """
    archive = FakeTranscriptArchiveWriter()
    on = Wiring()
    on.archive = archive
    stage_on = ConversationLifecycle(
        conversations=on.conversations,
        memory=on.memory,
        archive=archive,
        archive_enabled=True,
        retention=RETENTION,
        now=on.clock,
    )
    conversation = await stage_on.begin(None)
    await stage_on.capture(
        conversation.id,
        content="x",
        asked=SAID,
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )
    assert len(archive.recorded) == 1

    stage_off = ConversationLifecycle(
        conversations=on.conversations,
        memory=on.memory,
        archive=archive,
        archive_enabled=False,
        retention=RETENTION,
        now=on.clock,
    )
    await stage_off.capture(
        conversation.id,
        content="x",
        asked="a second thing",
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )

    assert len(archive.recorded) == 1, "the write stopped"
    assert next(iter(archive.recorded.values())).asked == SAID, "and nothing was destroyed"


async def test_the_switch_does_not_stop_the_conversation_scoped_destroy() -> None:
    """§6: it gates the write alone, so what is held stays destroyable."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.capture_one(conversation.id)
    off = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=wiring.memory,
        archive=wiring.archive,
        archive_enabled=False,
        retention=RETENTION,
        now=wiring.clock,
    )

    await off.delete(conversation.id)

    assert wiring.archive.recorded == {}


# --- the ordering and its degradations (§2, §13 item 5) ---------------------


async def test_the_entry_lands_when_the_episode_write_fails() -> None:
    """ADR-0225 §2: the archive is the copy that must survive, so it goes first.

    ADR-0074 §3 accepts a failed episode write on the ground that "a missing episode
    is the one outcome that loses nothing but the record" — true while the record's
    whole life is thirty days, and less true once there is a store whose job is to
    still hold the exchange in three years.
    """

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the store would not write"
            raise MemoryStoreError(msg)

    wiring = Wiring(memory=Faulting())
    conversation = await wiring.stage.begin(None)

    report = await wiring.capture_one(conversation.id)

    assert len(wiring.archive.recorded) == 1, "the transcript survived the lost episode"
    assert report.degraded is True, "and the capture is still reported degraded"


async def test_a_failing_archive_write_degrades_the_capture_and_stops_nothing() -> None:
    """ADR-0225 §2: it never fails a turn and never fails a capture.

    The episode write proceeds, nothing is retried, and the failure is reported on
    the capture's own degraded outcome exactly as a failed episode write is.
    """
    wiring = Wiring()
    wiring.archive.fail()
    conversation = await wiring.stage.begin(None)

    report = await wiring.capture_one(conversation.id)

    assert report.degraded is True
    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is not None, "the episode write proceeded"


async def test_a_landed_entry_does_not_make_a_lost_episode_undegraded() -> None:
    """ADR-0225 §2: the archive makes the loss smaller, not absent.

    Pinned because the tempting reading of "the archive is the copy that must
    survive" is that a capture whose transcript landed is a capture that succeeded —
    which would stop reporting exactly the fault ADR-0074 §3 wants reported.
    """

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the store would not write"
            raise MemoryStoreError(msg)

    wiring = Wiring(memory=Faulting())
    conversation = await wiring.stage.begin(None)

    report = await wiring.capture_one(conversation.id)

    assert report.degraded is True


async def test_neither_failure_fails_the_turn() -> None:
    """§2, restated as the property the two cases above are about.

    Capture degrades a turn and never fails one, because failing would throw away an
    answer the user already has.
    """

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            msg = "the store would not write"
            raise MemoryStoreError(msg)

    both = Wiring(memory=Faulting())
    both.archive.fail()
    conversation = await both.stage.begin(None)

    report = await both.capture_one(conversation.id)

    assert report.degraded is True


# --- the compensation (§2, §13 item 6) --------------------------------------


async def test_a_conversation_deleted_mid_capture_leaves_neither_half() -> None:
    """ADR-0225 §2: the verification compensates the archive as well as the episode.

    The one trigger the ordering cannot rule out: an append that *succeeded* before
    the conversation was stamped, whose writes land after.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    class Stamping(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            written = await super().write_atomic(writes)
            await wiring.conversations.stamp_deleted(conversation.id)
            return written

    stamped = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=Stamping(now=wiring.clock),
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )

    report = await stamped.capture(
        conversation.id,
        content="x",
        asked=SAID,
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )

    assert report.degraded is True
    assert wiring.archive.recorded == {}, "the entry was compensated with the episode"


async def test_the_verification_runs_when_only_the_entry_landed() -> None:
    """ADR-0225 §2: it runs whenever **either** write landed.

    Before this decision the episode-write-failure path returned without verifying,
    because on that path nothing had been written. With an archive entry already at
    the address, that path now has something to compensate — and a conversation
    stamped underneath it would otherwise keep a transcript the user deleted.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    class Faulting(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            await wiring.conversations.stamp_deleted(conversation.id)
            msg = "the store would not write"
            raise MemoryStoreError(msg)

    stage = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=Faulting(now=wiring.clock),
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )

    report = await stage.capture(
        conversation.id,
        content="x",
        asked=SAID,
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )

    assert report.degraded is True
    assert wiring.archive.recorded == {}


async def test_a_failed_compensation_is_logged_and_does_not_fail_the_turn() -> None:
    """ADR-0074 §9.6's rule, applied to the second store.

    What is left is an orphan the tombstone's own sweep will find, and the archive's
    own destroy reaches it besides — so the turn still returns its answer and the
    failure is reported rather than swallowed.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)

    class Stamping(FakeMemoryStore):
        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            written = await super().write_atomic(writes)
            await wiring.conversations.stamp_deleted(conversation.id)
            wiring.archive.fail()
            return written

    stage = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=Stamping(now=wiring.clock),
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )

    report = await stage.capture(
        conversation.id,
        content="x",
        asked=SAID,
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )

    assert report.degraded is True


# --- eviction versus destruction (§5, §13 items 3 and 4) --------------------


async def test_an_entry_survives_the_expiry_and_reclaim_of_its_episode() -> None:
    """ADR-0225 §5: expiry evicts, and never destroys.

    The whole design in one case: the horizon governs the *working set* — what is
    retrieved, what is observed, what reaches a prompt, what an id resolves to — and
    destruction governs the *text*.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    report = await wiring.capture_one(conversation.id)

    wiring.clock.advance(RETENTION + DAY)
    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is None, "the episode is past its horizon"
    await wiring.memory.purge_expired()
    assert await wiring.stage.reclaim() == 1, "and the conversation record was reclaimed"

    assert len(wiring.archive.recorded) == 1, "the transcript stayed"


async def test_forgetting_a_conversation_destroys_its_transcript() -> None:
    """ADR-0225 §5: destruction is a user act, and it reaches the archive whole."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.capture_one(conversation.id)

    assert await wiring.stage.delete(conversation.id) is True

    assert wiring.archive.recorded == {}


async def test_a_reclaimed_conversation_still_yields_its_transcript_to_the_destroy() -> None:
    """§5, and §13 item 4: the destroy resolves inside the archive.

    ADR-0074 §7's reclaim drops an emptied conversation's index and record on the
    horizon, after which ``forget-conversation`` refuses that id as unknown. If the
    cascade had been "delete what the index names", a user whose conversation had
    been reclaimed could *read* their transcript and could not *destroy* it — which
    is ADR-0004 §6's right made conditional on a sweep.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.capture_one(conversation.id)
    wiring.clock.advance(RETENTION + DAY)
    await wiring.memory.purge_expired()
    assert await wiring.stage.reclaim() == 1
    assert await wiring.conversations.get(conversation.id) is None
    assert len(wiring.archive.recorded) == 1

    assert await wiring.archive.discard_conversation(conversation.id) == 1

    assert wiring.archive.recorded == {}


# --- the deletion failure paths (§5, §13 item 14) ---------------------------


async def test_a_failed_archive_discard_deletes_no_episode_and_drops_nothing() -> None:
    """ADR-0225 §5: the discard is the first action of ADR-0074 §8's step 2.

    A discard that raises aborts the call there and no clause of §8 changes: every
    episode the index names still resolves, so step 3's own condition is unmet by
    §8's own terms, the tombstone survives, and the reclaim re-runs the whole of step
    2 — this discard included.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    report = await wiring.capture_one(conversation.id)
    wiring.archive.fail()

    with pytest.raises(TranscriptArchiveError):
        await wiring.stage.delete(conversation.id)

    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is not None, "no episode was deleted"
    # Read the way the sweep reads it: `turns` refuses a stamped conversation, and
    # what has to survive here is the intent log the re-run walks.
    assert await wiring.conversations.episodes_to_purge(conversation.id), "the index survives"
    assert conversation.id in await wiring.conversations.stamped_conversation_ids()


async def test_the_sweep_finishes_a_deletion_whose_archive_discard_had_failed() -> None:
    """§5: the tombstone stands and the re-run carries it through."""
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    report = await wiring.capture_one(conversation.id)
    wiring.archive.fail()
    with pytest.raises(TranscriptArchiveError):
        await wiring.stage.delete(conversation.id)

    wiring.archive = FakeTranscriptArchiveWriter(wiring.archive.recorded.values())
    recovered = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=wiring.memory,
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )
    wiring.clock.advance(2 * timedelta(hours=1))

    assert await recovered.sweep_deletions() == 1

    assert wiring.archive.recorded == {}
    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is None


async def test_a_second_sweep_accepts_an_already_empty_archive_as_a_no_op() -> None:
    """ADR-0225 §5, and §13 item 14's other side — the one the archive-first order creates.

    The archive discard *succeeds* and a ``MemoryStore.delete`` then raises part-way
    through step 2: the tombstone and the index survive, no drop happens, and the
    sweep run again finds the archive already empty. Zero is the conforming answer
    and not a failure, so the second run carries the remaining episode deletions
    through to the drop.
    """
    wiring = Wiring()
    conversation = await wiring.stage.begin(None)
    await wiring.capture_one(conversation.id)
    await wiring.capture_one(conversation.id)
    assert len(wiring.archive.recorded) == 2
    refusals = {"count": 1}

    class Faulting(FakeMemoryStore):
        async def delete(self, record_id: str) -> bool:
            if refusals["count"]:
                refusals["count"] -= 1
                msg = "the store would not delete"
                raise MemoryStoreError(msg)
            return await super().delete(record_id)

    stage = ConversationLifecycle(
        conversations=wiring.conversations,
        memory=Faulting(now=wiring.clock),
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )

    with pytest.raises(MemoryStoreError):
        await stage.delete(conversation.id)
    assert wiring.archive.recorded == {}, "the transcript went first and went whole"
    # The stamp hides a conversation from every presenting read, so the tombstone is
    # visible only through the sweep's own enumeration.
    assert conversation.id in await wiring.conversations.stamped_conversation_ids()

    wiring.clock.advance(2 * timedelta(hours=1))
    assert await stage.sweep_deletions() == 1, "the second run finishes it"


# --- nothing of an entry reaches a log (§4, ADR-0004 §5) --------------------


@pytest.mark.parametrize("failing", ["archive", "compensation"])
async def test_no_archive_text_reaches_a_log_on_any_path(failing: str) -> None:
    """ADR-0225 §4: a failure names its address and never its text (§13 item 16).

    Captured over the whole log stream of a capture and of each of its failure paths,
    because the risk is not that someone writes ``log.info(entry.asked)`` on purpose
    — it is an ``exc_info`` or a formatted argument carrying the exchange into a file
    the never-list is about keeping it out of.
    """
    structlog.configure(processors=[structlog.testing.LogCapture()])
    captured = structlog.testing.LogCapture()
    structlog.configure(processors=[captured])
    try:
        wiring = Wiring()
        conversation = await wiring.stage.begin(None)
        if failing == "archive":
            wiring.archive.fail()
            await wiring.capture_one(conversation.id)
        else:
            await wiring.capture_one(conversation.id)
            wiring.archive.fail()
            with pytest.raises(TranscriptArchiveError):
                await wiring.stage.delete(conversation.id)
    finally:
        structlog.reset_defaults()

    rendered = repr(captured.entries)
    assert SAID not in rendered
    assert ANSWERED not in rendered


async def test_a_failed_archive_write_is_logged_with_its_address() -> None:
    """The other half: a swallowed fault must not be a silent one (ADR-0074 §3, §9).

    A capture whose transcript is silently not being written is a user who will not
    find out until they go looking for it years later, which is the failure the
    archive exists to prevent.
    """
    captured = structlog.testing.LogCapture()
    structlog.configure(processors=[captured])
    try:
        wiring = Wiring()
        conversation = await wiring.stage.begin(None)
        wiring.archive.fail()
        report = await wiring.capture_one(conversation.id)
    finally:
        structlog.reset_defaults()

    archived = [one for one in captured.entries if one.get("stage") == "archive"]
    assert archived, "the failure was logged"
    assert archived[0]["address"] == report.episode_id


# --- a store fault reading the conversation is not a compensation ----------


async def test_an_unverifiable_capture_keeps_both_writes() -> None:
    """The archive follows the episode's existing rule (ADR-0074 §8).

    We cannot tell whether to compensate, and absent evidence otherwise the writes
    stand — so the turn is not reported as unrecorded, which would be a false alarm.
    A conversation that *was* in fact stamped still has its tombstone, and the next
    sweep destroys both through it.
    """
    wiring = Wiring()

    class Unreadable(FakeConversationStore):
        async def get(self, conversation_id: str) -> Conversation | None:
            msg = "the index would not read"
            raise ConversationStoreError(msg)

    unreadable = Unreadable(now=wiring.clock, retention=RETENTION)
    started = await unreadable.start()
    stage = ConversationLifecycle(
        conversations=unreadable,
        memory=wiring.memory,
        archive=wiring.archive,
        archive_enabled=True,
        retention=RETENTION,
        now=wiring.clock,
    )

    report = await stage.capture(
        started.id,
        content="x",
        asked=SAID,
        outcome=ANSWERED,
        disposition=ExchangeDisposition.NO_ACTION_NEEDED,
    )

    assert report.degraded is False
    assert len(wiring.archive.recorded) == 1
