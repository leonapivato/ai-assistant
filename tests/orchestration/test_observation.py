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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    MemoryStoreError,
    ModelError,
    UnknownConversationError,
    UnresolvedEvidenceError,
)
from ai_assistant.core.types import (
    DeferralAdmissionOutcome,
    EpisodicMemory,
    MemoryDecision,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    ObservationOutcome,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration import (
    LearnDecision,
    MemoryWriteStage,
    ObservationReport,
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
    from collections.abc import Sequence

    from ai_assistant.core.protocols import MemoryWriter, Observer
    from ai_assistant.core.types import MemoryIngestResult

AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)

#: The route the stage is told the observer reads through (ADR-0077 §3). Fixed here
#: so a case can assert the report names *that* route and not some other string.
ROUTE = "anthropic:claude-opus-4-8"

BATCH = 20

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


class Harness:
    """A wired :class:`ObservationStage` and the fakes behind it, for assertions."""

    def __init__(
        self,
        *,
        observer: Observer | None = None,
        writer: MemoryWriter | None = None,
        policy: FakeMemoryPolicy | None = None,
        batch_size: int = BATCH,
    ) -> None:
        self._tick = 0
        self.memory = FakeMemoryStore(now=lambda: AT)
        self.conversations = FakeConversationStore(now=self._advancing)
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


async def test_an_unscoped_run_observes_the_most_recently_active_conversation() -> None:
    """With no id, the selector is ``recent``'s first row (§8)."""
    harness = Harness()
    older = await harness.conversation_with(2)
    newer = await harness.conversation_with(2)

    report = await harness.stage.observe()

    assert report.conversation_id == newer
    assert report.conversation_id != older
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


async def test_two_unscoped_runs_select_the_same_conversation() -> None:
    """By design: there is no cursor and no rotation (§8).

    Asserted rather than left implicit, because a test demanding otherwise would be
    demanding the durable state ADR-0077 §8 declines — and re-observation is safe
    without it, the gate folding a repeat into a ``REINFORCE``.
    """
    harness = Harness()
    await harness.conversation_with(2)
    newest = await harness.conversation_with(2)

    first = await harness.stage.observe()
    second = await harness.stage.observe()

    assert first.conversation_id == second.conversation_id == newest


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


async def test_observing_the_same_batch_twice_reinforces_rather_than_duplicating() -> None:
    """The second run folds into the existing record and does not raise its confidence.

    Scripted, because the property under test is the *fold*, not the model: an
    observer free to answer differently would make the assertion about the provider.
    """
    belief = "the user prefers metric units"
    harness = Harness(
        observer=FakeObserver([ObservedBelief(content=belief, record_id="rec-1")]),
        policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE),
    )
    conversation = await harness.conversation_with(2)

    first = await harness.stage.observe(conversation)
    stored = await harness.memory.get("rec-1")
    assert stored is not None
    before = stored.provenance.confidence

    # A second pass mints a fresh id for the same belief, as a real producer does
    # (ADR-0047 §2: the ids are the producer's). Re-using the first id would make
    # the write an upsert and hide whether the *fold* happened at all.
    harness.stage._observer = FakeObserver([ObservedBelief(content=belief, record_id="rec-2")])
    second = await harness.stage.observe(conversation)

    assert len(second.proposals) == len(first.proposals) == 1
    assert second.proposals[0].decision is LearnDecision.REINFORCED
    # Folded into the existing record rather than written as a second one.
    assert second.proposals[0].record_id == "rec-1"
    assert await harness.memory.get("rec-2") is None
    after = await harness.memory.get("rec-1")
    assert after is not None
    assert after.provenance.confidence == before  # the same evidence scores the same


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
