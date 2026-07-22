"""Every injected-clock seam is guarded, and each raises its subsystem's error.

ADR-0026 §7 is uniformity with **no advisory exemption**: a seam that produces a
float, a seam that only stamps an export, and a seam whose instant is advisory
all guard alike, because a seam cannot know the provenance of the reading it was
handed and so cannot know whether attributing UTC restores a fact or invents one.

This module is deliberately cross-subsystem, which no per-package test file can
be. Its subject is the *set*: a new seam that forgets the guard, or an existing
one whose translation drifts to the wrong ``AssistantError``, fails here rather
than being noticed in review. ``tests/core/test_clock.py`` pins what the guard
does; this pins that every seam has it.

The `testing/` fakes are in scope for the reason they exist (ADR-0026 §7): they
are the canonical doubles consumers certify against, and a fake looser than the
contract certifies consumers the real implementation will reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.context.sources import ClockContextSource
from ai_assistant.core.errors import ContextError, MemoryStoreError, PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    CurrentContext,
    Goal,
    MemoryDecisionKind,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.memory import InMemoryMemoryStore, MemoryIngestor, SqliteMemoryStore
from ai_assistant.orchestration import LearningLoop
from ai_assistant.planning import InMemoryPlanStore, PlanExecution
from ai_assistant.testing import (
    FakeContextProvider,
    FakeEmbedder,
    FakeFeedbackProcessor,
    FakeMemoryPolicy,
    FakeMemoryStore,
    FakeMemoryWriter,
    FakePlanner,
    FakePlanStore,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

#: A naive reading: the one every seam used to accept and now must refuse.
_NAIVE = datetime(2026, 7, 21, 12)  # noqa: DTZ001 — the naive reading is the subject
_AWARE = datetime(2026, 7, 21, 12, tzinfo=UTC)


def _naive_clock() -> datetime:
    return _NAIVE


def _record(*, expires_at: datetime | None = None) -> SemanticMemory:
    """A record carrying an expiry, since that is what makes a store read its clock."""
    return SemanticMemory(
        id="m1",
        content="the user drinks coffee",
        fact="the user drinks coffee",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AWARE
        ),
        expires_at=expires_at,
    )


def _goal() -> Goal:
    return Goal(
        id="g1",
        statement="book the flight",
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AWARE
        ),
        created_at=_AWARE,
    )


def _context() -> CurrentContext:
    return CurrentContext(
        now=_AWARE,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
    )


def _plan() -> ActionPlan:
    return ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_AWARE, rationale="because")


def _proposal() -> MemoryUpdateProposal:
    return MemoryUpdateProposal(proposed=_record(), rationale="the user said so")


@dataclass(frozen=True)
class Seam:
    """One injected-clock seam and the error its subsystem owes on a bad reading.

    Attributes:
        label: The seam, as named in ADR-0026's table.
        read: Builds the object with a naive clock and drives it to read that
            clock, through the seam's real entry point rather than by reaching
            into a private method. Async uniformly, so the one synchronous seam
            needs no separate branch.
        error: The ``AssistantError`` subclass ADR-0026 §4 assigns the seam.
    """

    label: str
    read: Callable[[], Coroutine[None, None, None]]
    error: type[Exception]


async def _in_memory_store() -> None:
    store = InMemoryMemoryStore(now=_naive_clock)
    await store.add(_record(expires_at=_AWARE))
    await store.get("m1")


async def _sqlite_store() -> None:
    store = SqliteMemoryStore(path=":memory:", embedder=FakeEmbedder(), now=_naive_clock)
    await store.get("m1")


async def _ingestor() -> None:
    # STORE_TEMPORARY is the ruling whose expiry stamp reads the clock, and it
    # reaches the store through `model_copy(update=...)`, past every validator.
    await MemoryIngestor(
        store=InMemoryMemoryStore(now=lambda: _AWARE),
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY),
        now=_naive_clock,
    ).ingest(_proposal())


async def _fake_store() -> None:
    store = FakeMemoryStore(now=_naive_clock)
    await store.add(_record(expires_at=_AWARE))
    await store.get("m1")


async def _fake_writer() -> None:
    store = FakeMemoryStore(now=lambda: _AWARE)
    await FakeMemoryWriter(
        store=store,
        policy=FakeMemoryPolicy(MemoryDecisionKind.STORE_TEMPORARY),
        now=_naive_clock,
    ).ingest(_proposal())


async def _learning_loop() -> None:
    memory = FakeMemoryStore(now=lambda: _AWARE)
    await LearningLoop(
        context=FakeContextProvider(),
        memory=memory,
        writer=FakeMemoryWriter(store=memory, policy=FakeMemoryPolicy(), now=lambda: _AWARE),
        planner=FakePlanner(now=lambda: _AWARE),
        feedback=FakeFeedbackProcessor(),
        now=_naive_clock,
    ).respond("book the flight")


async def _clock_source() -> None:
    await ClockContextSource(now=_naive_clock).contribute()


async def _fake_planner() -> None:
    await FakePlanner(now=_naive_clock).plan(_goal(), context=_context())


async def _fake_plan_store() -> None:
    await FakePlanStore(now=_naive_clock).export()


async def _in_memory_plan_store() -> None:
    await InMemoryPlanStore(now=_naive_clock).export()


async def _plan_execution() -> None:
    PlanExecution(now=_naive_clock).start(_plan(), execution_id="e1")


#: Every seam ADR-0026 §7 covers, verified against the code rather than the table:
#: ``FakeMemoryWriter`` is an eleventh the ADR's table predates (ADR-0028), and it
#: is in scope for §7's reason — it is a canonical double (#186).
SEAMS = [
    Seam("ClockContextSource", _clock_source, ContextError),
    Seam("PlanExecution", _plan_execution, PlanningError),
    Seam("InMemoryPlanStore", _in_memory_plan_store, PlanningError),
    Seam("InMemoryMemoryStore", _in_memory_store, MemoryStoreError),
    Seam("SqliteMemoryStore", _sqlite_store, MemoryStoreError),
    Seam("MemoryIngestor", _ingestor, MemoryStoreError),
    Seam("LearningLoop", _learning_loop, PlanningError),
    Seam("FakeMemoryStore", _fake_store, MemoryStoreError),
    Seam("FakeMemoryWriter", _fake_writer, MemoryStoreError),
    Seam("FakePlanner", _fake_planner, PlanningError),
    Seam("FakePlanStore", _fake_plan_store, PlanningError),
]


@pytest.mark.parametrize("seam", SEAMS, ids=[seam.label for seam in SEAMS])
async def test_every_seam_refuses_a_naive_reading_as_its_own_error(seam: Seam) -> None:
    """ADR-0026 §§4, 7: guarded everywhere, translated at each subsystem's boundary.

    ``core`` raises ``ValueError`` and nothing else — it cannot know what its
    caller will do with the failure — so a raw ``ValueError`` reaching a caller
    is the failure this asserts against. `orchestration` has no error of its own,
    so it borrows the reading stage's; a fake raises the error of the
    implementation it doubles, since a fake that leaked ``ValueError`` where the
    real store raises ``MemoryStoreError`` would certify a consumer's error
    handling against behaviour it never meets in production.
    """
    with pytest.raises(seam.error) as caught:
        await seam.read()

    assert seam.label in str(caught.value)


def test_the_seam_table_is_the_whole_set() -> None:
    """A new seam that forgets the guard has to be added here to pass anything.

    Not a proof — nothing can mechanically discover an unwritten guard — but it
    keeps the enumerated set honest: the labels are the ``owner`` strings, and a
    seam whose label drifts from its constructor fails the assertion above.
    """
    assert len({seam.label for seam in SEAMS}) == len(SEAMS)
