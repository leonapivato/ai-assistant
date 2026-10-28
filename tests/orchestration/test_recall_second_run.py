"""ADR-0308 §2: recall's second run, on what understanding found (as ADR-0353 §14:3 cues it).

The searches are scripted: each cue's text answers, per band, with the records and
scores a case sets, so what the run keeps, in what order and found by which cue is
read off the cases alone.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    RECALLED_ITEMS_MAX,
    BeliefBand,
    Memory,
    MemoryKind,
    MemorySearchResult,
    RecallCue,
    RecallOutcome,
)
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    UnboundedAudienceSupply,
)
from ai_assistant.orchestration.recall import RecallStage
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore
from ai_assistant.testing.memories import memory_in_band

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.orchestration.disclosure import TurnSupply
    from ai_assistant.orchestration.recall import Recalled

AT: Final = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
MEANING: Final = "the user asks when their dentist appointment is"
GAP_A: Final = "which dentist"
GAP_B: Final = "which appointment"


def _fact(memory_id: str, band: BeliefBand = BeliefBand.ASSERTED) -> Memory:
    return memory_in_band(memory_id, memory_id, band)


ASSERTED: Final = BeliefBand.ASSERTED
DERIVED: Final = BeliefBand.DERIVED


@dataclass(frozen=True)
class _Search:
    query: str
    limit: int
    kinds: tuple[MemoryKind, ...]
    band: BeliefBand


@dataclass
class _Scripted(FakeMemoryStore):
    """Each query answers with its scripted records of the band asked, scored as set."""

    answers: dict[str, list[tuple[Memory, float]]] = field(default_factory=dict)
    searches: list[_Search] = field(default_factory=list)
    fail_on: str | None = None
    slow: bool = False

    def __post_init__(self) -> None:
        super().__init__(now=lambda: AT)

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
        **_: Any,
    ) -> MemorySearchResult:
        assert bands is not None
        assert kinds is not None
        (band,) = bands
        self.searches.append(_Search(query, limit, tuple(kinds), band))
        if self.slow:
            await asyncio.sleep(10)
        if query == self.fail_on:
            msg = "down"
            raise MemoryStoreError(msg)
        records = tuple(
            record.model_copy(update={"score": score})
            for record, score in self.answers.get(query, [])
            if record.band is band
        )
        return MemorySearchResult(records=records[:limit], capped=False)


def _stage(
    memory: FakeMemoryStore, *, limit: int = 3, budget: timedelta = timedelta(seconds=2)
) -> RecallStage:
    return RecallStage(
        memory=memory, stories=FakeStoryStore(), threshold=0.5, limit=limit, budget=budget
    )


async def _again(  # noqa: PLR0913 — one knob per argument a case varies
    stage: RecallStage,
    gaps: Sequence[str] = (GAP_A,),
    *,
    meaning: str = MEANING,
    passed_over: frozenset[str] = frozenset(),
    cap: int = 8,
    audience: TurnSupply = BOUNDED,
    deadline: float = math.inf,
) -> Recalled:
    return await stage.recall_again(
        meaning,
        gaps,
        audience=audience,
        deadline=deadline,
        passed_over=passed_over,
        cap=cap,
    )


def _ids(recalled: Recalled) -> list[str]:
    assert len(recalled.scores) == len(recalled.result.items)
    return [item.id for item in recalled.result.items]


# --- §2:2: the cues -----------------------------------------------------------------------


async def test_the_meaning_and_each_distinct_gap_is_searched_on_its_own_per_band() -> None:
    memory = _Scripted()
    recalled = await _again(_stage(memory), (GAP_A, GAP_B, GAP_A))
    assert [(one.query, one.band) for one in memory.searches] == [
        (text, band)
        for text in (MEANING, GAP_A, GAP_B)
        for band in (BeliefBand.ASSERTED, BeliefBand.ATTESTED, BeliefBand.DERIVED)
    ]
    assert recalled.result.outcome is RecallOutcome.NOTHING_FOUND
    assert recalled.result.cues == (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP)


async def test_with_no_unclear_point_the_meaning_is_the_one_cue() -> None:
    memory = _Scripted(answers={MEANING: [(_fact("m"), 0.9)]})
    recalled = await _again(_stage(memory), ())
    assert {one.query for one in memory.searches} == {MEANING}
    assert recalled.result.cues == (RecallCue.UNDERSTOOD_MEANING,)
    assert recalled.result.items[0].found_by == (RecallCue.UNDERSTOOD_MEANING,)


async def test_a_gap_that_is_the_meaning_is_searched_once_and_found_by_both() -> None:
    memory = _Scripted(answers={MEANING: [(_fact("m"), 0.9)]})
    recalled = await _again(_stage(memory), (MEANING,))
    assert [one.query for one in memory.searches] == [MEANING] * 3
    assert recalled.result.items[0].found_by == (
        RecallCue.UNDERSTOOD_MEANING,
        RecallCue.UNDERSTOOD_GAP,
    )


# --- §2:3: per cue, under the first run's threshold and limit, passing over ----------------


async def test_each_cue_keeps_under_the_threshold_and_its_own_limit() -> None:
    memory = _Scripted(
        answers={
            MEANING: [(_fact(f"m{n}"), 0.9) for n in range(4)] + [(_fact("low"), 0.4)],
            GAP_A: [(_fact(f"p{n}"), 0.9) for n in range(4)],
        }
    )
    recalled = await _again(_stage(memory, limit=2))
    assert _ids(recalled) == ["m0", "m1", "p0", "p1"]


async def test_what_the_windows_hold_and_the_first_run_kept_is_passed_over() -> None:
    memory = _Scripted(
        answers={MEANING: [(_fact("window"), 0.95), (_fact("first"), 0.9), (_fact("new"), 0.8)]}
    )
    recalled = await _again(_stage(memory), (), passed_over=frozenset({"window", "first"}))
    assert _ids(recalled) == ["new"]


async def test_each_band_search_asks_for_the_limit_plus_what_is_passed_over() -> None:
    memory = _Scripted()
    await _again(_stage(memory, limit=3), passed_over=frozenset({"a", "b", "c"}))
    assert {one.limit for one in memory.searches} == {6}


# --- §2:4: the cap, in band order, each record once -----------------------------------------


async def test_the_cues_records_are_kept_in_band_order_meaning_first_within_a_band() -> None:
    memory = _Scripted(
        answers={
            MEANING: [(_fact("m-derived", DERIVED), 0.99), (_fact("m-asserted"), 0.6)],
            GAP_A: [(_fact("a-derived", DERIVED), 0.99), (_fact("a-asserted"), 0.7)],
            GAP_B: [(_fact("b-asserted"), 0.9)],
        }
    )
    recalled = await _again(_stage(memory), (GAP_A, GAP_B))
    assert _ids(recalled) == ["m-asserted", "a-asserted", "b-asserted", "m-derived", "a-derived"]


async def test_the_cap_bounds_the_total_in_band_order() -> None:
    memory = _Scripted(
        answers={
            MEANING: [(_fact("m-derived", DERIVED), 0.99), (_fact("m-asserted"), 0.6)],
            GAP_A: [(_fact("a-asserted"), 0.7)],
        }
    )
    recalled = await _again(_stage(memory), cap=2)
    assert _ids(recalled) == ["m-asserted", "a-asserted"]


async def test_a_record_two_cues_found_is_kept_once_found_by_both_kinds() -> None:
    shared = _fact("shared")
    memory = _Scripted(
        answers={
            MEANING: [(shared, 0.6)],
            GAP_A: [(shared, 0.9), (_fact("gap-only"), 0.8)],
        }
    )
    recalled = await _again(_stage(memory))
    assert _ids(recalled) == ["shared", "gap-only"]
    first, second = recalled.result.items
    assert first.found_by == (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP)
    assert second.found_by == (RecallCue.UNDERSTOOD_GAP,)
    assert recalled.scores == (0.9, 0.8)


@pytest.mark.parametrize("cap", [0, RECALLED_ITEMS_MAX + 1])
async def test_a_cap_outside_the_types_ceiling_is_refused(cap: int) -> None:
    with pytest.raises(ValueError, match="ADR-0308"):
        await _again(_stage(_Scripted()), cap=cap)


# --- §2:6: the audience rule -----------------------------------------------------------------


async def test_an_unbounded_audience_searches_semantic_records_alone() -> None:
    memory = _Scripted()
    await _again(_stage(memory), audience=UNBOUNDED)
    assert {one.kinds for one in memory.searches} == {(MemoryKind.MEMORY,)}


async def test_a_bounded_audience_searches_episodes_and_semantic_records() -> None:
    memory = _Scripted()
    await _again(_stage(memory))
    assert {one.kinds for one in memory.searches} == {(MemoryKind.EPISODIC, MemoryKind.MEMORY)}


# --- §2:7: failure-tolerant under recall's budget ---------------------------------------------


async def test_a_store_failure_is_a_failed_decision_carrying_the_cues() -> None:
    memory = _Scripted(answers={MEANING: [(_fact("m"), 0.9)]}, fail_on=GAP_A)
    recalled = await _again(_stage(memory))
    assert (recalled.result.outcome, recalled.result.items, recalled.scores) == (
        RecallOutcome.FAILED,
        (),
        (),
    )
    assert recalled.result.cues == (RecallCue.UNDERSTOOD_MEANING, RecallCue.UNDERSTOOD_GAP)
    assert isinstance(recalled.error, MemoryStoreError)


async def test_a_spent_budget_is_a_timed_out_decision() -> None:
    stage = _stage(_Scripted(slow=True), budget=timedelta(milliseconds=10))
    recalled = await _again(stage)
    assert recalled.result.outcome is RecallOutcome.TIMED_OUT
    assert isinstance(recalled.error, TimeoutError)


async def test_the_pass_deadline_caps_the_budget() -> None:
    stage = _stage(_Scripted(slow=True))
    started = asyncio.get_running_loop().time()
    recalled = await _again(stage, deadline=started + 0.01)
    assert recalled.result.outcome is RecallOutcome.TIMED_OUT
    assert asyncio.get_running_loop().time() - started < 2


async def test_a_passed_deadline_raises_and_searches_nothing() -> None:
    memory = _Scripted()
    with pytest.raises(TimeoutError, match="before recall"):
        await _again(_stage(memory), deadline=asyncio.get_running_loop().time())
    assert memory.searches == []
