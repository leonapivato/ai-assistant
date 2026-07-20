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

from ai_assistant.core.errors import ContextError, MemoryStoreError, PlanningError
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
from ai_assistant.orchestration import LearningLoop
from ai_assistant.testing import (
    FakeContextProvider,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakePlanner,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import (
        ContextProvider,
        FeedbackProcessor,
        MemoryPolicy,
        MemoryStore,
        Planner,
    )
    from ai_assistant.core.types import ActionPlan, Goal, MemoryRecord

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
    ) -> list[MemoryRecord]:
        """Fail the way a real store fails."""
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


def _loop(
    *,
    context: ContextProvider | None = None,
    memory: MemoryStore | None = None,
    policy: MemoryPolicy | None = None,
    planner: Planner | None = None,
    feedback: FeedbackProcessor | None = None,
) -> LearningLoop:
    """Build a loop from canonical fakes, with a fixed clock and stable ids.

    Parameters are typed by the Protocols, not the fakes, so a test can swap in
    a narrower double (see :class:`_FailingPlanner`) without a cast.
    """
    return LearningLoop(
        context=context or FakeContextProvider(),
        memory=memory or FakeMemoryStore(now=_clock),
        policy=policy or FakeMemoryPolicy(),
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
    assert outcome.decision.kind is MemoryDecisionKind.ACCEPT
    assert outcome.record_id is not None

    second = await loop.respond("draft a concise reply to Dana")

    assert [record.id for record in second.memories] == [outcome.record_id]
    learned = second.memories[0]
    assert isinstance(learned, PreferenceMemory)
    assert learned.preference == "prefers concise replies"
    # The planner did not merely have it available — it was handed it.
    assert [record.id for record in planner.calls[1][2]] == [outcome.record_id]
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
        policy=FakeMemoryPolicy(),
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

    assert outcome.record_id is not None
    assert await memory.get(outcome.record_id) is not None


async def test_learn_writes_nothing_when_the_processor_proposes_nothing() -> None:
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, feedback=FakeFeedbackProcessor([]))

    assert await loop.learn(_preference_feedback()) == ()
    assert await memory.export() == []


async def test_learn_reports_a_rejection_without_writing() -> None:
    memory = FakeMemoryStore(now=_clock)
    loop = _loop(memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.REJECT))

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.decision.kind is MemoryDecisionKind.REJECT
    assert outcome.record_id is None
    assert await memory.export() == []


async def test_learn_stamps_expiry_on_a_temporary_store() -> None:
    memory = FakeMemoryStore(now=_clock)
    ttl = timedelta(hours=6)
    loop = _loop(
        memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY, ttl=ttl)
    )

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.record_id is not None
    stored = await memory.get(outcome.record_id)
    assert stored is not None
    assert stored.expires_at == _NOW + ttl


async def test_learn_reports_a_merge_without_applying_it() -> None:
    """MERGE is memory's own semantics; this loop reports it rather than forking it.

    Documented in ADR-0022 §4 and tracked as issue #103: folding two records
    lives in ``MemoryIngestor``, which golden rule 1 forbids importing here.
    """
    memory = FakeMemoryStore(now=_clock)
    existing = PreferenceMemory(
        id="pref-existing",
        content="prefers concise replies",
        preference="prefers concise replies",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
    )
    await memory.add(existing)
    loop = _loop(memory=memory, policy=FakeMemoryPolicy(MemoryDecisionKind.MERGE))

    [outcome] = await loop.learn(_preference_feedback())

    assert outcome.decision.kind is MemoryDecisionKind.MERGE
    assert outcome.decision.merge_into == "pref-existing"
    assert outcome.record_id is None
    assert [record.id for record in await memory.export()] == ["pref-existing"]


async def test_learn_offers_the_policy_the_conflicting_records() -> None:
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        PreferenceMemory(
            id="pref-existing",
            content="prefers concise replies",
            preference="prefers concise replies",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
            ),
        )
    )
    policy = FakeMemoryPolicy()
    loop = _loop(memory=memory, policy=policy)

    await loop.learn(_preference_feedback())

    assert [record.id for record in policy.calls[0].conflicts] == ["pref-existing"]
    # The proposal handed to the policy names them too, so a decision is
    # auditable against what it ruled on.
    assert policy.last_proposal.conflicts == ["pref-existing"]


async def test_learn_ignores_a_conflict_below_the_threshold() -> None:
    memory = FakeMemoryStore(now=_clock)
    await memory.add(
        PreferenceMemory(
            id="pref-unrelated",
            content="prefers window seats on long flights",
            preference="prefers window seats on long flights",
            provenance=Provenance(
                source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW
            ),
        )
    )
    policy = FakeMemoryPolicy()
    loop = _loop(memory=memory, policy=policy)

    await loop.learn(_preference_feedback())

    assert policy.calls[0].conflicts == ()


async def test_learn_does_not_treat_the_proposal_itself_as_a_conflict() -> None:
    """A record cannot conflict with the version of it being re-proposed."""
    memory = FakeMemoryStore(now=_clock)
    event = _preference_feedback()
    policy = FakeMemoryPolicy()
    loop = _loop(memory=memory, policy=policy)

    await loop.learn(event)  # writes the record under a derived id
    await loop.learn(event)  # the same feedback again, so the same id

    assert policy.calls[1].conflicts == ()


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

    assert [outcome.record_id for outcome in outcomes] == ["pref-0", "pref-1", "pref-2"]


async def test_learn_propagates_a_store_failure() -> None:
    loop = _loop(memory=_FailingSearchStore(now=_clock))

    with pytest.raises(MemoryStoreError, match="retrieval is unavailable"):
        await loop.learn(_preference_feedback())
