"""Tests for the closed learning loop (ADR-0022).

Every collaborator is a canonical fake from ``ai_assistant.testing``, so these
tests exercise the wiring without importing any subsystem's internals (CLAUDE.md
golden rule 1) — which is exactly what the engine under test is required to do.

The one that matters most is :func:`test_a_learned_preference_is_reused_on_a_later_turn`:
the *closed* part of the loop, and the roadmap's acceptance criterion for the
first vertical.
"""

from __future__ import annotations

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


def _loop_with(*, retrieval_limit: int) -> LearningLoop:
    """Build a loop with the given retrieval tuning and canonical everything else."""
    memory = FakeMemoryStore(now=_clock)
    return LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writes=_writes(FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=_clock)),
        planner=FakePlanner(now=_clock),
        feedback=FakeFeedbackProcessor(),
        retrieval_limit=retrieval_limit,
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
