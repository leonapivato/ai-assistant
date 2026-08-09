"""Tests for the closed learning loop (ADR-0022).

Every collaborator is a canonical fake from ``ai_assistant.testing``, so these
tests exercise the wiring without importing any subsystem's internals (CLAUDE.md
golden rule 1) — which is exactly what the engine under test is required to do.

The one that matters most is :func:`test_a_learned_preference_is_reused_on_a_later_turn`:
the *closed* part of the loop, and the roadmap's acceptance criterion for the
first vertical.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import (
    AssistantError,
    ContextError,
    MemoryStoreConflictError,
    MemoryStoreError,
    PlanningError,
)
from ai_assistant.core.types import (
    CurrentContext,
    EpisodicMemory,
    FeedbackEvent,
    FeedbackKind,
    MemoryDecisionKind,
    MemoryKind,
    MemorySource,
    MemoryUpdateProposal,
    PreferenceMemory,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.orchestration import (
    LearningLoop,
    MemoryWriteStage,
)
from ai_assistant.orchestration.loop import (
    _DEFAULT_RESOLUTION_LIMIT,
    RESOLUTION_KINDS,
)
from ai_assistant.testing import (
    FakeContextProvider,
    FakeDeferralStore,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanner,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryPolicy,
        MemoryStore,
        MemoryWriter,
        Planner,
    )
    from ai_assistant.core.types import (
        ActionPlan,
        BeliefBand,
        Goal,
        MemoryIngestResult,
        MemoryRecord,
        MemoryWrite,
        SourceReading,
    )

_NOW = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)


def _clock() -> datetime:
    return _NOW


class _FailingSearchStore(FakeMemoryStore):
    """The canonical store with retrieval broken.

    ``FakeMemoryStore`` has no configured failure mode the way
    ``FakeContextProvider`` does (issue #105), and the degradation path needs
    one. Narrowly overriding the single method under test keeps the rest of the
    contract-correct fake rather than hand-rolling a mock of the whole store.
    """

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> list[MemoryRecord]:
        """Fail the way a real store fails, whichever band was asked for."""
        msg = "fake: retrieval is unavailable"
        raise MemoryStoreError(msg)


class _FailingPlanner:
    """A ``Planner`` that cannot plan.

    ``FakePlanner`` always succeeds, and the ``Planner`` contract documents
    ``PlanningError`` as an outcome the pipeline must survive, so the failure
    path needs a subject the canonical fake cannot be configured into being.
    """

    async def plan(
        self,
        goal: Goal,
        *,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
    ) -> ActionPlan:
        """Fail the way a planner with nothing to offer fails."""
        msg = "no plan for that"
        raise PlanningError(msg)


def _writes(writer: MemoryWriter) -> MemoryWriteStage:
    """Wrap a writer in the write stage the loop now holds (ADR-0078 §3).

    The loop reaches memory through the *stage* rather than through a
    ``MemoryWriter`` of its own, so a proposal the policy defers parks a durable
    question instead of vanishing. Each stage gets a fresh ``FakeDeferralStore``;
    the tests that assert what the queue did build their own and read it back.
    """
    return MemoryWriteStage(writer=writer, deferrals=FakeDeferralStore(now=_clock))


def _loop(  # noqa: PLR0913  # one parameter per injected collaborator, all optional
    *,
    context: ContextProvider | None = None,
    memory: MemoryStore | None = None,
    policy: MemoryPolicy | None = None,
    planner: Planner | None = None,
    feedback: FeedbackProcessor | None = None,
    writer: MemoryWriter | None = None,
    resolution_limit: int = _DEFAULT_RESOLUTION_LIMIT,
) -> LearningLoop:
    """Build a loop from canonical fakes, with a fixed clock and stable ids.

    Parameters are typed by the Protocols, not the fakes, so a test can swap in
    a narrower double (see :class:`_FailingPlanner`) without a cast.

    **The writer is built over the same store the loop retrieves from**, which
    is the composition-root obligation ADR-0028 §4 states and cannot put in the
    type system. It is enforced here rather than requested: wired to two stores,
    :func:`test_a_learned_preference_is_reused_on_a_later_turn` learns
    successfully and retrieves nothing on the next turn. ``policy`` reaches the
    loop only through that writer — the loop holds no policy of its own.
    """
    store = memory or FakeMemoryStore(now=_clock)
    return LearningLoop(
        context=context or FakeContextProvider(),
        memory=store,
        writes=_writes(
            writer or FakeMemoryWriter(store=store, policy=policy or FakeMemoryPolicy(), now=_clock)
        ),
        planner=planner or FakePlanner(now=_clock),
        feedback=feedback or FakeFeedbackProcessor(),
        resolution_limit=resolution_limit,
        now=_clock,
        id_factory=lambda: "goal-1",
    )


def _preference_feedback(content: str = "prefers concise replies") -> FeedbackEvent:
    return FeedbackEvent(
        kind=FeedbackKind.PREFERENCE,
        memory_kind=MemoryKind.PREFERENCE,
        content=content,
        subject="email tone",
        created_at=_NOW,
    )


def _correction(
    content: str = "the office is in Boston",
    *,
    memory_kind: MemoryKind | None = None,
) -> FeedbackEvent:
    """A correction, **unpinned by default** — the case ADR-0122 §3 resolves."""
    return FeedbackEvent(
        kind=FeedbackKind.CORRECTION,
        memory_kind=memory_kind,
        content=content,
        created_at=_NOW,
    )


def _stated_preference(content: str = "I prefer tea") -> FeedbackEvent:
    """A stated preference with **no** ``memory_kind`` — §3's other arm."""
    return FeedbackEvent(kind=FeedbackKind.PREFERENCE, content=content, created_at=_NOW)


def _asserted(at: datetime = _NOW) -> Provenance:
    return Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=at)


def _observed(confidence: float = 0.6) -> Provenance:
    return Provenance(source=MemorySource.OBSERVED, confidence=confidence, last_updated=_NOW)


# --------------------------------------------------------------------------- #
# The closed loop                                                             #
# --------------------------------------------------------------------------- #


async def test_a_learned_preference_is_reused_on_a_later_turn() -> None:
    """The whole point: correct the assistant once, and the next turn knows.

    Turn 1 plans with nothing retrieved. The user then states a preference; the
    policy accepts it and it is written. Turn 2 plans with that preference in
    hand — the *closed* part of the loop, proven rather than claimed.
    """
    planner = FakePlanner(now=_clock)
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, planner=planner)

    first = await loop.respond("draft a reply to Dana")
    assert first.memories == ()
    assert planner.calls[0][2] == ()

    [outcome] = await loop.learn(_preference_feedback())
    assert outcome.result.decision.kind is MemoryDecisionKind.ACCEPT
    assert outcome.result.record_id is not None

    second = await loop.respond("draft a concise reply to Dana")

    assert [record.id for record in second.memories] == [outcome.result.record_id]
    learned = second.memories[0]
    assert isinstance(learned, PreferenceMemory)
    assert learned.preference == "prefers concise replies"
    # The planner did not merely have it available — it was handed it.
    assert [record.id for record in planner.calls[1][2]] == [outcome.result.record_id]
    assert not second.memory_degraded


# --------------------------------------------------------------------------- #
# respond: stage wiring                                                       #
# --------------------------------------------------------------------------- #


async def test_respond_plans_against_the_assembled_context() -> None:
    context = CurrentContext(
        now=_NOW,
        time_of_day=TimeOfDay.NIGHT,
        is_weekend=True,
        within_working_hours=False,
    )
    provider = FakeContextProvider(context)
    planner = FakePlanner(now=_clock)
    loop = _loop(context=provider, planner=planner)

    result = await loop.respond("what is on tomorrow")

    assert provider.call_count == 1
    assert result.context == context
    assert planner.calls[0][1] == context
    assert result.plan.goal_id == result.goal.id


async def test_respond_mints_a_user_asserted_goal_from_the_utterance() -> None:
    loop = _loop()

    result = await loop.respond("  book the flight  ")

    assert result.goal.id == "goal-1"
    assert result.goal.statement == "book the flight"
    assert result.goal.provenance.source is MemorySource.USER_ASSERTED
    assert result.goal.created_at == _NOW


@pytest.mark.parametrize("utterance", ["", "   ", "\n\t"])
async def test_respond_refuses_a_blank_utterance(utterance: str) -> None:
    loop = _loop()

    with pytest.raises(PlanningError, match="non-empty utterance"):
        await loop.respond(utterance)


async def test_respond_does_not_assemble_context_for_a_blank_utterance() -> None:
    """Nothing downstream runs once the request is known to be unanswerable."""
    provider = FakeContextProvider()
    planner = FakePlanner(now=_clock)
    loop = _loop(context=provider, planner=planner)

    with pytest.raises(PlanningError):
        await loop.respond("")

    assert provider.call_count == 0
    assert planner.calls == []


async def test_a_derived_flood_cannot_displace_an_assertion_from_the_prompt() -> None:
    """The acceptance criterion for per-band retrieval, end to end (ADR-0072 §5).

    This is the failure the whole band-scoped read exists to prevent, driven
    through the loop rather than through the assembler: "a flood of low-confidence
    inferences can displace an assertion *below the cut*, where no amount of
    downstream ordering recovers it".

    **It is written end-to-end deliberately, because the unit tests do not reach
    it.** ``assemble_by_band`` has its own suite and the store has its conformance
    clause, but nothing else pins ``LoopEngine._retrieve`` to *use* them — reverting
    it to a single band-neutral ``search`` leaves every other test in this change
    green while restoring the exact bug. That gap is what this closes.

    The fixture makes the flood win under a band-neutral read on the fake's own
    ranking: every record scores 1.0 (each contains the one query term), the sort is
    stable, and the forty inferences are inserted first, so a band-neutral top-5
    is forty-deep in inferences before it reaches the assertion. Composing per band
    puts the assertion first because it is in the first band read, not because it
    outscored anything — which is precisely ADR-0113 §4's distinction between
    eligibility and ordering.
    """
    memory = FakeMemoryStore(now=_clock)
    for index in range(40):
        await memory.add(
            SemanticMemory(
                id=f"guess-{index}",
                content="dana billing",
                fact="dana billing",
                provenance=Provenance(
                    source=MemorySource.INFERRED, confidence=0.6, last_updated=_NOW
                ),
            )
        )
    await memory.add(
        SemanticMemory(
            id="told",
            content="dana billing owner",
            fact="dana billing owner",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
            ),
        )
    )
    planner = FakePlanner(now=_clock)
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=_writes(FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)),
        planner=planner,
        feedback=FakeFeedbackProcessor(),
        retrieval_limit=5,
        now=_clock,
    )

    result = await loop.respond("dana")

    ids = [record.id for record in result.memories]
    assert ids[0] == "told", (
        "the user's own assertion must reach the prompt first; a band-neutral "
        "retrieval leaves it below the cut (ADR-0072 §5, ADR-0113 §2)"
    )
    assert len(ids) == 5, "the rest of the budget still goes to the derived band"


async def test_respond_retrieves_at_most_the_configured_limit() -> None:
    memory = FakeMemoryStore(now=_clock)
    for index in range(4):
        await memory.add(
            SemanticMemory(
                id=f"fact-{index}",
                content="dana works on billing",
                fact="dana works on billing",
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.6, last_updated=_NOW
                ),
            )
        )
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=_writes(FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)),
        planner=FakePlanner(now=_clock),
        feedback=FakeFeedbackProcessor(),
        retrieval_limit=2,
        now=_clock,
    )

    result = await loop.respond("dana")

    assert len(result.memories) == 2


async def test_respond_survives_a_retrieval_failure_and_says_so() -> None:
    """Losing memory costs the answer its personalisation, not its usefulness."""
    planner = FakePlanner(now=_clock)
    loop = _loop(memory=_FailingSearchStore(now=_clock), planner=planner)

    result = await loop.respond("draft a reply to Dana")

    assert result.memory_degraded
    assert result.memories == ()
    assert planner.calls[0][2] == ()
    assert result.plan is not None


async def test_respond_aborts_when_context_assembly_fails() -> None:
    """A context that cannot be assembled is not one to invent."""
    planner = FakePlanner(now=_clock)
    loop = _loop(context=FakeContextProvider(failure="no sources"), planner=planner)

    with pytest.raises(ContextError, match="no sources"):
        await loop.respond("draft a reply to Dana")

    assert planner.calls == []


async def test_respond_propagates_a_planning_failure() -> None:
    loop = _loop(planner=_FailingPlanner())

    with pytest.raises(PlanningError, match="no plan for that"):
        await loop.respond("do the impossible")


# --------------------------------------------------------------------------- #
# learn: propose, dispose, persist                                            #
# --------------------------------------------------------------------------- #


async def test_learn_writes_an_accepted_proposal() -> None:
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.ACCEPT))

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.result.record_id is not None
    assert await memory.get(outcome.result.record_id) is not None


async def test_learn_writes_nothing_when_the_processor_proposes_nothing() -> None:
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, feedback=FakeFeedbackProcessor([]))

    assert await loop.learn(_preference_feedback()) == ()
    assert await memory.export() == []


async def test_learn_reports_a_rejection_without_writing() -> None:
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.REJECT))

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.result.decision.kind is MemoryDecisionKind.REJECT
    assert outcome.result.record_id is None
    assert await memory.export() == []


async def test_learn_stamps_expiry_on_a_temporary_store() -> None:
    """Stamped by the *writer's* clock, which is why the helper fixes both.

    A test that fixed only the loop's would get a wall-clock expiry here
    (ADR-0028 §4b).
    """
    memory = FakeMemoryStore(now=_clock)
    ttl = timedelta(hours=6)
    loop = _loop(
        memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=ttl)
    )

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.result.record_id is not None
    stored = await memory.get(outcome.result.record_id)
    assert stored is not None
    assert stored.expires_at == _NOW + ttl


async def test_learn_applies_a_reinforce_through_the_writer() -> None:
    """ADR-0028 §4: the ruling that consolidates is now *applied*, not reported.

    The loop still knows nothing about what a fold is — the writer's fold
    lands it on the target's id and the loop reports what it was told. This test
    replaces ADR-0022 §4's ``test_learn_reports_a_merge_without_applying_it``,
    which described the gap issue #103 tracked.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        PreferenceMemory(
            id="pref-existing",
            content="prefers concise replies always",
            preference="prefers concise replies always",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.6, last_updated=_NOW),
        )
    )
    loop = _loop(memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.REINFORCE))

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.result.decision.kind is MemoryDecisionKind.REINFORCE
    assert outcome.result.decision.target_id == "pref-existing"
    assert outcome.result.record_id == "pref-existing"  # the target's id, not a new one
    assert [record.id for record in await memory.export()] == ["pref-existing"]
    merged = await memory.get("pref-existing")
    assert merged is not None
    assert merged.content == "prefers concise replies"  # folded, not left alone


async def test_learn_hands_every_proposal_to_the_writer() -> None:
    """What the loop now owns of the write path: delegation, in order.

    Conflict resolution, the policy's ruling and the write itself are the
    writer's, so this is the whole of the loop's obligation (ADR-0028 §4) — and
    the write half of the loop no longer has a copy of any of them to test.
    """
    memory = FakeMemoryStore(now=_clock)
    writer = FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)
    proposals = [
        MemoryUpdateProposal(
            proposed=PreferenceMemory(
                id=f"pref-{index}",
                content=f"preference {index}",
                preference=f"preference {index}",
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
                ),
            ),
            rationale="user preference",
        )
        for index in range(2)
    ]
    loop = _loop(memory=memory, writer=writer, feedback=FakeFeedbackProcessor(proposals))

    await loop.learn(_preference_feedback())

    assert [call.proposed.id for call in writer.calls] == ["pref-0", "pref-1"]
    # The loop resolves no conflicts of its own: what it hands over is the
    # proposal as proposed, ids and all.
    assert [call.conflicts for call in writer.calls] == [(), ()]


async def test_learn_applies_every_proposal_in_order() -> None:
    memory = FakeMemoryStore(now=_clock)
    proposals = [
        MemoryUpdateProposal(
            proposed=PreferenceMemory(
                id=f"pref-{index}",
                content=f"preference {index}",
                preference=f"preference {index}",
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
                ),
            ),
            rationale="user preference",
        )
        for index in range(3)
    ]
    loop = _loop(memory=memory, feedback=FakeFeedbackProcessor(proposals))

    outcomes = await loop.learn(_preference_feedback())

    assert [outcome.result.record_id for outcome in outcomes] == ["pref-0", "pref-1", "pref-2"]


async def test_learn_propagates_a_store_failure() -> None:
    loop = _loop(memory=_FailingSearchStore(now=_clock))

    with pytest.raises(MemoryStoreError, match="retrieval is unavailable"):
        await loop.learn(_preference_feedback())


async def test_learn_refuses_a_repeated_record_id_rather_than_overwriting() -> None:
    """A repeated record id is refused, not resolved last-write-wins (ADR-0108 §1).

    This case previously asserted the opposite, on ADR-0022 §4's ground that
    ``MemoryStore.add`` is an upsert and "both outcomes report that id, so the
    collision is visible rather than hidden". ADR-0108 partially supersedes that
    clause. The loop still does not de-duplicate — nothing here inspects the
    proposals against each other — but the write path now *declares* what it means,
    and an ``ACCEPT`` means "install a new record". The collision stays visible, and
    more so: a refusal naming the id, rather than two reported successes one of
    which destroyed the other's record.

    §4's *reasoning* survives, and so does the case it protected: a caller that
    means to land on a stored record still does, through the fold the policy rules.
    What §4 defended never looked like this — two proposals of one kind arriving at
    one id with different content, nothing ruled about the record standing there,
    which conflict detection cannot even see (#630, #110).
    """
    memory = FakeMemoryStore(now=_clock)
    proposals = [
        MemoryUpdateProposal(
            proposed=PreferenceMemory(
                id="pref-same",
                content=content,
                preference=content,
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
                ),
            ),
            rationale="user preference",
        )
        for content in ("prefers short replies", "prefers very short replies")
    ]
    loop = _loop(memory=memory, feedback=FakeFeedbackProcessor(proposals))

    with pytest.raises(MemoryStoreConflictError):
        await loop.learn(_preference_feedback())

    # The first proposal stands untouched. That is the whole point: the record the
    # second write would have replaced is one no ruling was made about, so replacing
    # it silently is the defect and refusing is the fix. The partial application is
    # ADR-0022 §4's documented behaviour for a store failure, unchanged.
    stored = await memory.get("pref-same")
    assert stored is not None
    assert stored.content == "prefers short replies"


async def test_learn_propagates_a_processor_failure_without_writing() -> None:
    """Nothing is proposed, so nothing may be written — and the failure surfaces.

    ``learn`` runs the processor before any other stage, so a failure there must
    leave the store untouched rather than being swallowed into an empty result
    indistinguishable from "the user said nothing worth learning".
    """

    class _FailingProcessor:
        """A ``FeedbackProcessor`` that cannot derive proposals."""

        async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
            """Fail the way a processor with a broken model fails."""
            msg = "fake: cannot derive proposals"
            raise AssistantError(msg)

    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, feedback=_FailingProcessor())

    with pytest.raises(AssistantError, match="cannot derive proposals"):
        await loop.learn(_preference_feedback())

    assert await memory.export() == []


async def test_learn_propagates_a_writer_failure_without_writing() -> None:
    """A proposal the write path refused is not one this loop rescues.

    The writer holds the policy that gates the write (VISION §7), so whatever it
    raises — a policy that cannot rule, a store that cannot be read — propagates
    as itself rather than being swallowed or defaulted into memory (ADR-0028 §5:
    no error type is invented at this seam).
    """

    class _FailingWriter:
        """A ``MemoryWriter`` that cannot ingest."""

        async def ingest(self, proposal: MemoryUpdateProposal) -> MemoryIngestResult:
            """Fail the way a writer whose policy cannot rule fails."""
            msg = "fake: cannot rule on this"
            raise AssistantError(msg)

        async def ingest_reading(self, reading: SourceReading) -> Sequence[MemoryIngestResult]:
            """Fail the same way, so the double refuses on both seams alike."""
            msg = "fake: cannot rule on this"
            raise AssistantError(msg)

    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, writer=_FailingWriter())

    with pytest.raises(AssistantError, match="cannot rule on this"):
        await loop.learn(_preference_feedback())

    assert await memory.export() == []


async def test_learn_leaves_earlier_proposals_applied_when_a_later_write_fails() -> None:
    """The partial application ADR-0022 §4 documents, pinned rather than assumed."""

    class _FailsOnSecondWrite(FakeMemoryStore):
        """The canonical store, refusing every write after the first.

        It overrides ``write_atomic`` rather than ``add`` because that is the door
        an installing ruling goes through since ADR-0108 §2 — the ingestor declares
        ``INSERT_IF_ABSENT`` rather than relying on ``add``'s upsert default. The
        subject of this case is unchanged: a store failure part-way through a
        proposal list, and what the loop does about it.
        """

        def __init__(self) -> None:
            super().__init__(now=_clock)
            self.writes = 0

        async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
            """Accept the first write, then fail the way a full store fails."""
            self.writes += 1
            if self.writes > 1:
                msg = "fake: the store is full"
                raise MemoryStoreError(msg)
            return await super().write_atomic(writes)

    memory = _FailsOnSecondWrite()
    proposals = [
        MemoryUpdateProposal(
            proposed=PreferenceMemory(
                id=f"pref-{index}",
                content=f"preference {index}",
                preference=f"preference {index}",
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
                ),
            ),
            rationale="user preference",
        )
        for index in range(2)
    ]
    loop = _loop(memory=memory, feedback=FakeFeedbackProcessor(proposals))

    with pytest.raises(MemoryStoreError, match="the store is full"):
        await loop.learn(_preference_feedback())

    # No result is returned at all, and the first proposal stays written: the
    # loop reports no success it cannot stand behind, and invents no rollback
    # the MemoryStore contract does not offer.
    assert [record.id for record in await memory.export()] == ["pref-0"]


# --------------------------------------------------------------------------- #
# learn: resolving a correction's drawer (ADR-0122)                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _SearchCall:
    """One ``MemoryStore.search``, as its caller asked for it."""

    query: str
    limit: int
    kinds: tuple[MemoryKind, ...] | None
    bands: tuple[BeliefBand, ...] | None


@dataclass(frozen=True, slots=True)
class _Processed:
    """One ``FeedbackProcessor.process``, journalled beside the searches."""

    event: FeedbackEvent


class _JournallingStore(FakeMemoryStore):
    """The canonical store, recording every ``search`` into a shared journal.

    ``FakeMemoryStore`` records nothing of its reads, and ADR-0122 §10 asks for a
    test on the read's *shape* rather than on what it produced — "an implementation
    that issues two searches, passes ``bands``, omits the ``kinds`` argument, or
    reuses the turn's ``retrieval_limit`` still resolves a lone preference neighbour
    correctly and passes" every outcome test in this file.

    The journal is shared with :class:`_JournallingProcessor` so the *order* is
    recorded too, which is what separates the resolution's read from the write
    path's own conflict probe further down. Overriding one method keeps the rest of
    the contract-correct fake rather than hand-rolling a store.
    """

    def __init__(self, journal: list[object], **kwargs: object) -> None:
        """Record into ``journal``; every other argument is the canonical fake's."""
        super().__init__(**kwargs)  # type: ignore[arg-type]  # relayed verbatim
        self._journal = journal

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> list[MemoryRecord]:
        """Record the call as asked for, then answer it as the fake does."""
        self._journal.append(
            _SearchCall(
                query=query,
                limit=limit,
                kinds=None if kinds is None else tuple(kinds),
                bands=None if bands is None else tuple(bands),
            )
        )
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)


class _JournallingProcessor(FakeFeedbackProcessor):
    """The canonical processor, marking the journal where it was called."""

    def __init__(self, journal: list[object]) -> None:
        """Record into the same journal :class:`_JournallingStore` writes to."""
        super().__init__()
        self._journal = journal

    async def process(self, event: FeedbackEvent) -> Sequence[MemoryUpdateProposal]:
        """Mark the call, then answer as the canonical fake does."""
        self._journal.append(_Processed(event=event))
        return await super().process(event)


class _RefusingSearchStore(FakeMemoryStore):
    """The canonical store, for which being searched at all is the failure.

    The shape ADR-0122 §10 requires for §6's pin: "an injected store that fails the
    assertion if ``search`` is called at all", because a resolution that ran and
    *then* deferred to the pin passes an outcome-only test while issuing a read
    whose result it discards.
    """

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> list[MemoryRecord]:
        """Refuse: this store must not be read."""
        msg = f"the resolution must issue no search here, and it searched for {query!r}"
        raise AssertionError(msg)


class _PostCutKindFilterStore(FakeMemoryStore):
    """A conforming store whose ``kind`` predicate binds **after** the ranking cut.

    ``FakeMemoryStore`` filters by kind before it truncates, which is one permitted
    placement but not the only one: ADR-0113 §2 moves the *band* ahead of the cut and
    is explicit that ``kind`` keeps "the post-cut placement ADR-0045 §6 and ADR-0007
    ratified for them", so "a call may return fewer than ``limit`` records while
    eligible ones exist". Both are conforming, and the residue ADR-0122 §3 records —
    a target crowded out by higher-ranked records the resolution cannot mint — is
    only expressible against this one. Modelled here rather than asserted of the
    canonical fake, which cannot exhibit it.
    """

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> list[MemoryRecord]:
        """Rank and cut band-neutrally and kind-neutrally, then drop what is out."""
        wanted = None if kinds is None else frozenset(str(kind) for kind in kinds)
        page = await super().search(query, limit=limit, bands=bands)
        return [record for record in page if wanted is None or record.kind in wanted]


async def test_the_resolution_reads_once_before_the_processor_and_in_the_shape_ruled() -> None:
    """§3's clause is not observable from an outcome, so it is asserted directly.

    ADR-0122 §10 names each way an implementation passes every other test here while
    breaking this one: two searches carry an extra failure point on a path the user
    invokes by hand; passing ``bands`` narrows a read the clause leaves band-neutral;
    omitting ``kinds`` lets a crowd of episodes take the page (§3, and
    :func:`test_a_correction_crowded_out_by_records_it_cannot_mint_lands_as_semantic`);
    and reusing ``retrieval_limit`` moves what a correction is filed under whenever a
    deployment tunes what an answer is personalised from.

    The journal is shared with the processor so the ordering is pinned too — §3 says
    the resolution happens *before* the ``FeedbackProcessor`` is called, and the
    write path's own conflict probe reads the same store moments later.
    """
    journal: list[object] = []
    memory = _JournallingStore(journal, now=_clock)
    await memory.add(
        PreferenceMemory(
            id="pref-espresso",
            content="prefers espresso in the morning",
            preference="prefers espresso in the morning",
            provenance=_asserted(),
        )
    )
    loop = _loop(
        memory=memory,
        feedback=_JournallingProcessor(journal),
        # Neither the turn's limit nor ``search``'s own default, so an
        # implementation reusing either is caught by the value alone.
        resolution_limit=3,
    )

    await loop.learn(_correction("prefers cappuccino in the morning, not espresso"))

    processed = next(index for index, entry in enumerate(journal) if isinstance(entry, _Processed))
    reads = [entry for entry in journal[:processed] if isinstance(entry, _SearchCall)]
    assert len(reads) == 1, "exactly one search resolves the drawer"
    [read] = reads
    assert read.query == "prefers cappuccino in the morning, not espresso"
    assert read.kinds == (MemoryKind.PREFERENCE, MemoryKind.SEMANTIC)
    assert read.bands is None
    assert read.limit == 3


def test_the_resolution_set_is_the_two_kinds_the_rule_based_processor_mints() -> None:
    """§3 fixes the set by that clause, and widening it is a ratified decision.

    Pinned as a literal rather than derived, because the derivation is the thing §3
    refuses: ``FeedbackProcessor`` exposes ``process`` and nothing else, so the set
    cannot be asked for, and inventing a declaration would be a Protocol change under
    golden rule 5. When ADR-0009 §6's ``PROCEDURAL``/``EPISODIC`` deferral is taken
    up, the lane taking it partially supersedes §3 in the scope of this set — and
    this assertion is what makes that a decision rather than a drift.
    """
    assert RESOLUTION_KINDS == (MemoryKind.PREFERENCE, MemoryKind.SEMANTIC)


async def test_a_correction_resolves_into_the_drawer_its_target_lives_in() -> None:
    """The defect #864 reports, at this loop's own seam.

    The correction names no record type. Its only neighbour is a ``PreferenceMemory``
    — which the pre-ADR fixed table could not reach, because it filed every
    correction as ``SEMANTIC`` and the conflict probe then looked only there.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        PreferenceMemory(
            id="pref-espresso",
            content="prefers espresso in the morning",
            preference="prefers espresso in the morning",
            provenance=_observed(),
        )
    )
    processor = FakeFeedbackProcessor()
    loop = _loop(memory=memory, feedback=processor)

    await loop.learn(_correction("prefers cappuccino in the morning, not espresso"))

    assert processor.last_event.memory_kind is MemoryKind.PREFERENCE


async def test_a_stated_preference_resolves_by_intent_and_issues_no_read() -> None:
    """§3's ``PREFERENCE`` arm, which omitting would be a defect rather than a saving.

    The store is one that fails on being read at all, so an implementation resolving
    *both* intents by search fails here even though its answer would be right on a
    store that happened to hold nothing — the accident §10 names ("an outcome-only
    test passes here by accident whenever the store happens to hold nothing"). A
    stated preference establishes a ``PreferenceMemory`` by its own intent: the user
    is not pointing at a stored belief, they are stating one.
    """
    processor = FakeFeedbackProcessor()
    memory = _RefusingSearchStore(now=_clock)
    loop = _loop(
        memory=memory,
        feedback=processor,
        # The write path reads the store too, and this store refuses every read;
        # the subject here is the resolution, so the write is taken out of the way.
        writer=FakeMemoryWriter(
            store=FakeMemoryStore(now=_clock), policy=FakeMemoryPolicy(), now=_clock
        ),
    )

    await loop.learn(_stated_preference("I prefer tea in the afternoon"))

    assert processor.last_event.memory_kind is MemoryKind.PREFERENCE


async def test_a_pinned_kind_is_honoured_and_suppresses_the_resolution_read() -> None:
    """§6: the pin says "I know which drawer, **do not look**".

    A resolution that ran and then deferred to the pin would perform a search whose
    result it discards, and would pass any outcome-only test; a store that refuses to
    be read is what makes the difference observable. The pin is honoured for both
    ``FeedbackKind`` members, and into the drawer the user named even where a
    resolution would have chosen another.
    """
    processor = FakeFeedbackProcessor()
    loop = _loop(
        memory=_RefusingSearchStore(now=_clock),
        feedback=processor,
        writer=FakeMemoryWriter(
            store=FakeMemoryStore(now=_clock), policy=FakeMemoryPolicy(), now=_clock
        ),
    )

    await loop.learn(_correction("the office is in Boston", memory_kind=MemoryKind.SEMANTIC))
    await loop.learn(
        _stated_preference("I prefer tea").model_copy(update={"memory_kind": MemoryKind.SEMANTIC})
    )

    assert [event.memory_kind for event in processor.events] == [
        MemoryKind.SEMANTIC,
        MemoryKind.SEMANTIC,
    ]


async def test_the_resolution_never_selects_a_kind_the_processor_cannot_mint() -> None:
    """§3's bounded set, with the best-ranked record overall an episode.

    The episode outranks the preference on the fake's own scoring — it contains both
    query terms where the preference contains one — so an unscoped read would resolve
    to ``EPISODIC``, ``_to_record`` would propose nothing, and the user's correction
    would vanish *entirely*: strictly worse than the mis-drawering ADR-0122 fixes.
    Scoped, the correction resolves to the best-ranked **mintable** drawer instead.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        EpisodicMemory(
            id="ep-1",
            content="the user ordered espresso this morning",
            occurred_at=_NOW,
            provenance=_observed(),
        )
    )
    await memory.add(
        PreferenceMemory(
            id="pref-espresso",
            content="prefers espresso",
            preference="prefers espresso",
            provenance=_observed(),
        )
    )
    processor = FakeFeedbackProcessor()
    loop = _loop(memory=memory, feedback=processor)

    outcomes = await loop.learn(_correction("espresso this morning"))

    assert processor.last_event.memory_kind is MemoryKind.PREFERENCE
    assert len(outcomes) == 1, "the correction must not vanish"


async def test_two_mintable_drawers_match_and_the_best_ranked_one_wins_once() -> None:
    """§4: best-ranked, no tiebreak of our own, and exactly **one** proposal.

    The semantic record carries both query terms and the preference one, so relevance
    — the only ordering this corpus admits (ADR-0113 §4, ADR-0112 §1) — puts the
    semantic record first. Minting into both drawers is expressible (``process``
    returns a ``Sequence``) and refused: one utterance is one belief, and a store
    holding neighbours in two drawers is a fact about the store rather than evidence
    the user holds two wrong beliefs.
    """
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        SemanticMemory(
            id="fact-1",
            content="the office is in Boston",
            fact="the office is in Boston",
            provenance=_observed(),
        )
    )
    await memory.add(
        PreferenceMemory(
            id="pref-1",
            content="prefers the office quiet",
            preference="prefers the office quiet",
            provenance=_observed(),
        )
    )
    processor = FakeFeedbackProcessor()
    loop = _loop(memory=memory, feedback=processor)

    outcomes = await loop.learn(_correction("the office is in Cambridge"))

    assert processor.last_event.memory_kind is MemoryKind.SEMANTIC
    assert len(outcomes) == 1


async def test_a_correction_with_no_live_target_lands_as_semantic() -> None:
    """§5: the store looked and holds nothing, so the correction stands alone.

    A correction with no live target is an assertion the user happened to phrase as
    one, and ``SEMANTIC`` is the drawer for a free-standing assertion — the one branch
    on which the old fixed table's answer was ever right. It is never dropped, never
    refused, and never held for a question on this ground.
    """
    processor = FakeFeedbackProcessor()
    loop = _loop(feedback=processor)

    outcomes = await loop.learn(_correction("the office is in Boston"))

    assert processor.last_event.memory_kind is MemoryKind.SEMANTIC
    assert len(outcomes) == 1


async def test_a_correction_crowded_out_by_records_it_cannot_mint_lands_as_semantic() -> None:
    """The residue §3 records, asserted as the **known** outcome rather than hidden.

    Against a store whose ``kind`` predicate binds after the ranking cut — a placement
    ADR-0113 §2 explicitly leaves to ``kind`` — three higher-ranked episodes fill a
    resolution page of three, and the preference sitting just below is never seen. The
    correction resolves by §5 and lands as ``SEMANTIC``, exactly as it does today.

    This is issue #457's known non-exhaustiveness of retrieval, which ADR-0122 §3
    states rather than papers over: ``_detect_conflicts`` stands on the same limit for
    the same reason — "what it never surfaced is invisible here". Closing it means
    closing #457, for the conflict probe and this read together; a second retrieval
    operation invented in this lane would be a ``MemoryStore`` contract decision taken
    where ``MemoryStore`` is not being decided.
    """
    memory = _PostCutKindFilterStore(now=_clock)
    for index in range(3):
        await memory.add(
            EpisodicMemory(
                id=f"ep-{index}",
                content="ordered espresso this morning again",
                occurred_at=_NOW,
                provenance=_observed(),
            )
        )
    await memory.add(
        PreferenceMemory(
            id="pref-espresso",
            content="prefers espresso",
            preference="prefers espresso",
            provenance=_observed(),
        )
    )
    processor = FakeFeedbackProcessor()
    loop = _loop(memory=memory, feedback=processor, resolution_limit=3)

    await loop.learn(_correction("ordered espresso this morning"))

    assert processor.last_event.memory_kind is MemoryKind.SEMANTIC


async def test_a_failing_resolution_read_propagates_with_nothing_proposed() -> None:
    """§3: the resolution has no degraded mode, and both halves are asserted.

    A test that only checked the call raised would pass an implementation that fell
    through to §5 on a failed read — so this asserts the processor was never called
    and the store holds nothing. §5's fallback answers "the store looked and holds
    nothing", a fact; it may not be made to answer "the store could not look", which
    is not one, and a correction filed in a drawer chosen by a failure is precisely
    the silent mis-filing ADR-0122 ends. ``learn`` deliberately does not copy
    ``respond`` here: a turn degrades and says so, because an answer with less context
    is still an answer.
    """
    memory = _FailingSearchStore(now=_clock)
    processor = FakeFeedbackProcessor()
    loop = _loop(memory=memory, feedback=processor)

    with pytest.raises(MemoryStoreError, match="retrieval is unavailable"):
        await loop.learn(_correction("the office is in Boston"))

    assert processor.call_count == 0, "nothing was proposed"
    assert await memory.export() == [], "and nothing was written"


async def test_a_processor_proposing_nothing_for_a_resolved_kind_surfaces() -> None:
    """§7's second clause: an empty answer to a *resolved* event is a mis-wiring.

    The kind was chosen from :data:`RESOLUTION_KINDS` **because** the wired processor
    is required to mint it (§3's composition-root obligation). An empty sequence
    therefore says the root wired one that does not, and reporting it as "no update
    proposed" would drop a correction on the strength of a wiring mistake — the same
    silent loss ADR-0122 exists to remove, one layer down. That is what makes an
    untypeable obligation enforceable: not checked at wiring time, and not survivable
    at use time.
    """
    loop = _loop(feedback=FakeFeedbackProcessor([]))

    with pytest.raises(RuntimeError, match="RESOLUTION_KINDS"):
        await loop.learn(_correction("the office is in Boston"))


async def test_a_pinned_deferred_kind_still_returns_an_empty_outcome() -> None:
    """§7's second clause, other half — the two cases must not be collapsed.

    A **pinned** ``PROCEDURAL`` is a user asking for something the deterministic
    processor does not yet build (ADR-0009 §6), and reporting that nothing was
    proposed is the honest answer that ADR ratified. It looks identical at the seam to
    the mis-wiring above and means the opposite, so the pin is what separates them.
    """
    loop = _loop(feedback=FakeFeedbackProcessor([]))

    outcomes = await loop.learn(
        _correction("run the backup like this", memory_kind=MemoryKind.PROCEDURAL)
    )

    assert outcomes == ()


# --------------------------------------------------------------------------- #
# Tuning                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("retrieval_limit", [0, -1])
def test_tuning_that_would_silently_disable_retrieval_is_refused(retrieval_limit: int) -> None:
    """A stage turned off while the loop still reports health is refused up front.

    The conflict half of this check moved to ``MemoryIngestor`` with the values
    it guards (ADR-0028 §4a); ``tests/memory/test_ingest.py`` asserts it there.
    """
    with pytest.raises(ValueError, match="retrieval_limit must be at least 1"):
        _loop_with(retrieval_limit=retrieval_limit)


async def test_tuning_accepts_the_smallest_useful_limit() -> None:
    """1 is the smallest retrieval limit that retrieves anything at all."""
    loop = _loop_with(retrieval_limit=1)

    result = await loop.respond("hello")

    assert result.goal.statement == "hello"


@pytest.mark.parametrize("limit", [1.5, float("inf"), True, "5"])
def test_tuning_refuses_a_limit_that_is_not_an_integer(limit: object) -> None:
    """A non-integral limit reaches the store, where slicing by it raises."""
    with pytest.raises(TypeError, match="must be an integer"):
        _loop_with(retrieval_limit=limit)  # type: ignore[arg-type]  # deliberately invalid


@pytest.mark.parametrize("resolution_limit", [0, -1])
def test_tuning_that_would_silently_disable_the_resolution_is_refused(
    resolution_limit: int,
) -> None:
    """The sharper version of the same failure (ADR-0122 §3).

    A non-positive limit makes ``search`` match nothing by contract, so **every**
    unpinned correction would take §5's fallback and land as ``SEMANTIC`` — the
    pre-ADR defect, restored by a number, reported as success, and indistinguishable
    at every surface from a store that genuinely holds no target.
    """
    with pytest.raises(ValueError, match="resolution_limit must be at least 1"):
        _loop_with(resolution_limit=resolution_limit)


@pytest.mark.parametrize("limit", [1.5, float("inf"), True, "5"])
def test_tuning_refuses_a_resolution_limit_that_is_not_an_integer(limit: object) -> None:
    """Guarded exactly as the turn's is, and for the same reason."""
    with pytest.raises(TypeError, match="resolution_limit must be an integer"):
        _loop_with(resolution_limit=limit)  # type: ignore[arg-type]  # deliberately invalid


def _loop_with(
    *,
    retrieval_limit: int = 5,
    resolution_limit: int = _DEFAULT_RESOLUTION_LIMIT,
) -> LearningLoop:
    """Build a loop with the given tuning and canonical everything else."""
    memory = FakeMemoryStore(now=_clock)
    return LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=_writes(FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)),
        planner=FakePlanner(now=_clock),
        feedback=FakeFeedbackProcessor(),
        retrieval_limit=retrieval_limit,
        resolution_limit=resolution_limit,
        now=_clock,
    )


async def test_a_naive_clock_is_the_reading_stages_error() -> None:
    """Inverted by ADR-0026: the loop used to attribute UTC to this reading.

    ``core/errors.py`` defines no error for `orchestration`, so the failure is
    the *stage*'s: the clock is read while minting the turn's goal, which
    already raises ``PlanningError`` for a blank utterance.
    """
    naive_now = _NOW.replace(tzinfo=None)
    memory = FakeMemoryStore(now=_clock)
    loop = LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=_writes(FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)),
        planner=FakePlanner(now=_clock),
        feedback=FakeFeedbackProcessor(),
        now=lambda: naive_now,
    )

    with pytest.raises(PlanningError, match="LearningLoop"):
        await loop.respond("book the flight")
