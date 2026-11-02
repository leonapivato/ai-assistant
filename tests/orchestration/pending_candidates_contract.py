"""Shared obligations of ``AssistantEngine.pending_candidates`` (ADR-0329 §18:1-§18:2).

Every implementation answers the panel's read from the same records: the most recent
episodes, each one's recorded ``remember`` calls joined to the effect records that
show them done (§3:3), an episode the observer has settled left out (§16:2). And every
implementation answers none where ``remember`` records no candidate, which is every
deployment until the observer is wired (§19:3): a subject is handed to the suite
built one way or the other, since which way is the composition root's and no call on
the surface changes it.

A mixin, as ``episode_inspection_contract`` is, so the engine, the canonical fake and
the wire client each bind it in the file that binds the rest of the suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    ActionRequest,
    ActivationEffect,
    ActivationUnderstanding,
    ChannelContext,
    ControllerRule,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    NewConversation,
    ObservationRecord,
    ObservationState,
    PendingCandidate,
    PlanningRound,
    ProcessingReason,
    ProcessingStatus,
    ProposedCall,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    ToolOutcome,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.orchestration.authorizer import values_digest
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import (
    OWNERS_WORDS,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeMemoryStore, FakePlanStore

#: The contract limit each subject is built at: room for a few candidates, and small
#: enough that two long facts are past it, each within the fact's own bound.
PENDING_LIMIT: Final = 2048

#: The instant each subject's stores are clocked at, and the episodes occur before.
PENDING_AT: Final = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

#: More newer episodes than one page of the episode listing holds, so an older one is
#: reached only by a read that continues past the first page.
_NEWER: Final = 120


@dataclass(frozen=True, slots=True)
class PendingCandidatesSubject:
    """An engine and the two stores its read joins, seeded from the test process.

    Attributes:
        engine: The subject under test.
        memory: The store the episodes are held in.
        plans: The plan store the effect records and observation records are held in.
    """

    engine: AssistantEngine
    memory: FakeMemoryStore
    plans: FakePlanStore


def _arguments(fact: str) -> dict[str, Any]:
    return {"fact": fact, "why": "it is about their travel", "rests_on_this_stimulus": True}


async def hold_episode(
    subject: PendingCandidatesSubject,
    activation: str,
    *facts: str,
    age: timedelta = timedelta(hours=1),
    done: bool = True,
) -> str:
    """Hold a frozen episode whose one round recorded a ``remember`` call per fact.

    Each call's effect record is claimed and finished as acting would leave it:
    succeeded where ``done``, failed otherwise.

    Returns:
        The episode's id.
    """
    episode = f"activation:{activation}"
    round_id = f"round:{activation}"
    calls = tuple(
        ProposedCall(call_id=f"c{index}", name="remember_fact", arguments=_arguments(fact))
        for index, fact in enumerate(facts, start=1)
    )
    at = PENDING_AT - age
    await _hold(subject, activation, at, PlanningRound(id=round_id, recorded_at=at, calls=calls))
    for index, fact in enumerate(facts, start=1):
        filled = {**_arguments(fact), "episode": episode, "rests_on_outside_content": False}
        effect = ActivationEffect(
            id=f"effect:{activation}:{index}",
            activation_id=activation,
            round=round_id,
            capability="remember_fact",
            values_digest=values_digest(ActionRequest(tool=REMEMBER_CANDIDATE, parameters=filled)),
            decision_id=f"decision:{activation}:{index}",
            claimed_at=at,
        )
        await subject.plans.claim_activation_effect(effect, match=None)
        if done:
            await subject.plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)
        else:
            await subject.plans.finish_activation_effect(
                effect.id, ToolOutcome.FAILED, reason="refused"
            )
    return episode


async def _hold(
    subject: PendingCandidatesSubject,
    activation: str,
    at: datetime,
    planned: PlanningRound,
    *,
    understanding: ActivationUnderstanding | None = None,
) -> str:
    """Hold one frozen episode of ``activation`` with one round, occurring at ``at``."""
    episode = f"activation:{activation}"
    record = EpisodeProcessingRecord(
        activation_id=activation,
        started_at=at,
        ended_at=at,
        trigger=RecordedChannelTrigger(
            target=NewConversation(),
            channel=None,
            payload=RecordedTextInput(text="the words they wrote"),
            context=ChannelContext(),
            reply=WholeTextReply(),
            parties=OWNERS_WORDS,
        ),
        status=ProcessingStatus.COMPLETED,
        reason=ProcessingReason.RETURNED,
        understanding=() if understanding is None else (understanding,),
        understanding_omitted=UnderstandingOmission.NOT_REACHED if understanding is None else None,
        stages=ended_pass(at, ControllerRule.NOTHING_DUE),
        rounds=(planned,),
    )
    await subject.memory.add(
        EpisodicMemory(
            id=episode,
            content="",
            provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=at),
            occurred_at=at,
            outcome="Noted.",
            processing_record=record,
        )
    )
    return episode


class PendingCandidatesContract:
    """The panel's read through the engine, the fake and the wire client alike."""

    @pytest.fixture
    def pending_candidates_subject(self) -> PendingCandidatesSubject:
        """Override with an implementation of the panel's read.

        Built at :data:`PENDING_LIMIT`, with its stores clocked at :data:`PENDING_AT`.
        """
        raise NotImplementedError

    async def test_a_done_call_of_an_unprocessed_episode_is_pending(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        """§18:1: each pending candidate by its fact, with the episode it belongs to."""
        subject = pending_candidates_subject
        episode = await hold_episode(subject, "a1", "prefers window seats")

        held = await subject.engine.pending_candidates()

        assert held == (PendingCandidate(episode_id=episode, fact="prefers window seats"),)

    async def test_the_most_recent_episode_comes_first_and_calls_keep_their_order(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        subject = pending_candidates_subject
        older = await hold_episode(subject, "a1", "lives in Lisbon", age=timedelta(days=2))
        newer = await hold_episode(subject, "a2", "has a dog", "the dog is called Rui")

        held = await subject.engine.pending_candidates()

        assert held == (
            PendingCandidate(episode_id=newer, fact="has a dog"),
            PendingCandidate(episode_id=newer, fact="the dog is called Rui"),
            PendingCandidate(episode_id=older, fact="lives in Lisbon"),
        )

    @pytest.mark.parametrize(
        "state", [ObservationState.PROCESSED, ObservationState.SKIPPED, ObservationState.STUCK]
    )
    async def test_an_episode_the_observer_settled_shows_none(
        self, pending_candidates_subject: PendingCandidatesSubject, state: ObservationState
    ) -> None:
        """§16:2: processed, skipped or stuck, the episode's candidates are not pending."""
        subject = pending_candidates_subject
        settled = await hold_episode(subject, "a1", "lives in Lisbon")
        waiting = await hold_episode(subject, "a2", "has a dog")
        await subject.plans.write_observation(
            ObservationRecord(episode=settled, state=state), expected_revision=0
        )
        await subject.plans.write_observation(
            ObservationRecord(episode=waiting, state=ObservationState.WAITING),
            expected_revision=0,
        )

        held = await subject.engine.pending_candidates()

        assert held == (PendingCandidate(episode_id=waiting, fact="has a dog"),)

    async def test_a_call_not_done_is_no_candidate(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        """§3:3: a candidate is a call its effect record shows done."""
        subject = pending_candidates_subject
        await hold_episode(subject, "a1", "lives in Lisbon", done=False)

        assert await subject.engine.pending_candidates() == ()

    async def test_none_held_is_an_empty_tuple(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        held = await pending_candidates_subject.engine.pending_candidates()

        assert held == ()
        assert isinstance(held, tuple)

    async def test_an_episode_behind_a_full_page_of_newer_ones_is_still_read(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        """§18:1 has no horizon: the panel shows every pending candidate, however old."""
        subject = pending_candidates_subject
        oldest = await hold_episode(subject, "oldest", "lives in Lisbon", age=timedelta(days=30))
        for index in range(_NEWER):
            await hold_episode(subject, f"newer-{index:03}", age=timedelta(minutes=index + 1))

        held = await subject.engine.pending_candidates()

        assert held == (PendingCandidate(episode_id=oldest, fact="lives in Lisbon"),)

    async def test_a_result_past_the_limit_is_refused(
        self, pending_candidates_subject: PendingCandidatesSubject
    ) -> None:
        """ADR-0085 §8c: the size limit binds this read's result as every other's."""
        subject = pending_candidates_subject
        await hold_episode(subject, "a1", "x" * (PENDING_LIMIT // 2), "y" * (PENDING_LIMIT // 2))

        with pytest.raises(OversizedValueError):
            await subject.engine.pending_candidates()
