"""The observation stage: selection, the write path, and what it reports (ADR-0077).

Every collaborator is a canonical fake from ``ai_assistant.testing`` or a thin
scripted wrapper around one, so nothing here imports a subsystem concrete (CLAUDE.md
golden rule 1). What is under test is the *stage*: which episodes it selects, what
it does with each proposal that comes back, and what its report says — never the
producer's own clauses, which its conformance suite owns.

The one hand-rolled double is :class:`_RacingWriter`, which delegates every call to
the canonical :class:`FakeMemoryWriter` and raises
:class:`UnresolvedEvidenceError` for named proposals. It has to be scripted:
ADR-0077 §5's race is an episode expiring *between* selection and the write, which
no fake can be asked to produce on its own, and delegating rather than replacing
keeps "the other two are still ingested" an assertion about records that really
landed.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreConflictError,
    MemoryStoreError,
    ModelError,
    UnknownConversationError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    DeferralAdmissionOutcome,
    EpisodicMemory,
    LearnDecision,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    ObservationOutcome,
    ObservationReport,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration import (
    MemoryWriteStage,
    ObservationRunReport,
    ObservationStage,
)
from ai_assistant.testing import (
    FakeConversationStore,
    FakeDeferralStore,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakeObserver,
    ObservationGate,
    ObservedBelief,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ai_assistant.core.protocols import MemoryWriter, Observer
    from ai_assistant.core.types import (
        Conversation,
        ConversationTurn,
        MemoryIngestResult,
        SourceReading,
    )

AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

#: The route the stage is told the observer reads through (ADR-0077 §3). Fixed here
#: so a case can assert the report names *that* route and not some other string.
ROUTE = "anthropic:claude-opus-4-8"

BATCH = 20

#: ADR-0218 §7's three run figures, at their shipped defaults so a case reads
#: against the values an unconfigured hub actually runs.
QUIET = timedelta(minutes=10)
MAX_AGE = timedelta(hours=2)
RUN_BUDGET = timedelta(minutes=5)

#: The instant a scheduled run's clock reads, unless a case says otherwise. An hour
#: past :data:`AT`, so a conversation whose activity was stamped at ``AT`` is quiet
#: by a wide margin and one stamped at ``RUN`` is not quiet at all.
RUN = AT + timedelta(hours=1)


class _Clock:
    """A store clock a case sets by hand.

    ``last_active_at`` and ``last_turn_at`` are what ADR-0218 §1 turns on, and both
    come from the store's clock rather than the caller's — so a case that wants a
    conversation *active* at one instant and *recorded* at another has to move this
    between the calls, which the harness's second-per-reading clock cannot express.
    """

    def __init__(self, at: datetime = AT) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


#: Spelled once: an ``INFERRED`` belief needs two distinct supports (ADR-0077 §5).
INFERRED = MemorySource.INFERRED


class _RacingWriter:
    """A ``MemoryWriter`` that refuses named proposals for unresolved evidence.

    Delegates everything else to the canonical :class:`FakeMemoryWriter`, so a
    proposal this does not refuse is really conflict-checked, ruled on and written.
    """

    def __init__(self, inner: FakeMemoryWriter, *, unresolved: dict[str, tuple[str, ...]]) -> None:
        """Script the refusal.

        Args:
            inner: The real write path every un-refused proposal goes through.
            unresolved: Proposed-record id → the ids the writer reports as
                unresolved for it.
        """
        self._inner = inner
        self._unresolved = unresolved
        self.calls: list[str] = []

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Refuse if scripted for this proposal, otherwise really ingest it."""
        self.calls.append(proposal.proposed.id)
        ids = self._unresolved.get(proposal.proposed.id)
        if ids is not None:
            msg = "evidence does not resolve"
            raise UnresolvedEvidenceError(msg, ids)
        return await self._inner.ingest(proposal)

    async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
        """Delegate the reading-level path unchanged (ADR-0115 §1).

        Present so this double still satisfies ``MemoryWriter``. Nothing in this
        module drives a reading — these cases are about the single-proposal seam —
        so the script this double carries applies to :meth:`ingest` alone.
        """
        return await self._inner.ingest_reading(reading)


class _FailingWriter:
    """A ``MemoryWriter`` that raises ``MemoryStoreError`` on its *n*-th call."""

    def __init__(self, inner: FakeMemoryWriter, *, fail_on: int) -> None:
        self._inner = inner
        self._fail_on = fail_on
        self.calls = 0

    async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
        """Delegate, except on the call the script names."""
        self.calls += 1
        if self.calls == self._fail_on:
            msg = "the store is broken"
            raise MemoryStoreError(msg)
        return await self._inner.ingest(proposal)

    async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
        """Delegate the reading-level path unchanged (ADR-0115 §1).

        Present so this double still satisfies ``MemoryWriter``. Nothing in this
        module drives a reading — these cases are about the single-proposal seam —
        so the script this double carries applies to :meth:`ingest` alone.
        """
        return await self._inner.ingest_reading(reading)


class _FailingObserver:
    """An ``Observer`` whose model call fails, as a real provider failure would."""

    def __init__(self) -> None:
        self.calls = 0

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Raise unwrapped, its classification intact (ADR-0013 §5)."""
        del episodes
        self.calls += 1
        msg = "the provider is down"
        raise ModelError(msg)


class _WatchedConversations(FakeConversationStore):
    """The canonical store fake, with every advance it is asked for recorded.

    A thin subclass rather than a delegating wrapper, so what is under test is the
    canonical fake's own behaviour. It exists because ADR-0212 §8 asks for cases
    asserted **on the store** and not only on the reported result — "a pass with no
    candidate at all, and a pass over an explicitly named conversation with nothing
    above its watermark, each make no ``record_observed`` call whatever" — and
    ``ConversationStore`` exposes no call log, deliberately.

    :attr:`hold_advance` is the second lever, and it is what lets two passes over one
    conversation be interleaved deterministically: an advance whose 1-based index is
    in that set announces its arrival on :attr:`reached` and suspends until
    :attr:`release` for the same index is set.
    """

    def __init__(self, *, now: Callable[[], datetime], new_id: Callable[[], str] | None) -> None:
        """Wrap the canonical fake, adding the call log and the advance gate."""
        if new_id is None:
            super().__init__(now=now)
        else:
            super().__init__(now=now, new_id=new_id)
        #: Every ``record_observed`` this store was asked for, in call order.
        self.advances: list[tuple[str, int]] = []
        #: 1-based indexes of advances to hold at the gate.
        self.hold_advance: set[int] = set()
        self.reached: dict[int, asyncio.Event] = defaultdict(asyncio.Event)
        self.release: dict[int, asyncio.Event] = defaultdict(asyncio.Event)
        #: When set, the advance refuses instead of writing — a store fault at the
        #: one call ADR-0212 §6 rules on, scripted because no fake can be asked to
        #: produce one and the disposition is the whole subject of that section.
        self.advance_raises = False
        #: When set, the advance commits and the awaiting task is then cancelled
        #: before the call returns — §6's commit-ambiguous half, in the half that is
        #: assertable. ADR-0054's shield makes this the real shape rather than a
        #: contrivance: a store whose write runs in a worker thread can commit and
        #: then have the awaiting task cancelled.
        self.cancel_after_advance = False
        #: When set, the conversation is stamped deleted immediately before the
        #: advance — §6's deletion race, which no fake produces on its own.
        self.stamp_before_advance = False
        #: Seconds the candidate listing parks for before answering. ADR-0218 §2's
        #: due test is awaited work of its own — a listing and up to fifty page
        #: probes — so a case about the run budget needs a way to spend it *there*
        #: rather than inside a pass.
        self.listing_delay = 0.0
        #: Every ``turns_after`` and every ``turns`` this store was asked for, in
        #: call order. ADR-0218 §2 rules that "the page read to decide is the page
        #: the pass reads: no turn is read twice", which is a claim about *calls*
        #: and is unobservable from any report.
        self.pages_read: list[tuple[str, int | None]] = []
        self.tails_read: list[str] = []

    def plant_watermark(self, conversation_id: str, ordinal: int) -> None:
        """Write a watermark the contract itself has no way to write (ADR-0212 §7).

        ``record_observed`` refuses an ordinal above the conversation's highest, so a
        watermark this store must *discard* is unreachable through the seam — which
        is the whole point of §7's clause and the reason it has to be planted here.
        Only that limb is expressible against a dict-backed store: a value that is
        not an integer, or one below the first ordinal, cannot be held by a frozen
        pydantic model at all, and the ``sqlite3`` store's own cases carry the limbs
        a *file* can hold.
        """
        stored = self._conversations[conversation_id]
        self._conversations[conversation_id] = stored.model_copy(
            update={"observed_through": ordinal}
        )

    def raw_watermark(self, conversation_id: str) -> int | None:
        """The watermark as stored, readable even once the conversation is stamped.

        Every presenting read hides a stamped conversation (ADR-0074 §9), so this is
        the only way to assert §6's "the watermark is untouched" for the one case in
        which the conversation is gone by the time the pass ends.
        """
        return self._conversations[conversation_id].observed_through

    async def conversations_with_unobserved_turns(self, *, limit: int = 50) -> list[Conversation]:
        """List the candidates, parking first if the case wants the budget spent here."""
        if self.listing_delay:
            await asyncio.sleep(self.listing_delay)
        return await super().conversations_with_unobserved_turns(limit=limit)

    async def turns_after(
        self,
        conversation_id: str,
        *,
        after_ordinal: int | None = None,
        limit: int | None = None,
    ) -> list[ConversationTurn]:
        """Read the page above a position, recording that the read happened."""
        self.pages_read.append((conversation_id, after_ordinal))
        return await super().turns_after(conversation_id, after_ordinal=after_ordinal, limit=limit)

    async def turns(
        self, conversation_id: str, *, limit: int | None = None, before_ordinal: int | None = None
    ) -> list[ConversationTurn]:
        """Read the tail, recording that the read happened."""
        self.tails_read.append(conversation_id)
        return await super().turns(conversation_id, limit=limit, before_ordinal=before_ordinal)

    async def record_observed(
        self, conversation_id: str, *, through_ordinal: int
    ) -> Conversation | None:
        """Record the advance asked for, hold it if the case wants to, then perform it."""
        self.advances.append((conversation_id, through_ordinal))
        index = len(self.advances)
        if index in self.hold_advance:
            self.reached[index].set()
            async with asyncio.timeout(5.0):
                await self.release[index].wait()
        if self.advance_raises:
            msg = "the conversation index could not be written"
            raise ConversationStoreError(msg)
        if self.stamp_before_advance:
            await super().stamp_deleted(conversation_id)
        stamped = await super().record_observed(conversation_id, through_ordinal=through_ordinal)
        if self.cancel_after_advance:
            raise asyncio.CancelledError
        return stamped


class Harness:
    """A wired :class:`ObservationStage` and the fakes behind it, for assertions."""

    def __init__(  # noqa: PLR0913 — one keyword per injected collaborator the stage takes, plus ADR-0218 §7's three run figures and the run's own clock
        self,
        *,
        observer: Observer | None = None,
        writer: MemoryWriter | None = None,
        policy: FakeMemoryPolicy | None = None,
        batch_size: int = BATCH,
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
        quiet_window: timedelta = QUIET,
        max_unobserved_age: timedelta = MAX_AGE,
        run_budget: timedelta = RUN_BUDGET,
        run_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._tick = 0
        #: The store's clock where a case supplied a settable one, so a helper can
        #: move it between ``start`` and ``append``.
        self.store_clock = now if isinstance(now, _Clock) else None
        self.memory = FakeMemoryStore(now=lambda: AT)
        self.conversations = _WatchedConversations(
            now=self._advancing if now is None else now, new_id=new_id
        )
        self.policy = policy if policy is not None else FakeMemoryPolicy()
        self.real_writer = FakeMemoryWriter(store=self.memory, policy=self.policy, now=lambda: AT)
        self.writer: MemoryWriter = writer if writer is not None else self.real_writer
        self.observer: Observer = observer if observer is not None else FakeObserver()
        # The stage reaches memory through the orchestration **write stage** rather
        # than through a `MemoryWriter` of its own (ADR-0078 §3), so an observed
        # proposal the policy defers parks a durable question. The queue is held here
        # so a case can read back what was parked.
        self.deferrals = FakeDeferralStore(now=lambda: AT)
        self.writes = MemoryWriteStage(writer=self.writer, deferrals=self.deferrals)
        self.stage = ObservationStage(
            observer=self.observer,
            conversations=self.conversations,
            memory=self.memory,
            writes=self.writes,
            batch_size=batch_size,
            route=ROUTE,
            # ADR-0218 §7's figures reach the **scheduled run** and nothing else:
            # `observe` applies no due test, so every case above this section is
            # unaffected by what they are.
            quiet_window=quiet_window,
            max_unobserved_age=max_unobserved_age,
            run_budget=run_budget,
            now=run_now if run_now is not None else (lambda: RUN),
        )

    def swap_writer(self, writer: MemoryWriter) -> None:
        """Put a scripted writer behind the stage's write stage.

        The stage holds the orchestration write stage rather than a ``MemoryWriter``
        (ADR-0078 §3), so a case that scripts the *writer* replaces the stage's
        writer by rebuilding the wrapper around it — over the **same** deferral queue,
        so nothing about what was parked changes with the swap.
        """
        self.writes = MemoryWriteStage(writer=writer, deferrals=self.deferrals)
        self.stage._writes = self.writes

    @property
    def fake(self) -> FakeObserver:
        """The injected observer as the canonical fake, for its call log.

        ``Observer`` exposes neither a call count nor the batches it was handed —
        deliberately, since neither is contract — so a case asserting on them has to
        narrow to the fake it wired.
        """
        assert isinstance(self.observer, FakeObserver)
        return self.observer

    def _advancing(self) -> datetime:
        """A clock that moves a second per reading.

        ``recent``'s order is ``last_active_at`` descending with ``id`` ascending as
        the tie-break, so a *pinned* clock would make "the most recently active
        conversation" a statement about ids. Two conversations that were genuinely
        active at different times is the case ADR-0077 §8's selector is about.
        """
        self._tick += 1
        return AT + timedelta(seconds=self._tick)

    def stage_over(self, observer: Observer) -> ObservationStage:
        """A second stage over the *same* stores, for interleaving two passes.

        Two passes over one conversation may overlap and nothing serialises them
        (ADR-0212 §5), so a case about that overlap needs two callers rather than one
        called twice — and each needs its own observer, because the gate that holds a
        pass mid-flight lives on the observer.
        """
        return ObservationStage(
            observer=observer,
            conversations=self.conversations,
            memory=self.memory,
            writes=self.writes,
            batch_size=BATCH,
            route=ROUTE,
        )

    async def conversation_with(self, turns: int, *, captured: int | None = None) -> str:
        """Start a conversation with ``turns`` turns, ``captured`` of them recorded.

        The default records every turn. A lower ``captured`` leaves the *oldest*
        turns with an index entry and no episode — the shape ADR-0074 §3 makes
        ordinary, since the index entry lands first and the episode write is
        best-effort.
        """
        recorded = turns if captured is None else captured
        conversation = await self.conversations.start()
        for ordinal in range(turns):
            turn = await self.conversations.append(conversation.id, occurred_at=AT)
            if ordinal >= turns - recorded:
                await self.memory.add(_episode(turn.episode_id))
        return conversation.id

    async def conversation_of(self, ordinals_with_episodes: Sequence[int], *, turns: int) -> str:
        """Start a conversation of ``turns`` turns, landing only the named ordinals.

        The general form of :meth:`conversation_with`, for the cases where *which*
        turns resolve is the point — a gap at the end of a page, a gap in its middle,
        or a page that resolves to nothing at all (ADR-0212 §5).
        """
        conversation = await self.conversations.start()
        for _ in range(turns):
            turn = await self.conversations.append(conversation.id, occurred_at=AT)
            if turn.ordinal in ordinals_with_episodes:
                await self.memory.add(_episode(turn.episode_id))
        return conversation.id

    async def append_turns(
        self, conversation_id: str, count: int, *, captured: bool = True
    ) -> None:
        """Record ``count`` further turns on an existing conversation."""
        for _ in range(count):
            turn = await self.conversations.append(conversation_id, occurred_at=AT)
            if captured:
                await self.memory.add(_episode(turn.episode_id))

    async def conversation_stamped(
        self,
        *,
        active_at: datetime,
        stamps: Sequence[datetime],
        captured: bool = True,
    ) -> str:
        """Start a conversation *active* at one instant, with turns stamped at others.

        The two instants ADR-0218 §1 turns on come from different clocks and this is
        what lets a case separate them: ``active_at`` is the store's, read by
        ``start``, and each of ``stamps`` is the **caller's** ``occurred_at``, which
        also sets ``last_turn_at``. A case wanting a conversation whose activity is
        recent and whose turns are old — or the reverse — sets them apart here.
        """
        assert self.store_clock is not None, "a case building stamped turns needs a _Clock"
        self.store_clock.at = active_at
        conversation = await self.conversations.start()
        for stamp in stamps:
            turn = await self.conversations.append(conversation.id, occurred_at=stamp)
            if captured:
                await self.memory.add(_episode(turn.episode_id))
        return conversation.id

    async def mark_active_at(self, conversation_id: str, at: datetime) -> None:
        """Record that a turn *began* at ``at``, recording no turn (ADR-0074 §3).

        ``mark_active`` "Record[s] that a turn has begun" and is called before the
        work, so "a turn that never completes still says the user was here" — which
        is the beat that makes ADR-0218 §2's residual reachable at all.
        """
        assert self.store_clock is not None, "a case moving the activity instant needs a _Clock"
        self.store_clock.at = at
        await self.conversations.mark_active(conversation_id)

    async def land(self, conversation_id: str, ordinal: int) -> None:
        """Write the episode a recorded turn names, as a late capture would."""
        await self.memory.add(_episode(f"conv:{conversation_id}:{ordinal}"))

    async def watermark(self, conversation_id: str) -> int | None:
        """Where the observation walk stands in this conversation, as the store reads it."""
        conversation = await self.conversations.get(conversation_id)
        assert conversation is not None
        return conversation.observed_through


def _episode(episode_id: str) -> EpisodicMemory:
    """One captured turn, as the capture stage writes it (ADR-0074 §4)."""
    return EpisodicMemory(
        id=episode_id,
        content=f"the user said something in {episode_id}",
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
    )


# --- selecting the batch (ADR-0077 §8) ----------------------------------


async def test_no_conversation_at_all_observes_nothing_and_names_no_route() -> None:
    """An empty store yields the zero report, and no model is asked (§9.7)."""
    harness = Harness()
    report = await harness.stage.observe()
    assert report == ObservationReport()
    assert report.route is None
    assert harness.fake.call_count == 0


async def test_an_unscoped_run_observes_the_least_recently_active_candidate() -> None:
    """With no id, the selector is the candidate listing's head (ADR-0212 §3).

    The direction is the point, and it is the half of ADR-0077 §8 this ADR replaces:
    ``recent``'s first row is the conversation the user is *using*, so taking it
    would re-select that one on every pass and never reach an idle one — ADR-0077
    §8's first named gap arriving through the cursor. Ascending activity reaches the
    idle one first, and serves the material nearest its retention horizon.
    """
    harness = Harness()
    older = await harness.conversation_with(2)
    newer = await harness.conversation_with(2)

    report = await harness.stage.observe()

    assert report.conversation_id == older
    assert report.conversation_id != newer
    assert report.episodes_read == 2


async def test_naming_the_other_conversation_reaches_the_episodes_outside_that_batch() -> None:
    """The pair pins the selector in both directions, and that everything is reachable.

    An implementation re-reading "the newest N episodes in the store" would pass the
    unscoped case above and fail this one — and its N+1th episode could never be
    requested at all (§8).
    """
    harness = Harness()
    older = await harness.conversation_with(2)
    await harness.conversation_with(2)

    report = await harness.stage.observe(older)

    assert report.conversation_id == older
    batch = harness.fake.batches[-1]
    assert {episode.id for episode in batch} == {
        turn.episode_id for turn in await harness.conversations.turns(older)
    }


async def test_two_unscoped_runs_walk_on_rather_than_re_reading_one_conversation() -> None:
    """ADR-0212 §3, replacing ADR-0077 §8's "no cursor and no rotation".

    This case used to assert the opposite — that two unscoped runs reselect the same
    conversation and hand the observer the *same* batch twice — and it was right to,
    because ADR-0077 §8 declined the durable state that would make anything else
    possible. §10(a) records the replacement: the first run's advance takes that
    conversation out of the candidate set, so the second reaches the one behind it,
    and the two batches are different.

    **What is not replaced is why a repeat would have been safe anyway.** ADR-0077
    §8's fold is what makes re-observation safe and the watermark only makes it rare
    (ADR-0212 §1, §6), so the surviving half of the old case is asserted below: the
    second run replaces nothing the first wrote.
    """
    harness = Harness()
    older = await harness.conversation_with(2)
    newer = await harness.conversation_with(2)

    first = await harness.stage.observe()
    after_one = {record.id for record in await harness.memory.export()}
    second = await harness.stage.observe()
    third = await harness.stage.observe()

    assert first.conversation_id == older
    assert second.conversation_id == newer
    assert len(harness.fake.batches) == 2
    assert harness.fake.batches[-1] != harness.fake.batches[-2], (
        "the second run walks on to the conversation behind the first, so the two "
        "passes read different episodes (ADR-0212 §3)"
    )
    # And with both conversations observed through their last turn there is no
    # candidate left: the third run reads nothing, asks no model, and reports the
    # zero report — which is what makes a timer safe to set (ADR-0212, Consequences).
    assert third == ObservationReport()
    assert harness.fake.call_count == 2
    # Nothing the first run wrote was replaced. That is the defect the old case was
    # narrowed to catch, stated over what survives rather than over a refusal: the
    # later runs' proposals carry minted ids, so they can neither collide with the
    # first run's records nor overwrite them. Whether they then *fold* is the
    # injected policy's business and not this stage's — this harness wires
    # `FakeMemoryPolicy`, which accepts by rule, and ADR-0159 §4(a)'s fold is pinned
    # against `DefaultMemoryPolicy` in `tests/memory/test_policy.py`.
    assert after_one <= {record.id for record in await harness.memory.export()}


async def test_a_producer_re_proposing_a_stored_id_is_refused() -> None:
    """ADR-0108 §2's own-id refusal, built rather than derived (#630, #735, #736).

    The rule is that "an id already naming a stored record is an accident in every
    case — a minting producer whose factory collided — and the honest response is a
    refusal rather than a silent replacement of a record no ruling was made about".
    ``_detect_conflicts`` filters the proposal's own id (#110), so such a proposal
    can never be folded into the record standing at that id; nothing but the refusal
    stands between it and a silent replacement.

    It used to be pinned as a side effect of ``FakeObserver`` *deriving* stable ids,
    which is the divergence from ``ModelBackedObserver`` that #736 closed. So the
    collision is scripted here instead — ``ObservedBelief.record_id`` names the id
    both runs propose, which is a producer that derives, stated as one. The rule
    keeps its test and the fake stops being the reason it has one.
    """
    scripted = [ObservedBelief(content="a belief worth holding", record_id="collides")]
    harness = Harness(observer=FakeObserver(scripted))
    conversation = await harness.conversation_with(2)

    await harness.stage.observe(conversation)

    # Fresh turns, because the first pass advanced the watermark past the two it read
    # and a second pass over nothing reaches no producer at all (ADR-0212 §3, §5).
    # What is under test is the *refusal*, so the pass has to get as far as proposing.
    await harness.append_turns(conversation, 2)

    with pytest.raises(MemoryStoreConflictError):
        await harness.stage.observe(conversation)


async def test_an_unknown_conversation_is_refused_rather_than_silently_empty() -> None:
    """A typo or a stale id is loud, as the store's own contract makes it (ADR-0074 §1)."""
    harness = Harness()
    await harness.conversation_with(1)
    with pytest.raises(UnknownConversationError):
        await harness.stage.observe("no-such-conversation")


async def test_the_batch_is_bounded_by_the_configured_size() -> None:
    """The window is the *most recent* ``batch_size`` turns, not the whole conversation."""
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_with(6)

    report = await harness.stage.observe(conversation)

    assert report.episodes_read == 3
    turns = await harness.conversations.turns(conversation)
    batch = harness.fake.batches[-1]
    assert [episode.id for episode in batch] == [turn.episode_id for turn in turns[-3:]]


async def test_a_turn_whose_episode_never_landed_is_skipped_without_backfilling() -> None:
    """A gap shortens the batch; it never reaches further back (ADR-0074 §5, §9.7).

    Backfilling would make the window's *span* depend on how many gaps it contains,
    so two runs over one conversation would read different stretches of it.
    """
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_with(4, captured=2)

    report = await harness.stage.observe(conversation)

    assert report.episodes_read == 2  # one short: the window's third turn has no episode
    assert report.route == ROUTE  # it still ran
    assert harness.fake.call_count == 1


async def test_a_window_where_no_episode_resolves_reaches_no_model_at_all() -> None:
    """No provider is called, and the report names **no** route (§9.7).

    Naming one would claim a read that never happened, which is the one thing §3's
    route reporting exists to make truthful.
    """
    harness = Harness()
    conversation = await harness.conversation_with(3, captured=0)

    report = await harness.stage.observe(conversation)

    assert report.conversation_id == conversation
    assert report.route is None
    assert report.episodes_read == 0
    assert report.proposals == ()
    assert report.discarded == 0
    assert harness.fake.call_count == 0


# --- the write path, ruling by ruling (ADR-0077 §4) ---------------------


async def test_every_proposal_goes_through_the_write_path_and_is_reported() -> None:
    """Accepted proposals are stored, and each is paired with the ruling it got."""
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content="the user prefers metric units")])
    )
    conversation = await harness.conversation_with(2)

    report = await harness.stage.observe(conversation)

    assert len(report.proposals) == 1
    entry = report.proposals[0]
    assert entry.content == "the user prefers metric units"
    assert entry.kind is MemoryKind.SEMANTIC
    assert entry.step is MemorySource.OBSERVED
    assert entry.confidence < 1.0
    assert entry.evidence_count >= 1
    assert entry.decision is LearnDecision.STORED
    assert entry.record_id is not None
    assert report.stored == 1
    # The id the report names is the one the inspection surface will list.
    assert await harness.memory.get(entry.record_id) is not None


async def test_the_stage_rules_on_nothing_and_relays_the_policys_reason() -> None:
    """A rejection is reported as a rejection, with the gate's own words (§4)."""
    harness = Harness(policy=FakeMemoryPolicy(MemoryDecisionKind.REJECT))
    conversation = await harness.conversation_with(2)

    report = await harness.stage.observe(conversation)

    assert report.proposals
    assert all(entry.decision is LearnDecision.REJECTED for entry in report.proposals)
    assert all(entry.record_id is None for entry in report.proposals)
    assert all(entry.reason for entry in report.proposals)
    assert report.stored == 0


async def test_a_deferral_is_reported_with_the_candidate_it_is_about() -> None:
    """``ASK_USER`` writes nothing and is **reported**, not dropped (§4, #423).

    The visibility interim: nothing persists a deferred proposal, so what the report
    carries is all there is — and a bare ruling with a ``None`` record id would show
    the user nothing to act on. The candidate's content, its citation count and the
    policy's reason are the whole point.
    """
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content="the user dislikes early meetings")]),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ASK_USER),
    )
    conversation = await harness.conversation_with(2)

    report = await harness.stage.observe(conversation)

    assert len(report.proposals) == 1
    deferred = report.proposals[0]
    assert deferred.decision is LearnDecision.DEFERRED
    assert deferred.record_id is None
    assert deferred.content == "the user dislikes early meetings"
    assert deferred.evidence_count >= 1
    assert deferred.reason  # the policy's own words, not a placeholder
    # Visible, not persisted: nothing about the deferral reached the store. The
    # episodes it was distilled from are still there, so the assertion is about the
    # *belief* kinds — an observer never proposes an episode (ADR-0077 §2).
    assert await harness.memory.list_beliefs(kinds=[MemoryKind.SEMANTIC]) == []


async def test_the_producers_two_counts_are_relayed_unchanged() -> None:
    """A degradation the producer reports reaches the *user-facing* report (§9.7).

    A stage that dropped them would re-create the silence ADR-0077 §4 refuses: "no
    beliefs" and "ten entries, none usable" would look identical.
    """
    harness = Harness(
        observer=FakeObserver(
            [ObservedBelief(content="one"), ObservedBelief(content="two")],
            max_proposals=1,
            discarded_unusable=3,
        )
    )
    conversation = await harness.conversation_with(2)

    report = await harness.stage.observe(conversation)

    assert report.discarded_unusable == 3
    assert report.discarded_over_limit == 1
    assert report.dropped_unsupported == 0
    assert report.discarded == 4


async def test_a_model_failure_ends_the_pass_rather_than_reporting_no_beliefs() -> None:
    """The user asked for observation and it did not happen (§4, ADR-0022 §3)."""
    harness = Harness(observer=_FailingObserver())
    conversation = await harness.conversation_with(2)

    with pytest.raises(ModelError):
        await harness.stage.observe(conversation)


async def test_a_writer_failure_on_the_second_of_three_leaves_the_first_stored() -> None:
    """The indeterminate partial write, pinned as ratified behaviour (§4, ADR-0022 §4).

    No partial-result transport is invented: the operation raises, an unknown prefix
    is already stored, and ``beliefs``/``forget`` are the recovery path. A later
    reader finds this in the suite rather than mistaking it for a bug.
    """
    harness = Harness(
        observer=FakeObserver(
            [
                ObservedBelief(content="first", record_id="rec-1"),
                ObservedBelief(content="second", record_id="rec-2"),
                ObservedBelief(content="third", record_id="rec-3"),
            ]
        )
    )
    harness.swap_writer(_FailingWriter(harness.real_writer, fail_on=2))
    conversation = await harness.conversation_with(2)

    with pytest.raises(MemoryStoreError):
        await harness.stage.observe(conversation)

    assert await harness.memory.get("rec-1") is not None
    assert await harness.memory.get("rec-3") is None


# --- the race-versus-bug discrimination (ADR-0077 §5) -------------------


async def _batch_ids(harness: Harness, conversation_id: str) -> tuple[str, ...]:
    """The episode ids the stage will select for ``conversation_id``."""
    turns = await harness.conversations.turns(conversation_id)
    return tuple(turn.episode_id for turn in turns)


async def test_an_episode_that_expires_mid_batch_drops_one_proposal_and_keeps_the_rest() -> None:
    """Every unresolved id inside the batch is the race: drop, count, carry on (§5).

    The negative assertion matters as much as the positive one — an implementation
    treating the refusal as a fault aborts a batch that was working, on nothing worse
    than a retention horizon doing its job.
    """
    harness = Harness(
        observer=FakeObserver(
            [
                ObservedBelief(content="first", record_id="rec-1"),
                ObservedBelief(content="second", record_id="rec-2"),
                ObservedBelief(content="third", record_id="rec-3"),
            ]
        )
    )
    conversation = await harness.conversation_with(2)
    selected = await _batch_ids(harness, conversation)
    harness.swap_writer(_RacingWriter(harness.real_writer, unresolved={"rec-2": (selected[0],)}))

    report = await harness.stage.observe(conversation)

    assert report.dropped_unsupported == 1
    assert len(report.proposals) == 3  # the drop is reported, not omitted
    dropped = next(entry for entry in report.proposals if entry.content == "second")
    assert dropped.decision is None
    assert dropped.record_id is None
    assert "went away" in dropped.reason
    # The other two really landed: the batch was not aborted.
    assert await harness.memory.get("rec-1") is not None
    assert await harness.memory.get("rec-3") is not None


async def test_a_citation_the_batch_never_contained_propagates_as_a_producer_fault() -> None:
    """An observer citing an id it was never handed is a bug, not a race (§5)."""
    harness = Harness(observer=FakeObserver([ObservedBelief(content="first", record_id="rec-1")]))
    conversation = await harness.conversation_with(2)
    harness.swap_writer(
        _RacingWriter(harness.real_writer, unresolved={"rec-1": ("conv:elsewhere#1",)})
    )

    with pytest.raises(UnresolvedEvidenceError):
        await harness.stage.observe(conversation)


async def test_a_fault_accompanied_by_an_expiry_is_still_a_fault() -> None:
    """The quantifier is "every", deliberately (§5).

    An implementation that catches ``UnresolvedEvidenceError`` without checking the
    batch passes the expiry case above and hides a producer bug forever; one that
    checked "any" rather than "every" would bury this fault under the race that
    happened to accompany it.
    """
    harness = Harness(observer=FakeObserver([ObservedBelief(content="first", record_id="rec-1")]))
    conversation = await harness.conversation_with(2)
    selected = await _batch_ids(harness, conversation)
    harness.swap_writer(
        _RacingWriter(harness.real_writer, unresolved={"rec-1": (selected[0], "conv:elsewhere#1")})
    )

    with pytest.raises(UnresolvedEvidenceError):
        await harness.stage.observe(conversation)


async def test_a_refusal_naming_no_ids_at_all_propagates() -> None:
    """Nothing identifies it as the race, so it is not swallowed as one (§5).

    "Every id is in the batch" is vacuously true of no ids, and reading the empty
    quantifier that way would swallow exactly the fault the discrimination exists to
    surface.
    """
    harness = Harness(observer=FakeObserver([ObservedBelief(content="first", record_id="rec-1")]))
    conversation = await harness.conversation_with(2)
    harness.swap_writer(_RacingWriter(harness.real_writer, unresolved={"rec-1": ()}))

    with pytest.raises(UnresolvedEvidenceError):
        await harness.stage.observe(conversation)


# --- re-observation is safe without a cursor (ADR-0077 §8) --------------


async def test_a_second_pass_over_the_same_page_reinforces_rather_than_duplicating() -> None:
    """ADR-0077 §8's fold, end to end, over the page a failed advance left behind.

    Two things at once, and they belong together. **ADR-0212 §6**: a pass that raises
    before its advance attempt moves the watermark by nothing, so the whole page is
    re-read by the next pass — never narrowed to "the turns whose proposals were not
    ruled". And **ADR-0077 §8**: that repetition is safe by the *fold* and not by the
    watermark, which only makes it rare. An implementation that leaned on the cursor
    for correctness would pass every other case here and fail this one.

    Scripted, because the property under test is the fold, not the model: an observer
    free to answer differently would make the assertion about the provider.
    """
    belief = "the user prefers metric units"
    # One observer across both passes, minting a fresh id each time exactly as a real
    # producer does (#736, ADR-0047 §2). Re-using the first id would make the second
    # write an upsert and hide whether the *fold* happened at all.
    minted = iter(["rec-1", "rec-2"])
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content=belief)], id_factory=lambda: next(minted)),
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
    )
    conversation = await harness.conversation_with(2)
    harness.conversations.advance_raises = True

    with pytest.raises(ConversationStoreError):
        await harness.stage.observe(conversation)

    stored = await harness.memory.get("rec-1")
    assert stored is not None
    before = stored.provenance.confidence
    assert await harness.watermark(conversation) is None, (
        "a pass whose advance did not commit leaves the watermark exactly as it was"
    )

    harness.conversations.advance_raises = False
    second = await harness.stage.observe(conversation)

    assert harness.fake.batches[-1] == harness.fake.batches[-2], (
        "the whole page is re-read, not the turns whose proposals were not ruled"
    )
    assert len(second.proposals) == 1
    assert second.proposals[0].decision is LearnDecision.REINFORCED
    # Folded into the existing record rather than written as a second one.
    assert second.proposals[0].record_id == "rec-1"
    assert await harness.memory.get("rec-2") is None
    after = await harness.memory.get("rec-1")
    assert after is not None
    assert after.provenance.confidence == before  # the same evidence scores the same
    assert await harness.watermark(conversation) == 2


# --- the observation watermark: selection, advance, failure (ADR-0212) ------


def _ordinals(batch: Sequence[EpisodicMemory]) -> list[int]:
    """The turn ordinals a batch of episodes came from.

    The episode id is derived from the conversation and the ordinal (ADR-0074 §3),
    so the batch says which *turns* the pass read — which is what every case below
    is actually about, and what an assertion on opaque ids would not show.
    """
    return [int(episode.id.rsplit(":", 1)[1]) for episode in batch]


async def test_a_first_pass_reads_the_tail_and_records_its_highest_ordinal() -> None:
    """§4: a conversation with no watermark starts at its tail, not at its first turn.

    And §4's cost is pinned beside the rule rather than left to be discovered: the
    turns below that first window stay below the first watermark recorded and are
    never selected again, however long the prefix is. The watermark asserts nothing
    about them (§1's second clause), which is why this is a pinned behaviour and not
    a defect.
    """
    harness = Harness(batch_size=2)
    conversation = await harness.conversation_with(5)

    report = await harness.stage.observe(conversation)

    assert _ordinals(harness.fake.batches[-1]) == [4, 5]
    assert report.episodes_read == 2
    assert harness.conversations.advances == [(conversation, 5)]
    assert await harness.watermark(conversation) == 5

    assert (await harness.stage.observe(conversation)).episodes_read == 0
    assert harness.fake.call_count == 1, "turns 1-3 are below the window and stay there"


async def test_a_named_conversation_with_nothing_above_its_watermark_makes_no_advance() -> None:
    """§5: a pass that read no turns makes **no** attempt and writes nothing.

    Asserted on the **store** and not only on the report, which is what §8 asks for:
    there is no ordinal for such a pass to name, ``None`` is not one, and
    ``record_observed`` refuses anything below the first ordinal before any I/O — so
    an implementation that "advanced to where it already was" would be making a call
    the contract has nothing for it to pass.

    This is also the named consequence of the whole decision on the CLI path:
    ``assistant observe <id>`` run twice does something the first time and nothing
    the second (§3). A deliberate re-observation is issue #1789 and is not this.
    """
    harness = Harness()
    conversation = await harness.conversation_with(2)
    await harness.stage.observe(conversation)
    harness.conversations.advances.clear()

    report = await harness.stage.observe(conversation)

    assert report == ObservationReport(conversation_id=conversation)
    assert harness.conversations.advances == []
    assert harness.fake.call_count == 1


async def test_a_pass_with_no_candidate_at_all_makes_no_advance() -> None:
    """§3, §5: no candidate means no turns read, no model called, nothing written."""
    harness = Harness()
    conversation = await harness.conversation_with(2)
    await harness.conversations.start()  # a conversation with no turns is no candidate
    await harness.stage.observe(conversation)
    harness.conversations.advances.clear()

    report = await harness.stage.observe()

    assert report == ObservationReport()
    assert report.conversation_id is None
    assert harness.conversations.advances == []
    assert harness.fake.call_count == 1


async def test_a_page_that_resolves_to_nothing_advances_past_it_in_one_pass() -> None:
    """§5's second branch, and the stall it exists to prevent.

    #1737 item 3 words the rule as "the cursor advances to the last turn *handed
    over*", and a page that hands nothing over would then never move it: the next
    pass reads the same dead page and does not move it either. A conversation whose
    unobserved turns have all expired — the ordinary state of one reached after a
    long idle period — would be a permanent candidate re-reading one dead page for
    as long as it lives.

    **In one pass, not one turn at a time**, which is what the single advance to the
    page's highest ordinal pins. It costs nothing: the page reached no observer at
    all, so passing over it passes over nothing that was ever readable.
    """
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_of([], turns=3)

    report = await harness.stage.observe(conversation)

    assert harness.fake.call_count == 0
    assert report == ObservationReport(conversation_id=conversation)
    assert harness.conversations.advances == [(conversation, 3)]
    assert await harness.watermark(conversation) == 3


async def test_a_page_whose_last_turn_is_unresolvable_advances_to_the_highest_below_it() -> None:
    """§5: the position is the highest turn the pass actually handed over.

    A trailing gap gets a second reading, and the reason is that it is the one gap
    that is ordinarily still **in flight**: where captures of one conversation are
    sequential, an in-flight turn is always the newest, because a later append
    happens after the earlier capture returned. So the common case is covered by the
    rule itself rather than by a special case for it.
    """
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_of([1, 2], turns=3)

    await harness.stage.observe(conversation)

    assert _ordinals(harness.fake.batches[-1]) == [1, 2]
    assert await harness.watermark(conversation) == 2

    # The next pass reads that turn alone. Its episode still has not landed, so the
    # page resolves to nothing and the second branch advances past it.
    second = await harness.stage.observe(conversation)

    assert second.episodes_read == 0
    assert harness.fake.call_count == 1
    assert await harness.watermark(conversation) == 3


async def test_an_episode_landing_between_two_passes_is_observed_on_the_second() -> None:
    """The other half of the trailing gap: the late capture is not lost (§5).

    The pair matters. Advancing past an unresolved trailing turn unconditionally
    would lose a turn whose episode was merely slow; stopping below it for ever would
    be the stall the case above pins. The rule reads it once more, and *then* moves
    on.
    """
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_of([1, 2], turns=3)
    await harness.stage.observe(conversation)

    await harness.land(conversation, 3)
    second = await harness.stage.observe(conversation)

    assert _ordinals(harness.fake.batches[-1]) == [3]
    assert second.episodes_read == 1
    assert await harness.watermark(conversation) == 3


async def test_an_unresolvable_turn_in_the_middle_of_a_page_is_passed_over() -> None:
    """§5's accepted residual, pinned as a decision rather than found as a defect.

    An interior gap is **not** given a second reading. A rule that gave every gap one
    would have to stop the watermark below the lowest unresolved turn, which re-reads
    that page's resolved turns above the gap on every following pass until the gap
    clears, and needs a further fallback for a page whose lowest turn is the gap — and
    another again for a page carrying two. The coverage that buys is the interior
    in-flight turn alone, which takes two overlapping captures of one conversation.

    So a later lane that wants the other rule has to change this test deliberately.
    The loss is one turn's *distillation*: the episode itself is unaffected, stays
    readable by retrieval, and expires on its own horizon.
    """
    harness = Harness(batch_size=3)
    conversation = await harness.conversation_of([1, 3], turns=3)

    await harness.stage.observe(conversation)

    assert _ordinals(harness.fake.batches[-1]) == [1, 3]
    assert await harness.watermark(conversation) == 3

    # Even once turn 2's episode lands, it is behind the watermark and is not read.
    await harness.land(conversation, 2)
    assert (await harness.stage.observe(conversation)).episodes_read == 0
    assert harness.fake.call_count == 1


async def test_a_full_page_behaves_exactly_as_a_short_one_does() -> None:
    """§5: no rule depends on the page's length, only on its ordinals.

    The position is "the highest ordinal in the page whose episode resolved", and an
    implementation computing it from ``len(page)`` — or treating a full page as
    "there is more, so stop short" — passes every case above and fails this one.
    """
    exact = Harness(batch_size=2)
    full = await exact.conversation_with(2)
    short = Harness(batch_size=2)
    partial = await short.conversation_with(1)

    await exact.stage.observe(full)
    await short.stage.observe(partial)

    assert exact.conversations.advances == [(full, 2)]
    assert short.conversations.advances == [(partial, 1)]
    assert await exact.watermark(full) == 2
    assert await short.watermark(partial) == 1


@pytest.mark.parametrize("earlier_stamps_first", [True, False])
async def test_two_overlapping_passes_leave_the_higher_position_standing(
    *, earlier_stamps_first: bool
) -> None:
    """§5: overlap safety rests on ``record_observed``'s monotonicity and nothing else.

    Two passes over one conversation may overlap and neither the store nor the
    decision serialises them. Each computes its position from **its own** page and
    its own resolution of that page's episodes, and the two may legitimately differ —
    here because turn 3's episode lands between the two page reads. Whichever order
    the stamps arrive in, the higher position stands and the lower performs nothing.

    Written end to end over two interleaved passes rather than as two store calls in
    a row, because what is under test is the stage and the store composing: a stage
    that read the watermark back to "confirm" its own advance, or retried it, would
    satisfy a store-level case and fail here.
    """
    belief = "the user is training for a marathon"
    minted = iter(["rec-1", "rec-2"])
    earlier_gate, later_gate = ObservationGate(), ObservationGate()
    harness = Harness(
        observer=FakeObserver(
            [ObservedBelief(content=belief)], id_factory=lambda: next(minted), gate=earlier_gate
        ),
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
    )
    conversation = await harness.conversation_of([1, 2], turns=3)
    later = harness.stage_over(
        FakeObserver(
            [ObservedBelief(content=belief)], id_factory=lambda: next(minted), gate=later_gate
        )
    )

    # The earlier pass reads the page while turn 3 is still in flight, and is held
    # before it can advance; the later one reads the same page once it has landed.
    earlier_pass = asyncio.create_task(harness.stage.observe(conversation))
    await earlier_gate.reached()
    await harness.land(conversation, 3)
    later_pass = asyncio.create_task(later.observe(conversation))
    await later_gate.reached()

    if earlier_stamps_first:
        earlier_gate.release()
        await earlier_pass
        later_gate.release()
        await later_pass
    else:
        later_gate.release()
        await later_pass
        earlier_gate.release()
        await earlier_pass

    assert sorted(harness.conversations.advances) == [(conversation, 2), (conversation, 3)], (
        "each pass names the position **it** read, and neither is recomputed"
    )
    assert await harness.watermark(conversation) == 3, (
        "the higher of the two positions stands whichever order the stamps arrived in"
    )
    landed = {record.id for record in await harness.memory.export()} & {"rec-1", "rec-2"}
    assert len(landed) == 1, (
        "the duplicate proposals fold rather than writing a second record (ADR-0077 §8)"
    )


async def test_a_pass_cancelled_after_its_advance_commits_leaves_the_stamped_watermark() -> None:
    """§6: the commit-ambiguous case, in the half that is assertable.

    ADR-0060's cancellation clause and ADR-0054's shield make this the real shape
    rather than a contrivance: a store whose write runs in a worker thread can commit
    and then have the awaiting task cancelled before the call returns. **Both
    outcomes are safe and neither is a defect** — if the stamp landed, every proposal
    of that pass had already been ruled, so the position records work that was done.

    What §6 forbids is the machinery that cannot tell the two apart anyway: no
    compensating write, no re-read of the watermark to "confirm" it, and no retry of
    the attempt inside the same pass. Each would be a second write to the watermark,
    which §5 forbids — so the assertion is that **exactly one** advance was ever
    asked for.
    """
    harness = Harness()
    conversation = await harness.conversation_with(2)
    harness.conversations.cancel_after_advance = True

    outcome = await asyncio.gather(harness.stage.observe(conversation), return_exceptions=True)

    assert isinstance(outcome[0], asyncio.CancelledError)
    assert harness.conversations.advances == [(conversation, 2)], "no compensating write"
    assert await harness.watermark(conversation) == 2

    harness.conversations.cancel_after_advance = False
    assert (await harness.stage.observe(conversation)).episodes_read == 0
    await harness.append_turns(conversation, 1)
    resumed = await harness.stage.observe(conversation)

    assert _ordinals(harness.fake.batches[-1]) == [3], (
        "the next pass resumes above the stamped position rather than re-reading the page"
    )
    assert resumed.episodes_read == 1


async def test_a_pass_that_raises_in_the_write_path_advances_nothing() -> None:
    """§6: a pass that raises **before** its attempt moves the watermark by nothing.

    There is no partial advance within a pass, and the re-read is never narrowed to
    "the turns whose proposals were not ruled" — which is what #1737 item 4 asks for
    and §6 refuses, because a proposal may cite several turns and a turn may be cited
    by none, so that set does not name a *position* in the ordinal order at all.
    """
    # A minting observer, as the producer it doubles is (#736): the re-read pass
    # proposes the same content at fresh ids, which is the production shape. Scripted
    # ids on both passes would make the second one collide with the first's record
    # and fail on ADR-0108 §2's own-id refusal, which is a different rule.
    minted = iter(["rec-1", "rec-2", "rec-3", "rec-4"])
    harness = Harness(
        observer=FakeObserver(
            [ObservedBelief(content="first"), ObservedBelief(content="second")],
            id_factory=lambda: next(minted),
        )
    )
    harness.swap_writer(_FailingWriter(harness.real_writer, fail_on=2))
    conversation = await harness.conversation_with(2)

    with pytest.raises(MemoryStoreError):
        await harness.stage.observe(conversation)

    assert await harness.memory.get("rec-1") is not None, "the first proposal was ruled"
    assert harness.conversations.advances == [], "and the watermark moved by nothing"
    assert await harness.watermark(conversation) is None

    harness.swap_writer(harness.real_writer)
    await harness.stage.observe(conversation)

    assert harness.fake.batches[-1] == harness.fake.batches[-2], "the whole page is re-read"


async def test_a_conversation_deleted_between_the_page_read_and_the_advance() -> None:
    """§6: the deletion race is the one page never re-read, and none is owed.

    ADR-0074 §8 working rather than a page lost. The pass reads its page, the user
    deletes the conversation, and ``record_observed`` then refuses — a refusal and
    not a commit, so the watermark is untouched; and by then the conversation has
    left the candidate listing, so no later pass can re-read what the failed one
    read. A belief the aborted pass would have proposed from those turns is precisely
    what a deletion is for.

    The exception leaves **this pass**. What a multi-pass *run* does with it is
    ADR-0218 §9's — it catches it, drops that candidate and carries on — and that is
    the trigger lane's, not this one's.
    """
    harness = Harness()
    conversation = await harness.conversation_with(2)
    harness.conversations.stamp_before_advance = True

    with pytest.raises(UnknownConversationError):
        await harness.stage.observe(conversation)

    assert harness.conversations.advances == [(conversation, 2)]
    assert harness.conversations.raw_watermark(conversation) is None
    assert await harness.conversations.get(conversation) is None
    assert await harness.conversations.conversations_with_unobserved_turns() == []


async def test_under_a_stopped_clock_a_busy_candidate_stays_first() -> None:
    """§3's accepted behaviour, pinned so a later lane changes the order deliberately.

    The candidate order starves nothing **where the clock advances monotonically**,
    and this project never promises that it does (``core/clock.py``). A stopped or
    stepped-back clock can leave a busy conversation's ``last_active_at`` at or below
    an idle one's, and where the tie is broken by an ``id`` that also sorts first the
    busy one is served ahead of the idle one indefinitely.

    That is **accepted and named**, not closed: closing it would take a durable
    service-order position — a second cursor with its own upgrade discipline and its
    own ``core`` surface — bought against a clock adjustment rather than against
    anything the walk does.
    """
    ids = iter(["busy", "idle"])
    harness = Harness(now=lambda: AT, new_id=lambda: next(ids))
    busy = await harness.conversation_with(2)
    idle = await harness.conversation_with(2)

    first = await harness.stage.observe()
    await harness.append_turns(busy, 2)
    await harness.conversations.mark_active(busy)
    second = await harness.stage.observe()

    assert (busy, idle) == ("busy", "idle")
    assert first.conversation_id == busy
    assert second.conversation_id == busy
    assert await harness.watermark(idle) is None, "the idle conversation is not reached"


async def test_a_watermark_the_store_discards_is_recovered_by_the_next_pass() -> None:
    """§7 end to end: a discarded watermark is read as absent, and §4 then governs.

    Written as one scenario rather than as two, because the failure it guards against
    is an implementation that coerces the value on one read and filters it wrongly on
    another — which would leave the conversation permanently unreachable: absent from
    the candidate listing because its stored watermark is above every turn, and
    unstampable because nothing selects it. The recovery is a *tail* read and not a
    walk from the first turn, since a discarded watermark is an absent one (§4).
    """
    harness = Harness(batch_size=2)
    conversation = await harness.conversation_with(3)
    harness.conversations.plant_watermark(conversation, 99)

    candidates = await harness.conversations.conversations_with_unobserved_turns()
    report = await harness.stage.observe(conversation)

    assert [one.id for one in candidates] == [conversation]
    assert [one.observed_through for one in candidates] == [None]
    assert _ordinals(harness.fake.batches[-1]) == [2, 3]
    assert report.episodes_read == 2
    assert await harness.watermark(conversation) == 3


# --- construction guards -------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, 2**63])
def test_a_batch_size_the_conversation_store_would_refuse_is_refused_here(bad: int) -> None:
    """Out of range is a ``ValueError`` at construction, not at the first observation."""
    harness = Harness()
    with pytest.raises(ValueError, match="batch_size"):
        ObservationStage(
            observer=harness.observer,
            conversations=harness.conversations,
            memory=harness.memory,
            writes=harness.writes,
            batch_size=bad,
            route=ROUTE,
        )


@pytest.mark.parametrize("bad", [True, 1.5, "2"])
def test_a_non_integer_batch_size_is_a_type_error(bad: object) -> None:
    """A bool, float or string bound reaches the store and fails far from the mistake."""
    harness = Harness()
    with pytest.raises(TypeError, match="must be an integer"):
        ObservationStage(
            observer=harness.observer,
            conversations=harness.conversations,
            memory=harness.memory,
            writes=harness.writes,
            batch_size=bad,  # type: ignore[arg-type]  # the point of the test
            route=ROUTE,
        )


async def test_a_real_expiry_between_selection_and_the_write_drops_only_that_proposal() -> None:
    """ADR-0077 §5's race, driven end to end through the **canonical** writer.

    The scripted double above pins the stage's discrimination in isolation; this pins
    it against the write path that actually ships the refusal. The episode is
    destroyed while ``observe`` is held at its first ``await`` — after the batch was
    selected and before any proposal is ingested — which is precisely the window §5
    describes: an episode is selected while live and the model call suspends for a
    round trip.

    The negative half carries as much weight as the positive: an implementation
    treating ``UnresolvedEvidenceError`` as a fault would abort a batch that was
    working, on nothing worse than a retention horizon doing its job.
    """
    gate = ObservationGate()
    harness = Harness(
        observer=FakeObserver(
            [
                ObservedBelief(content="first", start=0, record_id="rec-1"),
                ObservedBelief(content="second", start=1, record_id="rec-2"),
                ObservedBelief(content="third", start=2, record_id="rec-3"),
            ],
            gate=gate,
        )
    )
    conversation = await harness.conversation_with(3)
    selected = await _batch_ids(harness, conversation)

    running = asyncio.ensure_future(harness.stage.observe(conversation))
    await gate.reached()
    # The evidence goes away *under* the observation, exactly as an expiry or a
    # `forget-conversation` would. The batch is already chosen; the writes have not
    # begun.
    assert await harness.memory.delete(selected[1]) is True
    gate.release()
    report = await running

    assert report.dropped_unsupported == 1
    dropped = next(entry for entry in report.proposals if entry.content == "second")
    assert dropped.decision is None  # no ruling was sought, so none is claimed
    assert dropped.record_id is None
    # The batch was not aborted: the two proposals whose evidence survived landed.
    assert await harness.memory.get("rec-1") is not None
    assert await harness.memory.get("rec-3") is not None
    assert await harness.memory.get("rec-2") is None
    assert report.stored == 2


# --- the citations travel with the proposal (ADR-0077 §4) ---------------


async def test_a_deferred_proposal_carries_the_episodes_it_cites() -> None:
    """ADR-0077 §4's visibility interim, in full: content, **citations**, reason.

    Nothing persists a deferred proposal, so the report is the only place its warrant
    is ever shown. A count would be the last word on a belief the user is being asked
    to act on.
    """
    harness = Harness(
        observer=FakeObserver(
            [ObservedBelief(content="the user works from Lisbon", supports=2, step=INFERRED)]
        ),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ASK_USER),
    )
    conversation = await harness.conversation_with(2)
    turns = await harness.conversations.turns(conversation)
    cited = [await harness.memory.get(turn.episode_id) for turn in turns]

    report = await harness.stage.observe(conversation)

    deferred = report.proposals[0]
    assert deferred.decision is LearnDecision.DEFERRED
    assert deferred.evidence_count == 2
    assert [item.content for item in deferred.evidence] == [
        episode.content for episode in cited if episode is not None
    ]
    assert all(item.lost is False for item in deferred.evidence)


async def test_a_dropped_proposal_tombstones_the_citation_that_went_away() -> None:
    """The evidence that vanished renders as gone, not as the copy still in the batch.

    Echoing the batch's copy would print back a record the store no longer holds —
    content the user may have destroyed a moment earlier — while dropping the entry
    would hide a citation, which ADR-0073 §4's floor forbids.
    """
    gate = ObservationGate()
    harness = Harness(
        observer=FakeObserver(
            [ObservedBelief(content="a belief", supports=2, step=INFERRED, record_id="rec-1")],
            gate=gate,
        )
    )
    conversation = await harness.conversation_with(2)
    selected = await _batch_ids(harness, conversation)

    running = asyncio.ensure_future(harness.stage.observe(conversation))
    await gate.reached()
    assert await harness.memory.delete(selected[0]) is True
    gate.release()
    report = await running

    assert report.dropped_unsupported == 1
    dropped = report.proposals[0]
    assert dropped.decision is None
    assert dropped.evidence_count == 2
    assert dropped.evidence[0].lost is True  # the one that went away
    assert dropped.evidence[0].content is None
    assert dropped.evidence[1].lost is False  # the one that survived, still readable


async def test_a_proposal_citing_a_live_episode_outside_the_batch_is_refused() -> None:
    """The scope limit, closed on the half the writer cannot see (ADR-0077 §1, §5).

    A foreign id that happens to name a **live** record sails past the writer's
    evidence check — it resolves — so only this stage can catch it. Left unchecked it
    would be stored as a warrant and rendered as evidence, pulling content out of a
    conversation the user never asked to observe: exactly the scope property §1 makes
    a property of the seam rather than of one implementation's good behaviour.
    """
    harness = Harness()
    observed = await harness.conversation_with(2)
    elsewhere = await harness.conversation_with(1)
    foreign = (await _batch_ids(harness, elsewhere))[0]
    assert await harness.memory.get(foreign) is not None  # it really does resolve
    harness.stage._observer = _CitingObserver(foreign)

    with pytest.raises(ValueError, match="never handed"):
        await harness.stage.observe(observed)


async def test_nothing_is_written_when_any_proposal_cites_outside_the_batch() -> None:
    """Checked over the whole return value **before** anything is ingested.

    The check needs no store access, so interleaving it with the writes would buy
    nothing and risk a partial write for a fault that was knowable up front. A good
    proposal ahead of the offending one must therefore not have landed.
    """
    harness = Harness()
    observed = await harness.conversation_with(2)
    elsewhere = await harness.conversation_with(1)
    foreign = (await _batch_ids(harness, elsewhere))[0]
    harness.stage._observer = _CitingObserver(foreign, good_first=True)

    with pytest.raises(ValueError, match="never handed"):
        await harness.stage.observe(observed)

    assert await harness.memory.get("rec-good") is None
    assert await harness.memory.list_beliefs(kinds=[MemoryKind.SEMANTIC]) == []


class _CitingObserver:
    """An ``Observer`` that breaches §5's mapping rule, citing outside its batch.

    Hand-rolled rather than scripted through :class:`FakeObserver`, which cannot
    produce this shape by construction: it draws every citation from the batch it was
    handed, which is precisely the clause under test. A non-conforming observer is
    the only way to reach the stage's enforcement of it.
    """

    def __init__(self, foreign_id: str, *, good_first: bool = False) -> None:
        self._foreign = foreign_id
        self._good_first = good_first

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose one belief citing an id from outside ``episodes``."""
        proposals = []
        if self._good_first:
            proposals.append(_proposal_citing("rec-good", (episodes[0].id,)))
        proposals.append(_proposal_citing("rec-foreign", (self._foreign,)))
        return ObservationOutcome(proposals=tuple(proposals))


def _proposal_citing(record_id: str, evidence: tuple[str, ...]) -> MemoryUpdateProposal:
    """A well-formed derived proposal citing exactly ``evidence``."""
    return MemoryUpdateProposal(
        proposed=SemanticMemory(
            id=record_id,
            content=f"a belief at {record_id}",
            fact=f"a belief at {record_id}",
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.6, evidence=evidence, last_updated=AT
            ),
        ),
        rationale="the batch supports this",
    )


async def test_an_observed_deferral_against_a_full_queue_is_reported_and_raises_nothing() -> None:
    """ADR-0078 §7's refused branch, on the path that has nobody watching.

    "An observer proposal refused at the cap is reported to the observing stage and no
    further; what that stage's own result carries is ADR-0077's to decide, not this
    ADR's to specify from outside." So the report is **not** widened to carry the
    admission — and this pins both halves of that: the pass still reports the proposal
    and its deferred ruling, and nothing raises, so a full queue neither loses the
    observation nor turns it into an error.

    It is also the input the surface has to stay honest about: from a report that does
    not carry the admission, a parked question and a full queue look identical, so a
    line asserting "go answer this" would be false here (see the CLI's own case).
    """
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content="first", record_id="rec-1")]),
        policy=FakeMemoryPolicy(MemoryDecisionKind.ASK_USER),
    )
    # A cap of one, already spent by a question this pass did not raise.
    harness.deferrals = FakeDeferralStore(now=lambda: AT, queue_limit=1)
    harness.writes = MemoryWriteStage(writer=harness.writer, deferrals=harness.deferrals)
    harness.stage._writes = harness.writes
    filler = await harness.deferrals.defer(
        deferral_id="already-asked",
        proposal=MemoryUpdateProposal(
            proposed=EpisodicMemory(
                id="filler",
                content="something else entirely",
                occurred_at=AT,
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT
                ),
            ),
            rationale="a question that already holds the only slot",
        ),
        decision=MemoryDecision(kind=MemoryDecisionKind.ASK_USER, reason="fake: the user decides"),
    )
    assert filler.outcome is DeferralAdmissionOutcome.ADMITTED
    conversation = await harness.conversation_with(2)

    report = await harness.stage.observe(conversation)

    assert len(report.proposals) == 1, "the observation is reported, not lost"
    assert report.proposals[0].decision is LearnDecision.DEFERRED
    assert report.stored == 0
    assert len(await harness.deferrals.pending()) == 1, "the cap held; nothing new was parked"


# --- ADR-0204 §5: the derivation rule, over what the producer was supplied ----


def _episode_stamped(episode_id: str, *, supplied_withheld_content: bool) -> EpisodicMemory:
    """One captured turn, as capture writes it once ADR-0204 §2 stamps it."""
    return EpisodicMemory(
        id=episode_id,
        content=f"the user said something in {episode_id}",
        occurred_at=AT,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=AT,
            supplied_withheld_content=supplied_withheld_content,
        ),
    )


async def _conversation_of(harness: Harness, *stamps: bool) -> str:
    """A conversation whose turns carry ``stamps``, oldest first."""
    conversation = await harness.conversations.start()
    for stamped in stamps:
        turn = await harness.conversations.append(conversation.id, occurred_at=AT)
        await harness.memory.add(
            _episode_stamped(turn.episode_id, supplied_withheld_content=stamped)
        )
    return conversation.id


async def _only_belief(harness: Harness) -> SemanticMemory:
    """The one belief the run wrote, which is what its stamp is asserted about."""
    written = [one for one in await harness.memory.export() if isinstance(one, SemanticMemory)]
    assert len(written) == 1, "one scripted belief, one written record"
    return written[0]


async def test_a_belief_derived_from_a_stamped_episode_carries_the_stamp() -> None:
    """ADR-0204 §5's second clause, at the seam that derives beliefs from episodes.

    ADR-0074 §4 makes capture "the first producer into the derived band, arriving
    before the observer it exists to feed", so this stage is the second producer in
    that chain and the one §5's clause is written for.
    """
    harness = Harness(observer=FakeObserver([ObservedBelief(content="the user runs early")]))
    conversation = await _conversation_of(harness, True)

    await harness.stage.observe(conversation)

    assert (await _only_belief(harness)).provenance.supplied_withheld_content is True


async def test_the_disjunction_ranges_over_what_the_producer_received() -> None:
    """§8 case 12: over the batch supplied, never over the subset cited.

    The belief cites the unstamped episode and nothing else, so an implementation
    folding the field over ``Provenance.evidence`` passes case 11 and fails here —
    and its output reaches a channel of unbounded audience carrying a warrant the
    producer actually read. ``evidence`` is not the input set, and §5 says so in
    terms.
    """
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content="the user runs early", supports=1)])
    )
    # The batch reaches the producer oldest first and the belief cites its first
    # entry, so the stamped episode is seeded second — and the assertions below pin
    # that arrangement rather than trusting it.
    conversation = await _conversation_of(harness, False, True)

    await harness.stage.observe(conversation)

    batch = harness.fake.batches[0]
    assert len(batch) == 2
    assert batch[0].provenance.supplied_withheld_content is False
    assert batch[1].provenance.supplied_withheld_content is True
    belief = await _only_belief(harness)
    assert belief.provenance.evidence == (batch[0].id,), "it cited only the unstamped episode"
    assert belief.provenance.supplied_withheld_content is True


async def test_a_producer_supplied_nothing_stamped_emits_false() -> None:
    """§8 case 13: the direction that would otherwise stamp everything.

    Without this, an implementation writing ``True`` unconditionally passes both
    cases above and empties ADR-0199 §3's speakable set by a different route.
    """
    harness = Harness(observer=FakeObserver([ObservedBelief(content="the user runs early")]))
    conversation = await _conversation_of(harness, False, False)

    await harness.stage.observe(conversation)

    assert (await _only_belief(harness)).provenance.supplied_withheld_content is False


class _ClaimingObserver:
    """An ``Observer`` whose proposal claims ADR-0204 §1's field for itself.

    Hand-rolled rather than scripted through :class:`FakeObserver`, because the
    canonical fake deliberately offers no knob for it: a producer's value has no
    effect anywhere (ADR-0106 §3 read for this field), so a knob would advertise an
    input that is discarded. What is under test is precisely that discarding.
    """

    def __init__(self, *, claims: bool) -> None:
        self._claims = claims

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Propose one belief carrying the claim, citing the batch it was handed."""
        proposed = SemanticMemory(
            id="claimed",
            content="the user runs early",
            fact="the user runs early",
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.6,
                evidence=tuple(episode.id for episode in episodes),
                last_updated=AT,
                supplied_withheld_content=self._claims,
            ),
        )
        return ObservationOutcome(
            proposals=(MemoryUpdateProposal(proposed=proposed, rationale="the batch says so"),)
        )


async def test_the_stage_assigns_the_marker_over_the_producers_own_value() -> None:
    """ADR-0106 §3's discipline, applied to this field: assigned, never merged.

    A producer that claimed the stamp on a batch that held none would otherwise put
    a record beyond the spoken channel's reach on its own say-so, and a merge would
    leave that code path open. The stage computes the fact from the batch it
    selected and writes it over whatever arrived, so the producer never had the
    choice.
    """
    harness = Harness(observer=_ClaimingObserver(claims=True))
    conversation = await _conversation_of(harness, False)

    await harness.stage.observe(conversation)

    assert (await _only_belief(harness)).provenance.supplied_withheld_content is False


async def test_a_producer_that_forgets_the_marker_does_not_launder_the_warrant() -> None:
    """The other direction of the same clause, and the one that costs a disclosure.

    ADR-0106 §3's argument transfers whole: "the failure that matters is not a
    producer over-claiming taint but one omitting it, and nothing guarantees a field
    in a model's output".
    """
    harness = Harness(observer=_ClaimingObserver(claims=False))
    conversation = await _conversation_of(harness, True)

    await harness.stage.observe(conversation)

    assert (await _only_belief(harness)).provenance.supplied_withheld_content is True


# --- the scheduled run: when a conversation is due (ADR-0218) ----------------


async def test_quiet_is_decided_on_the_activity_instant_and_never_on_the_recorded_turn() -> None:
    """ADR-0218 §1, in both directions, because either alone passes for the wrong reason.

    ``last_active_at`` is "refreshed whenever a turn *begins*"; ``last_turn_at`` is
    set "by the append that writes a turn into the index". Between those two moments
    the user is mid-exchange, which is precisely the state a quiet window exists to
    stay out of — so measuring on the recorded turn "would call a conversation quiet
    while its next turn is in flight".

    The two conversations here are each other's mirror. ``ended`` was active an hour
    ago and its turns are stamped *now*: quiet on the ratified field, busy on the
    field that looks like it means the same thing. ``mid_exchange`` is the reverse.
    An implementation reading ``last_turn_at`` serves the second and skips the first,
    which is the exact inversion of what §1 rules — so each is asserted with the
    other absent, and neither run can pass by serving whatever it found.
    """
    ended = Harness(now=_Clock())
    quiet = await ended.conversation_stamped(active_at=AT, stamps=[RUN, RUN])

    ended_report = await ended.stage.run()

    assert ended_report.passes == 1
    assert ended.conversations.advances == [(quiet, 2)]

    mid = Harness(now=_Clock())
    busy = await mid.conversation_stamped(active_at=AT, stamps=[AT, AT])
    await mid.mark_active_at(busy, RUN)

    mid_report = await mid.stage.run()

    assert mid_report.passes == 0
    assert mid.conversations.advances == []
    assert mid.fake.call_count == 0


async def test_the_age_arm_is_decided_on_the_unobserved_page_s_first_turn() -> None:
    """ADR-0218 §2's span begins at the page's *oldest* turn, not its newest.

    "The question the age arm asks is 'has material been waiting too long', and the
    material is the turns above the watermark. […] Measuring on the *newest*
    unobserved turn would do the same thing one turn later. The oldest is the only
    one of the three that ages."

    Both conversations here hold the same two stamps in opposite orders, and neither
    is quiet or full — so the *only* thing that can separate them is which end of the
    page the arm reads. An implementation reading the last turn serves ``recent_first``
    and skips ``old_first``, which is the assertion pair below.
    """
    aging = Harness(now=_Clock())
    old_first = await aging.conversation_stamped(
        active_at=RUN, stamps=[RUN - timedelta(hours=3), RUN]
    )

    assert (await aging.stage.run()).passes == 1
    assert aging.conversations.advances == [(old_first, 2)]

    fresh = Harness(now=_Clock())
    await fresh.conversation_stamped(active_at=RUN, stamps=[RUN, RUN - timedelta(hours=3)])

    assert (await fresh.stage.run()).passes == 0
    assert fresh.conversations.advances == []


async def test_the_full_arm_fires_on_a_page_of_exactly_the_batch_size() -> None:
    """ADR-0218 §2's third arm: "a whole page is available to read", and no field of its own.

    §7 refuses the arm a threshold of its own — "its threshold is
    ``observation_batch_size``, because the condition it tests is exactly 'a whole
    page is available to read', and a second count would let the two disagree about
    what a page is" — so the boundary is asserted *at* the batch size and one turn
    below it, over a conversation that is neither quiet nor aged.
    """
    short = Harness(batch_size=3, now=_Clock())
    await short.conversation_stamped(active_at=RUN, stamps=[RUN, RUN])

    assert (await short.stage.run()).passes == 0
    assert short.conversations.advances == []

    whole = Harness(batch_size=3, now=_Clock())
    page = await whole.conversation_stamped(active_at=RUN, stamps=[RUN, RUN, RUN])

    report = await whole.stage.run()

    assert report.passes == 1
    assert report.episodes_read == 3
    assert whole.conversations.advances == [(page, 3)]


async def test_a_turn_stamped_ahead_of_the_run_s_clock_is_still_reached() -> None:
    """ADR-0218 §2's full arm is the one that rests on no instant at all.

    ``append`` takes ``occurred_at`` "from the caller's injected clock" and this
    project "never promises [the clock] is monotonic", so a turn stamped *ahead* of
    the store's clock "has an unobserved span whose age is negative and stays
    negative until the store's clock catches up". For a conversation that also never
    goes quiet the age arm would then be the only arm and would never fire.

    So the reach is asserted **deterministically and through the full arm alone**:
    the same conversation, at the same forward stamps and the same activity instant,
    is due at a whole page and not due one turn short. Nothing here waits for a clock
    to catch up, because ordinals are the store's own.
    """
    ahead = RUN + timedelta(hours=1)

    short = Harness(batch_size=3, now=_Clock())
    await short.conversation_stamped(active_at=RUN, stamps=[ahead, ahead])

    assert (await short.stage.run()).passes == 0

    whole = Harness(batch_size=3, now=_Clock())
    forward = await whole.conversation_stamped(active_at=RUN, stamps=[ahead, ahead, ahead])

    report = await whole.stage.run()

    assert report.passes == 1
    assert whole.conversations.advances == [(forward, 3)]


async def test_a_conversation_kept_out_of_quiet_by_turns_that_never_complete_is_due_on_no_arm() -> (
    None
):
    """ADR-0218 §2's residual, pinned as a recorded decision rather than a surprise.

    ``mark_active`` moves at the rate turns **begin** and the full arm advances at
    the rate they are **recorded**, so "a client that begins a turn inside every
    quiet window, each turn's work outlasting the window its beginning refreshed,
    stays out of quiet for as long as it keeps that up while adding rows more slowly
    than it adds activity. Turns that never complete are the limit of that."

    Such a conversation, holding one unobserved turn stamped ahead of the store's
    clock, "is quiet on no reading, aged on no reading and full on no reading". §2
    accepts and names that on four grounds — it needs three ordinary events
    suppressed at once, its duration is bounded by the size of the clock error, at
    most ``observation_batch_size - 1`` turns are *delayed* rather than lost, and
    both closures a reviewer would reach for are ruled out by ratified text. This
    case is what makes the acceptance visible: nothing is read, nothing is written,
    and the material stays exactly where it was.
    """
    harness = Harness(now=_Clock())
    stalled = await harness.conversation_stamped(active_at=AT, stamps=[RUN + timedelta(hours=1)])
    await harness.mark_active_at(stalled, RUN)

    report = await harness.stage.run()

    assert report == ObservationRunReport()
    assert harness.conversations.advances == []
    assert harness.fake.call_count == 0
    assert await harness.watermark(stalled) is None


async def test_a_run_takes_the_first_due_candidate_and_not_merely_the_first() -> None:
    """ADR-0218 §2's selection clause, which a "head of the listing" run fails.

    "The due test is evaluated by walking the candidate listing in ADR-0212 §3's
    order and taking the **first** candidate that is due." The head here is not due
    on any arm — recently active, one turn, stamped now — while the candidate behind
    it holds a whole page and is. A run that served the head would read a fragment
    mid-conversation, which is #1737 item 1's own failure.

    The head is genuinely first: ADR-0212 §3 orders on ``last_active_at`` ascending,
    and this one was active a second earlier. That ordering is also why the two arms
    that can separate them are the aged and the full ones — §1's monotonicity means
    a non-quiet head implies no candidate anywhere is quiet.
    """
    harness = Harness(batch_size=3, now=_Clock())
    head = await harness.conversation_stamped(active_at=RUN - timedelta(seconds=1), stamps=[RUN])
    behind = await harness.conversation_stamped(active_at=RUN, stamps=[RUN, RUN, RUN])

    report = await harness.stage.run()

    assert report.passes == 1
    assert harness.conversations.advances == [(behind, 3)]
    assert await harness.watermark(head) is None


async def test_the_page_read_to_decide_is_the_page_the_pass_reads() -> None:
    """ADR-0218 §2: "no turn is read twice to decide whether to read it".

    Unobservable from any report, so it is asserted on the store's own call log. The
    candidate carries a watermark and is due on the full arm, which is the arm that
    *has* to probe — the quiet arm reads nothing at all — so this is the case where a
    second read would actually happen if the page were not carried through.
    """
    harness = Harness(batch_size=2, now=_Clock())
    conversation = await harness.conversation_stamped(active_at=RUN, stamps=[RUN, RUN, RUN])
    # A watermark a pass really left, through the seam that leaves one: the first
    # turn is behind it, so the forward page is the next two and the full arm binds.
    await harness.conversations.record_observed(conversation, through_ordinal=1)
    harness.conversations.pages_read.clear()
    harness.conversations.tails_read.clear()

    report = await harness.stage.run()

    assert report.passes == 1
    assert harness.conversations.pages_read == [(conversation, 1)]
    assert harness.conversations.tails_read == []


async def test_a_first_pass_reads_two_pages_because_the_tail_is_a_different_page() -> None:
    """The one case ADR-0218 §2 names as reading two pages, and it names it as such.

    "Where the selected candidate has **no** recorded watermark, ADR-0212 §4 governs
    what the pass reads — 'that conversation's most recent ``observation_batch_size``
    turns' — which is a different page from the forward one the due test read. That
    is the one case in which a run reads two pages of one conversation, it happens on
    that conversation's first pass and never again."

    Asserted as the *tail* being read rather than merely as two calls, because the
    point is which turns the pass observes: the forward probe decided due-ness, and
    ADR-0212 §4's tail is still where the first pass begins.
    """
    harness = Harness(batch_size=2, now=_Clock())
    conversation = await harness.conversation_stamped(active_at=RUN, stamps=[RUN, RUN, RUN])

    report = await harness.stage.run()

    assert report.passes == 1
    assert harness.conversations.pages_read == [(conversation, None)]
    assert harness.conversations.tails_read == [conversation]
    # ADR-0212 §4's tail: the *newest* two turns, so the watermark lands at the top
    # and the prefix below it is passed over — which this ADR does not change.
    assert harness.conversations.advances == [(conversation, 3)]


# --- the scheduled run: what one run does (ADR-0218 §3, §9) -----------------


class _SlowObserver:
    """A ``FakeObserver`` whose call outlasts a run budget, so a boundary is visible.

    ADR-0111 §4's budget is "checked only at a chunk boundary, so no chunk is
    abandoned part-way and a run may overrun its budget by at most the duration of
    one chunk", and ADR-0218 §3 applies that with the pass as the chunk. A pass that
    returns instantly cannot tell a boundary check from an in-pass one, so this makes
    the first pass outlast the budget on purpose.
    """

    def __init__(self, inner: FakeObserver, *, takes: float) -> None:
        """Wrap ``inner``, parking for ``takes`` seconds on every call."""
        self._inner = inner
        self._takes = takes

    async def observe(self, episodes: Sequence[EpisodicMemory]) -> ObservationOutcome:
        """Park, then answer exactly as the canonical fake would."""
        await asyncio.sleep(self._takes)
        return await self._inner.observe(episodes)


async def test_a_run_with_nothing_due_performs_no_pass_and_calls_no_model() -> None:
    """ADR-0218 §2's own words, and the reason arming this job is affordable.

    "A run that finds no due candidate **performs no pass**: it calls no model,
    writes nothing, and reads no turn *to observe one*." That is what spends
    ADR-0083 §7's stated reason for the disabled default, so it is asserted rather
    than assumed — including that the run is a **success** carrying zeroes and not a
    failure, and that its terminal reason is the listing rather than the budget.
    """
    harness = Harness(now=_Clock())
    await harness.conversation_stamped(active_at=RUN, stamps=[RUN])

    report = await harness.stage.run()

    assert report == ObservationRunReport()
    assert report.budget_spent is False
    assert harness.fake.call_count == 0
    assert harness.conversations.advances == []


async def test_the_budget_is_checked_at_a_pass_boundary_and_never_inside_one() -> None:
    """ADR-0111 §4 with the pass as the chunk (ADR-0218 §3).

    The budget expires *during* the first pass, and the assertion is the pair: that
    pass completes in full — its advance lands, so nothing was abandoned part-way —
    and the second due candidate is not begun at all. A run checking the budget
    inside a pass would leave the first conversation's watermark where it was; one
    checking it nowhere would serve both.

    ``budget_spent`` is the disposition that separates this run from one that ran dry
    (§3's two terminal reasons), and it is asserted here because the counts alone
    cannot tell them apart.
    """
    harness = Harness(
        batch_size=2,
        now=_Clock(),
        observer=_SlowObserver(FakeObserver(), takes=0.05),
        run_budget=timedelta(milliseconds=10),
    )
    # Distinct activity instants, because ADR-0212 §3's order breaks a tie on `id`
    # and a uuid tie-break would make "which one the run served" a coin flip.
    first = await harness.conversation_stamped(active_at=AT, stamps=[AT, AT])
    second = await harness.conversation_stamped(
        active_at=AT + timedelta(seconds=1), stamps=[AT, AT]
    )

    report = await harness.stage.run()

    assert report.passes == 1
    assert report.budget_spent is True
    assert harness.conversations.advances == [(first, 2)]
    assert await harness.watermark(second) is None


async def test_a_conversation_deleted_under_a_run_drops_and_the_run_carries_on() -> None:
    """ADR-0218 §9, which is the one classification of ADR-0212 §6 it replaces.

    A deletion landing between the listing and the read is "an ordinary act the user
    performs, not a fault": the listing already excludes stamped conversations and
    both later calls raise for one, so the error is reachable from exactly one thing.
    Halting a whole run on it "would let one ordinary act stop a tick, and it would
    look like a store fault in the log".

    Both candidates are stamped under their own advance here, so the assertion is
    that the run **reached the second at all** — a run that halted on the first would
    log one attempt and stop. Nothing propagates, and the report is an ordinary one.
    """
    harness = Harness(now=_Clock())
    harness.conversations.stamp_before_advance = True
    first = await harness.conversation_stamped(active_at=AT, stamps=[AT])
    second = await harness.conversation_stamped(active_at=AT + timedelta(seconds=1), stamps=[AT])

    report = await harness.stage.run()

    assert [conversation for conversation, _ in harness.conversations.advances] == [first, second]
    assert report.passes == 0
    assert report.budget_spent is False


async def test_a_store_fault_at_the_advance_halts_the_run_and_propagates() -> None:
    """The other half of §9, and what keeps the catch narrow.

    "A pass that raises […] halts the run: no later pass is performed, and the
    exception **propagates out of** ``observe_due`` rather than being absorbed into a
    return value." Swallowing it would be the defect: ``Scheduler._run_job`` decides
    its two dispositions by whether the job body raises, so a run that returned a
    report saying it failed would be logged as a completed run with the fault's class
    recorded nowhere.

    This is the same shape as the case above with a different error class, which is
    exactly the point — the deletion race is caught because of *what it means*, not
    because a raise at that call is tolerable in general.
    """
    harness = Harness(now=_Clock())
    harness.conversations.advance_raises = True
    first = await harness.conversation_stamped(active_at=AT, stamps=[AT])
    await harness.conversation_stamped(active_at=AT + timedelta(seconds=1), stamps=[AT])

    with pytest.raises(ConversationStoreError):
        await harness.stage.run()

    assert harness.conversations.advances == [(first, 1)]


async def test_a_run_returns_counts_and_no_proposal_content_however_many_passes() -> None:
    """ADR-0218 §3's counts-only rule, asserted structurally rather than by reading fields.

    "**Nothing it returns grows with the number of passes**" — so the report of a
    three-pass run is checked for holding only numbers and one flag, which is the
    property a later field carrying an ``ObservedProposal`` would break. §3 argues it
    rather than asserting it: one report per pass would be "a list whose length is
    bounded by nothing in this ADR, holding Tier 1 proposal content, retained until
    the run returns, for a caller that discards it".

    The ruling counts are asserted as a **partition** of what was proposed, because
    what the gate rules is the policy's business and not this stage's: what this owes
    is that every proposal is accounted for exactly once.
    """
    harness = Harness(now=_Clock())
    for _ in range(3):
        await harness.conversation_stamped(active_at=AT, stamps=[AT, AT])

    report = await harness.stage.run()

    assert report.passes == 3
    assert report.conversations == 3
    assert report.model_calls == 3
    assert report.episodes_read == 6
    assert report.proposed > 0
    assert (
        report.committed + report.deferred + report.rejected + report.dropped_unsupported
        == report.proposed
    )
    assert all(isinstance(getattr(report, field.name), int | bool) for field in fields(report)), (
        "a run report carries counts and one disposition, never proposal content"
    )


async def test_a_run_drains_one_conversation_across_passes_until_it_leaves_the_set() -> None:
    """ADR-0218 §3's termination argument, and ADR-0212 §3's order working.

    "A candidate with many pages of unobserved turns stays at the head of the
    ascending order — no new turns, so no new activity instant — and is served pass
    after pass until it is exhausted or the budget is spent." §3 chose that over
    spreading the budget because ascending order "serves the material nearest its
    expiry first", and a run that abandoned a half-drained conversation would serve
    the material *furthest* from expiry with the same number of model calls.

    Four turns at a batch of two is two passes and then the candidate is gone, which
    is also the strict-advance half of the argument: each pass names a position
    strictly above the watermark it read, so the run cannot revisit what it drained.
    """
    harness = Harness(batch_size=2, now=_Clock())
    conversation = await harness.conversation_stamped(active_at=AT, stamps=[AT, AT, AT, AT, AT])
    # A watermark a pass really left, so the four turns above it are two pages. A
    # conversation with **no** watermark drains in one pass whatever its length,
    # because ADR-0212 §4 starts it at the tail and passes over the prefix.
    await harness.conversations.record_observed(conversation, through_ordinal=1)
    harness.conversations.advances.clear()

    report = await harness.stage.run()

    assert report.passes == 2
    assert report.conversations == 1
    assert harness.conversations.advances == [(conversation, 3), (conversation, 5)]
    # The third pass is stopped by the **watermark** and not by the listing's bound:
    # the conversation has left the candidate set because nothing stands above it.
    assert await harness.watermark(conversation) == 5


async def test_a_budget_the_due_test_spent_leaves_the_pass_unbegun() -> None:
    """The other half of the boundary, and the half a pass-length case cannot reach.

    ADR-0218 §2's due test is awaited work of its own — one listing, and up to fifty
    bounded page probes on a tick where nothing is quiet — so a run that checked its
    budget only *before* selecting could begin a pass on a budget those reads had
    already spent, and overrun by the due test **as well as** by one pass where §3
    allows one pass.

    Here the listing alone outlasts the budget, so the candidate is due, is selected,
    and is then not served: no model is called and no watermark moves, which is the
    difference between abandoning a pass part-way and never beginning one. What the
    check cannot bound is the listing's own duration — those are local store calls,
    which ADR-0218 §8 narrows out of ADR-0111 §4's deadline clause and #1817 holds.
    """
    harness = Harness(now=_Clock(), run_budget=timedelta(milliseconds=10))
    harness.conversations.listing_delay = 0.05
    conversation = await harness.conversation_stamped(active_at=AT, stamps=[AT, AT])

    report = await harness.stage.run()

    assert report.passes == 0
    assert report.budget_spent is True
    assert harness.fake.call_count == 0
    assert harness.conversations.advances == []
    assert await harness.watermark(conversation) is None


@pytest.mark.parametrize("figure", ["quiet_window", "max_unobserved_age", "run_budget"])
@pytest.mark.parametrize("bad", [timedelta(0), timedelta(seconds=-1)])
async def test_a_non_positive_run_figure_is_refused_at_construction(
    figure: str, bad: timedelta
) -> None:
    """ADR-0218 §7's ``gt=timedelta(0)``, guarded at the exported constructor too.

    ``Settings`` refuses these at load, and this class is exported — so a caller
    wiring it directly would otherwise get behaviour §7 forbids. ``timedelta(0)`` is
    the value that looks harmless and is not: a zero budget spends itself before the
    first pass boundary, and a zero quiet window makes **every** candidate quiet,
    which is the mid-conversation read §1 exists to prevent reached through the field
    meant to prevent it.
    """
    harness = Harness()
    # Typed loosely on purpose: parametrising over the *keyword* is what makes this
    # one case rather than three near-copies, and the three fields have different
    # types from the clock beside them.
    figures: dict[str, Any] = {figure: bad}
    with pytest.raises(ValueError, match="strictly positive"):
        ObservationStage(
            observer=harness.observer,
            conversations=harness.conversations,
            memory=harness.memory,
            writes=harness.writes,
            batch_size=BATCH,
            route=ROUTE,
            **figures,
        )


@pytest.mark.parametrize("figure", ["quiet_window", "max_unobserved_age", "run_budget"])
async def test_a_run_figure_that_is_not_a_duration_is_a_type_error(figure: str) -> None:
    """The other end, and it is not tidiness: a subclass can report infinity.

    ``type(...) is timedelta`` rather than ``isinstance`` closes the case
    ``core/config.py`` spends ``allow_inf_nan=False`` on one field over — a duration
    whose ``total_seconds`` is not finite makes a run's deadline unreachable and the
    run unbounded, which is the state the budget exists to prevent.
    """
    harness = Harness()
    figures: dict[str, Any] = {figure: 600}
    with pytest.raises(TypeError, match="must be a timedelta"):
        ObservationStage(
            observer=harness.observer,
            conversations=harness.conversations,
            memory=harness.memory,
            writes=harness.writes,
            batch_size=BATCH,
            route=ROUTE,
            **figures,
        )
