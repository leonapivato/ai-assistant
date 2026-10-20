"""The observer's run: the queue, the limits and the observation record (ADR-0329 §7, §16).

Driven over the canonical fakes with scripted model routes. The reading, the two steps'
checks and the writes each have their own suite; this one holds what a run does with
them: which episodes are due and in what order, what is recorded as it goes, and what a
failure, the budget, the bound and a second run do.
"""

from __future__ import annotations

from datetime import timedelta

from observer_support import AT, Harness, episode, reply

from ai_assistant.core.types import (
    Memory,
    MemoryOperationKind,
    ObservationAttemptEnd,
    ObservationState,
    ObserverStep,
    SupportOrigin,
)
from ai_assistant.testing import FakeModelProvider

_PREFERENCE = "I prefer window seats when I fly."


async def _three(harness: Harness, *, text: str = _PREFERENCE) -> None:
    """Three episodes, a minute apart: with a window of two, the oldest has left it."""
    await harness.hold(
        episode("one", at=AT - timedelta(minutes=3), text=text),
        episode("two", at=AT - timedelta(minutes=2), text="What time is it?"),
        episode("three", at=AT - timedelta(minutes=1), text="Thanks."),
    )


def _scout(*parts: str) -> str:
    return reply(findings=[{"claim": "The user prefers window seats.", "rests_on": list(parts)}])


def _create(part: str = "P1") -> str:
    return reply(
        action="create",
        wording="The user prefers window seats.",
        supports=[{"part": part, "direction": "for", "backs_as_worded": True, "how_sure": "sure"}],
    )


async def test_an_episode_that_left_the_window_is_committed_and_recorded() -> None:
    """§7:1, §9, §12, §16:1: scout, commit, a memory written, the record processed."""
    harness = Harness()
    await _three(harness)
    observer = harness.observer(
        scout=FakeModelProvider.scripted(_scout("P1")),
        commit=FakeModelProvider.scripted(_create()),
    )

    outcome = await observer.run()

    assert outcome.processed == 1
    (record,) = await harness.plans.observations(["activation:one"])
    assert record.state is ObservationState.PROCESSED
    (attempt,) = record.attempts
    assert attempt.end is ObservationAttemptEnd.FINISHED
    assert [call.step for call in attempt.calls] == [ObserverStep.SCOUT, ObserverStep.COMMIT]
    (finding,) = record.findings
    assert finding.outcome is not None
    (write,) = finding.outcome.writes
    assert write.operations == (MemoryOperationKind.CREATE,)
    stored = await harness.memory.get(write.memory)
    assert isinstance(stored, Memory)
    assert stored.content == "The user prefers window seats."
    (support,) = stored.supports
    assert support.origin is SupportOrigin.USER_MESSAGE
    assert support.when == AT - timedelta(minutes=3)
    assert support.added_by.value == "observer"
    assert await harness.plans.observations(["activation:two", "activation:three"]) == ()
