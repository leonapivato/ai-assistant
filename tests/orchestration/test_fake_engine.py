"""The canonical FakeAssistantEngine passes the shared AssistantEngine suite.

This is what lets a client lane trust ``ai_assistant.testing.FakeAssistantEngine``
as a stand-in for the engine: it is held to the same contract as the concrete
:class:`~ai_assistant.orchestration.engine.Engine` (``tests/orchestration/
test_engine_contract.py``).

**It is also the pair ADR-0084 §4's size clause needs.** That clause says the
limit is enforced by "*every* implementation", with the conformance suite as what
holds them to it — and until this fake exists there is only one implementation, so
the clause has nothing to bind. ADR-0087 §6 makes exactly that argument for
ratifying the canonical encoding before this change rather than with the hub.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from assistant_engine_contract import (
    _SOURCE,
    _TINY_LIMIT,
    AssistantEngineContract,
    page_after_mutating_the_filter,
)

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    BeliefBand,
    BeliefSummary,
    ContinuationToken,
    ConversationSummary,
    MemoryKind,
    QuestionState,
    TurnOutcome,
)
from ai_assistant.testing import FakeAssistantEngine

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import Belief, Identifier


class TestFakeAssistantEngineContract(AssistantEngineContract):
    """The canonical fake, held to the shared contract."""

    @pytest.fixture
    def engine(self) -> AssistantEngine:
        """One fake engine at the ordinary contract limit."""
        return FakeAssistantEngine()

    @pytest.fixture
    def tiny_engine(self) -> AssistantEngine:
        """The same implementation, with the limit small enough to reach."""
        return FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT)

    @pytest.fixture
    def granting_engine(self) -> AssistantEngine:
        """One fake engine holding a single grantable source with a location."""
        engine = FakeAssistantEngine()
        engine.hold_source(_SOURCE, location="/srv/calendar.ics")
        return engine

    @pytest.fixture
    def parked_engine(self) -> AssistantEngine:
        """One fake engine holding a single answerable park."""
        engine = FakeAssistantEngine()
        engine.park("h-1")
        return engine


# --- what the fake offers beyond the contract ------------------------------
# Its own tests, not the suite's: a canonical fake has to be *usable* as well as
# conformant, and these pin the setters a consumer's test will reach for.


async def test_a_held_belief_is_listed_and_readable() -> None:
    """``hold`` seeds the inspection surface without going through ``learn``."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="the office is in Boston")
    page = await engine.beliefs()
    assert [summary.id for summary in page] == ["rec-1"]
    detail = await engine.belief("rec-1")
    assert detail is not None
    assert detail.content == "the office is in Boston"


async def test_the_two_question_enumerations_stay_disjoint() -> None:
    """ADR-0078 §8: an interrupted question is a second list all the way up.

    Offering it beside the answerable ones would present a claim that cannot be
    taken — the system does not know whether the memory write landed.
    """
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    engine.ask("q-2", content="prefers metric", state=QuestionState.INTERRUPTED)
    assert [q.id for q in await engine.questions()] == ["q-1"]
    assert [q.id for q in await engine.interrupted_questions()] == ["q-2"]


async def test_accepting_a_question_leaves_a_record_live() -> None:
    """An applied answer names what is now live (ADR-0078 §8)."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    outcome = await engine.answer("q-1", accept=True)
    assert outcome.record_id is not None
    assert await engine.belief(outcome.record_id) is not None
    assert await engine.questions() == ()


async def test_declining_a_question_writes_nothing() -> None:
    """A rejection needs no claim, because it writes nothing."""
    engine = FakeAssistantEngine()
    engine.ask("q-1", content="works from home", state=QuestionState.OPEN)
    outcome = await engine.answer("q-1", accept=False)
    assert outcome.record_id is None
    assert await engine.beliefs() == ()


async def test_a_parked_confirmation_is_recovered_and_then_resolvable() -> None:
    """ADR-0052 §1's enumerate-and-re-mint, in miniature."""
    engine = FakeAssistantEngine()
    engine.park("h-1")
    pending = await engine.pending_confirmations()
    assert len(pending) == 1
    await engine.resume(pending[0].token, approved=True, timeout=timedelta(seconds=30))
    assert await engine.pending_confirmations() == ()


async def test_the_filters_compose_by_conjunction() -> None:
    """A belief is listed when its band is selected *and* its kind is (ADR-0073 §2)."""
    engine = FakeAssistantEngine()
    engine.hold("rec-1", content="a", kind=MemoryKind.SEMANTIC, band=BeliefBand.ASSERTED)
    engine.hold("rec-2", content="b", kind=MemoryKind.PREFERENCE, band=BeliefBand.DERIVED)
    listed = await engine.beliefs(bands=[BeliefBand.ASSERTED], kinds=[MemoryKind.PREFERENCE])
    assert listed == ()
    listed = await engine.beliefs(bands=[BeliefBand.DERIVED], kinds=[MemoryKind.PREFERENCE])
    assert [summary.id for summary in listed] == ["rec-2"]


# --- the suite discriminates ------------------------------------------------
# Each clause below is asserted by watching a deliberately non-conforming subject
# *fail* the very scenario the contract runs. A conformance test nobody has seen
# fail is a test that agrees with whatever it was written against; these are what
# make the six clauses evidence rather than description.


class _LazyFilterEngine(FakeAssistantEngine):
    """An engine that reads its filter *after* suspending — the §3d violation."""

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """Suspend first, then read ``bands`` — so a mid-call mutation is visible."""
        await asyncio.sleep(0)
        return await super().beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)


async def test_the_materialisation_clause_catches_a_lazy_filter() -> None:
    """The scenario the contract runs really does separate the two behaviours."""
    engine = _LazyFilterEngine()
    engine.hold("rec-1", content="the office is in Boston")
    page, control = await page_after_mutating_the_filter(engine)
    assert control != ()
    assert page == ()  # the emptied list was read after the suspension


class _UnlimitedEngine(FakeAssistantEngine):
    """An engine that measures its arguments and never its results — the §8c gap."""

    def _checked[T](self, result: T, method: str) -> T:
        """Skip the result check the contract requires of every implementation."""
        return result


async def test_the_size_clause_catches_an_unchecked_result() -> None:
    """An implementation that measured only its arguments would slip through §8c.

    ADR-0084 §4 insists on **both** directions precisely so a client is never
    silently less capable than the engine it stands in for; this is the half that
    would otherwise go unnoticed, because an oversized result is only visible to
    whoever tried to send it.

    **This is the scenario the suite runs**, down to the listing call whose request
    payload is twelve bytes — so what it demonstrates is that the suite's case is
    load-bearing rather than incidentally passing. An earlier draft asserted the
    same clause with an oversized *event*, which both implementations refused on
    the argument object before any result existed: an engine with no result check
    at all passed it.
    """

    async def _page(engine: FakeAssistantEngine) -> object:
        for index in range(6):
            engine.hold(f"rec-{index}", content=f"the office is in Boston, building {index}")
        return await engine.beliefs()

    with pytest.raises(OversizedValueError):
        await _page(FakeAssistantEngine(max_payload_bytes=_TINY_LIMIT))
    assert await _page(_UnlimitedEngine(max_payload_bytes=_TINY_LIMIT))  # nothing refused it


class _PermissiveEngine(FakeAssistantEngine):
    """An engine that admits a blank identifier — the §3c/§9 violation."""

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Look the id up without validating it first."""
        return self.beliefs_held.get(record_id)


async def test_the_identifier_clause_catches_a_permissive_engine() -> None:
    """A blank id must be refused, not answered ``None``.

    The distinction is what stops "no such belief" — a true sentence about a call
    the caller never meant to make — from standing in for a refusal.
    """
    with pytest.raises(ValueError, match=r"\w"):
        await FakeAssistantEngine().belief("  ")
    assert await _PermissiveEngine().belief("  ") is None  # nothing refused it


async def test_the_identifier_clause_catches_an_engine_that_does_not_strip() -> None:
    """The normalisation half, which a "reject blank" rule alone would leave open."""
    conforming = FakeAssistantEngine()
    conforming.hold("rec-1", content="the office is in Boston")
    assert await conforming.belief("  rec-1  ") is not None

    permissive = _PermissiveEngine()
    permissive.hold("rec-1", content="the office is in Boston")
    assert await permissive.belief("  rec-1  ") is None  # the raw value was looked up


class _InsertionOrderEngine(FakeAssistantEngine):
    """An engine that lists conversations as they were created — the ADR-0074 §2 gap."""

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """Return them in insertion order, which is what a naive dict gives."""
        held = tuple(
            ConversationSummary(
                id=digest.id,
                started_at=digest.started_at,
                last_active_at=digest.started_at,
                last_turn_at=digest.last_turn_at,
            )
            for digest in self.conversations_held.values()
        )
        return held[offset : offset + limit]


async def test_the_ordering_clause_catches_insertion_order() -> None:
    """The suite's ordering case really does separate the two behaviours.

    Two conversations and no continuation is the shape where the two orders
    *disagree*: activity descending puts the newer first, insertion order puts the
    older first. Continuing the older one afterwards makes them agree again, which
    is why the suite asserts both halves — the second alone would pass against an
    engine that never ordered anything.
    """

    async def _listed(engine: FakeAssistantEngine) -> list[str]:
        await engine.converse("one", timeout=timedelta(seconds=30))
        await engine.converse("two", timeout=timedelta(seconds=30))
        return [one.id for one in await engine.recent_conversations()]

    assert await _listed(FakeAssistantEngine()) == ["c-2", "c-1"]
    assert await _listed(_InsertionOrderEngine()) == ["c-1", "c-2"]  # nothing ordered it


class _SteplessEngine(FakeAssistantEngine):
    """An engine whose resume carries no resolved step — the ADR-0085 §4 gap."""

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
    ) -> TurnOutcome:
        """Resolve the park and hand back nothing to render."""
        await super().resume(token, approved=approved, timeout=timeout)
        return TurnOutcome(turn=None)


async def test_the_resume_clause_catches_an_outcome_with_no_step() -> None:
    """A resume that carries neither a turn nor a step leaves a client nothing.

    ``turn`` is legitimately ``None`` on a recovered park, which is exactly why the
    step cannot be: between them they are the whole of what a resumption produced.
    """
    conforming = FakeAssistantEngine()
    conforming.park("h-1")
    resolved = await conforming.resume(
        ContinuationToken(handle="h-1"), approved=True, timeout=timedelta(seconds=30)
    )
    assert resolved.step is not None

    stepless = _SteplessEngine()
    stepless.park("h-1")
    empty = await stepless.resume(
        ContinuationToken(handle="h-1"), approved=True, timeout=timedelta(seconds=30)
    )
    assert empty.step is None  # nothing to render, and nothing refused it
