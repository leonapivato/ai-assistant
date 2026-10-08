"""ADR-0300 §7: recall looks up the stories of the episodes it keeps.

The stage alone, over the canonical fakes: which kept records are looked up, what each
item carries, how a story store failure and recall's budget bound the lookups, and the
order :meth:`Recalled.stories` hands the stories to the candidates in (§6:1). The engine
wiring is in ``test_engine_recall_stories.py``.
"""

from __future__ import annotations

import asyncio
import math
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest
from story_support import AT, activation, address, episode, failing, memory_of

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    ActivationRecall,
    BeliefBand,
    EpisodicMemory,
    MemoryKind,
    MemorySource,
    Placement,
    Provenance,
    RecallCue,
    RecalledItem,
    RecallOutcome,
    RecallProvenance,
    SemanticMemory,
    StoryActor,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.recall import Recalled, RecallStage
from ai_assistant.testing import FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord, StoryHeader, StoryMember
    from ai_assistant.testing import FakeMemoryStore

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
#: The words every record a case means recall to keep holds, so the fake scores it 1.0.
CUE: Final = "canoe booked Sunday"
TEXT: Final = "The canoe is booked for Sunday."


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


async def _story(stories: FakeStoryStore, *members: StoryMember) -> str:
    story_id = (await stories.create(list(members), actor=StoryActor.OWNER)).story_id
    assert story_id is not None
    return story_id


def _fact(memory_id: str) -> SemanticMemory:
    return SemanticMemory(
        id=memory_id,
        content=TEXT,
        fact=TEXT,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        placement=Placement(),
    )


class _Counting:
    """Count ``stories_of`` calls on a fake, answering as it does."""

    def __init__(self, stories: FakeStoryStore) -> None:
        self.asked: list[StoryMember] = []
        answer = stories.stories_of

        async def stories_of(member: StoryMember) -> tuple[StoryHeader, ...]:
            self.asked.append(member)
            return await answer(member)

        stories.stories_of = stories_of  # type: ignore[method-assign]  # a seam on one instance


def _stage(
    memory: FakeMemoryStore,
    stories: FakeStoryStore,
    *,
    budget: timedelta = timedelta(seconds=2),
) -> RecallStage:
    return RecallStage(memory=memory, stories=stories, threshold=0.5, limit=3, budget=budget)


async def _recall(stage: RecallStage, *, deadline: float = math.inf) -> Recalled:
    return await stage.recall(CUE, audience=BOUNDED, deadline=deadline)


def _by_id(recalled: Recalled) -> dict[str, RecalledItem]:
    return {item.id: item for item in recalled.result.items}


async def _memory(*records: MemoryRecord) -> FakeMemoryStore:
    return await memory_of(*records)


# --- §7:1, §7:2: what is looked up, and what each item carries ------------------------------


async def test_a_kept_episode_carries_its_stories_in_the_stores_order() -> None:
    stories = _stories()
    older = await _story(stories, activation("a-1"))
    newer = await _story(stories, activation("a-1"))
    memory = await _memory(episode("a-1", text=TEXT))

    recalled = await _recall(_stage(memory, stories))

    assert recalled.result.outcome is RecallOutcome.FOUND
    # ADR-0289 §3: the store answers newest first, and the item keeps that order.
    assert _by_id(recalled)[address("a-1")].stories == (newer, older)


async def test_an_episode_in_no_story_carries_none() -> None:
    recalled = await _recall(_stage(await _memory(episode("a-1", text=TEXT)), _stories()))
    assert _by_id(recalled)[address("a-1")].stories == ()


async def test_a_semantic_record_is_never_looked_up_and_carries_none() -> None:
    stories = _stories()
    counting = _Counting(stories)
    recalled = await _recall(_stage(await _memory(_fact("fact-canoe")), stories))
    assert _by_id(recalled)["fact-canoe"].stories == ()
    assert counting.asked == []


async def test_only_an_episode_at_its_activations_address_is_looked_up() -> None:
    """§7:1: "whose stored id is an activation's episode", read off the record, not the id."""
    stories = _stories()
    await _story(stories, activation("a-1"), activation("a-2"))
    counting = _Counting(stories)
    at_address = episode("a-1", text=TEXT)
    elsewhere = episode("a-2", text=TEXT).model_copy(update={"id": "imported-a-2"})
    unrecorded = EpisodicMemory(
        id=address("a-3"),
        content=TEXT,
        occurred_at=AT,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=AT),
        placement=Placement(),
    )
    memory = await _memory(at_address, elsewhere, unrecorded)

    recalled = await _recall(_stage(memory, stories))

    items = _by_id(recalled)
    assert set(items) == {address("a-1"), "imported-a-2", address("a-3")}
    assert counting.asked == [activation("a-1")]
    assert items["imported-a-2"].stories == items[address("a-3")].stories == ()


# --- §7:3: a story store that fails, and recall's budget ------------------------------------


async def test_a_story_store_failure_is_a_failed_decision_returned_not_raised() -> None:
    stories = failing(_stories(), "stories_of")
    recalled = await _recall(_stage(await _memory(episode("a-1", text=TEXT)), stories))
    assert (recalled.result.outcome, recalled.result.items, recalled.scores) == (
        RecallOutcome.FAILED,
        (),
        (),
    )
    assert isinstance(recalled.error, StoryStoreError)


async def test_a_semantic_only_recall_reads_no_story_and_cannot_fail_on_one() -> None:
    stories = failing(_stories(), "stories_of")
    recalled = await _recall(_stage(await _memory(_fact("fact-canoe")), stories))
    assert recalled.result.outcome is RecallOutcome.FOUND


def _slow(stories: FakeStoryStore) -> FakeStoryStore:
    async def stories_of(member: StoryMember) -> tuple[StoryHeader, ...]:
        del member  # answered by no lookup: the call outlasts any budget a case sets
        await asyncio.sleep(10)
        return ()

    stories.stories_of = stories_of  # type: ignore[method-assign]  # a seam on one instance
    return stories


async def test_the_lookups_run_within_recalls_budget() -> None:
    stage = _stage(
        await _memory(episode("a-1", text=TEXT)),
        _slow(_stories()),
        budget=timedelta(milliseconds=10),
    )
    recalled = await _recall(stage)
    assert (recalled.result.outcome, recalled.result.items) == (RecallOutcome.TIMED_OUT, ())
    assert isinstance(recalled.error, TimeoutError)


async def test_the_pass_deadline_bounds_the_lookups_too() -> None:
    stage = _stage(await _memory(episode("a-1", text=TEXT)), _slow(_stories()))
    started = asyncio.get_running_loop().time()
    recalled = await _recall(stage, deadline=started + 0.01)
    assert recalled.result.outcome is RecallOutcome.TIMED_OUT
    assert asyncio.get_running_loop().time() - started < 2


# --- §6:1: the order the stories join the candidates in -------------------------------------


def _item(memory_id: str, *stories: str) -> RecalledItem:
    return RecalledItem(
        kind=MemoryKind.EPISODIC,
        id=memory_id,
        excerpt="",
        provenance=RecallProvenance.USER,
        standing=BeliefBand.DERIVED,
        rests_on_recorded_external_content=False,
        found_by=(RecallCue.ACTIVATION_INPUT,),
        stories=stories,
    )


def _found(*scored: tuple[RecalledItem, float]) -> Recalled:
    return Recalled(
        ActivationRecall(
            outcome=RecallOutcome.FOUND,
            cues=(RecallCue.ACTIVATION_INPUT,),
            items=tuple(item for item, _ in scored),
        ),
        scores=tuple(score for _, score in scored),
    )


def test_the_higher_scoring_items_stories_come_first_each_once() -> None:
    # Recall's order is band order, so a lower score can precede a higher one.
    recalled = _found(
        (_item("e-low", "s-low", "s-shared"), 0.6),
        (_item("e-high", "s-shared", "s-high"), 0.9),
        (_item("e-mid", "s-mid"), 0.7),
    )
    held = {"e-low", "e-high", "e-mid"}
    assert recalled.stories(held) == ("s-shared", "s-high", "s-mid", "s-low")


def test_equal_scores_keep_recalls_own_order() -> None:
    recalled = _found((_item("e-1", "s-1"), 0.8), (_item("e-2", "s-2"), 0.8))
    assert recalled.stories({"e-1", "e-2"}) == ("s-1", "s-2")


def test_an_item_the_fetch_did_not_admit_brings_no_story() -> None:
    recalled = _found((_item("e-1", "s-1"), 0.9), (_item("e-2", "s-2"), 0.8))
    assert recalled.stories({"e-2"}) == ("s-2",)
    assert recalled.stories(set()) == ()


@pytest.mark.parametrize(
    "outcome", [RecallOutcome.NOTHING_FOUND, RecallOutcome.FAILED, RecallOutcome.TIMED_OUT]
)
def test_a_recall_that_kept_nothing_brings_no_story(outcome: RecallOutcome) -> None:
    recalled = Recalled(ActivationRecall(outcome=outcome, cues=(RecallCue.ACTIVATION_INPUT,)))
    assert recalled.stories({"anything"}) == ()
