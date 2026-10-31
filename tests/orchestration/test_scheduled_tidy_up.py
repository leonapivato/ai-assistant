"""The scheduled tidy-up (ADR-0358 §4): which stories are due, in what order, how many.

Each case runs :class:`ScheduledTidyUp` over the one :class:`StoryTidyUp`, the canonical
fake story and memory stores and a provider whose reply is chosen by the story the
completion is for, with a clock the case moves, and asserts which stories were tidied
and in what order. What a tidy-up reads, renders, checks and writes is
``test_story_tidy_up.py``'s, and unchanged here (§4:5).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final

import pytest
from story_support import AT, EVENTS, activation, episode, failing, memory_of
from structlog.testing import capture_logs
from structured_support import structured

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import Message, StoryActor, StoryNoteAuthor
from ai_assistant.orchestration.story_tidy_up import (
    STORY_TIDY_UP_PROMPT,
    ScheduledTidyUp,
    ScheduledTidyUpReport,
    StoryTidyUp,
    TidyUpResult,
)
from ai_assistant.testing import FakeModelProvider, FakeStoryStore, default_prompt

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.testing import FakeMemoryStore

_QUIET: Final = timedelta(hours=24)
_BUDGET: Final = timedelta(seconds=30)
_GOOD: Final = json.dumps({"lines": ["A matter, tidied."], "flags": []})
_BROKEN: Final = "not a reply"


class _Clock:
    """A clock the case moves, read by the story store and the scheduled run alike."""

    def __init__(self) -> None:
        self.at = AT

    def __call__(self) -> datetime:
        return self.at


class _Model:
    """Answers each tidy-up by the first note it is shown, and records the order.

    A note naming a story in ``broken`` gets a reply that does not parse, so that
    story's run is refused; every other gets a reply that writes.
    """

    def __init__(self, *broken: str) -> None:
        self.broken = set(broken)
        self.seen: list[str] = []
        self.provider = FakeModelProvider(self._answer)

    def _answer(self, messages: Sequence[Message]) -> str:
        shown = json.loads(messages[-1].content)
        name = shown["notes"][0]["text"] if shown["notes"] else "(no note)"
        self.seen.append(name)
        return _BROKEN if name in self.broken else _GOOD


def _stories(clock: _Clock) -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=clock, new_id=lambda: f"{next(ids)}")


def _tidy_up(model: _Model, stories: FakeStoryStore, memory: FakeMemoryStore) -> StoryTidyUp:
    return StoryTidyUp(
        model=structured(model.provider),
        stories=stories,
        memory=memory,
        excerpt_chars=2000,
        other_stories=0,
        decisions=0,
        budget=_BUDGET,
        threshold=0.0,
        prompt=default_prompt(STORY_TIDY_UP_PROMPT),
    )


def _scheduled(  # noqa: PLR0913 — one knob per bound a case varies
    tidy_up: StoryTidyUp,
    stories: FakeStoryStore,
    clock: _Clock,
    *,
    threshold: int = 5,
    per_run: int = 10,
    budget: timedelta = _BUDGET,
) -> ScheduledTidyUp:
    return ScheduledTidyUp(
        tidy_up=tidy_up,
        stories=stories,
        threshold=threshold,
        quiet=_QUIET,
        per_run=per_run,
        budget=budget,
        now=clock,
    )


#: The frozen episodes every case's memory store holds, one for each story ``_story``
#: makes, so each tidy-up takes its story's episode in and leaves nothing pending.
_HELD: Final = tuple(f"a-{index}" for index in range(1, 9))


async def _memory(*more: MemoryRecord) -> FakeMemoryStore:
    return await memory_of(*(episode(one) for one in _HELD), *more)


async def _story(stories: FakeStoryStore, *notes: str, members: Sequence[str] = ()) -> str:
    """A story of ``members``, with ``notes`` pending on it, each its own name.

    With no ``members`` named, its one member is the next held episode, which is
    pending on it as well.
    """
    if not members:
        held = len((await stories.stories(limit=100)).stories)
        members = (_HELD[held],)
    created = await stories.create(
        [activation(member) for member in members], actor=StoryActor.UNDERSTANDING
    )
    assert created.story_id is not None
    for text in notes:
        await stories.append_note(
            created.story_id, text, author=StoryNoteAuthor.PLANNING, written_during="a-0"
        )
    return created.story_id


async def _pending(stories: FakeStoryStore, story_id: str) -> int:
    state = await stories.current_summary(story_id)
    assert state is not None
    return len(state.pending_notes) + len(state.pending_episodes)


# --- when a story is due (§4:2) ------------------------------------------------------


async def test_a_story_whose_pending_count_reaches_the_threshold_is_tidied() -> None:
    clock = _Clock()
    stories = _stories(clock)
    memory = await _memory()
    model = _Model()
    # Three notes and the episode, four pending; two notes and the episode, three.
    busy = await _story(stories, "busy", "busy, again", "busy, a third time")
    calm = await _story(stories, "calm", "calm, again")
    scheduled = _scheduled(_tidy_up(model, stories, memory), stories, clock, threshold=4)

    report = await scheduled.run()

    assert report == ScheduledTidyUpReport(due=1, tidied=1, written=1)
    assert model.seen == ["busy"]
    assert await _pending(stories, busy) == 0
    assert await _pending(stories, calm) == 3, "below the count and not quiet: not due"


async def test_a_story_with_anything_pending_is_tidied_once_it_has_gone_quiet() -> None:
    clock = _Clock()
    stories = _stories(clock)
    model = _Model()
    trip = await _story(stories, "trip")
    scheduled = _scheduled(_tidy_up(model, stories, await _memory()), stories, clock)

    clock.at = AT + _QUIET - timedelta(seconds=1)
    assert await scheduled.run() == ScheduledTidyUpReport()
    assert model.seen == []

    clock.at = AT + _QUIET + timedelta(seconds=1)
    assert await scheduled.run() == ScheduledTidyUpReport(due=1, tidied=1, written=1)
    assert model.seen == ["trip"]
    assert await _pending(stories, trip) == 0


async def test_the_quiet_period_counts_from_the_newest_of_what_is_pending() -> None:
    """An episode linked later keeps a story with an old note and episode from being quiet."""
    clock = _Clock()
    stories = _stories(clock)
    memory = await _memory(episode("a-later"))
    model = _Model()
    trip = await _story(stories, "trip")
    clock.at = AT + timedelta(hours=20)
    linked = await stories.link(trip, [activation("a-later")], actor=StoryActor.UNDERSTANDING)
    assert linked.refusal is None
    scheduled = _scheduled(_tidy_up(model, stories, memory), stories, clock)

    clock.at = AT + timedelta(hours=25)
    assert (await scheduled.run()).due == 0, "the episode came five hours ago"

    clock.at = AT + timedelta(hours=45)
    assert await scheduled.run() == ScheduledTidyUpReport(due=1, tidied=1, written=1)
    assert await _pending(stories, trip) == 0


async def test_a_story_with_nothing_pending_or_merged_away_is_not_due() -> None:
    clock = _Clock()
    stories = _stories(clock)
    model = _Model()
    kept = await _story(stories, "kept")
    gone = await _story(stories, "gone")
    merged = await stories.merge(gone, kept, actor=StoryActor.OWNER)
    assert merged.refusal is None
    scheduled = _scheduled(_tidy_up(model, stories, await _memory()), stories, clock, threshold=1)

    first = await scheduled.run()
    second = await scheduled.run()

    assert first == ScheduledTidyUpReport(due=1, tidied=1, written=1), "the merged one is not"
    assert second == ScheduledTidyUpReport(), "nothing is pending once it is tidied"


# --- the order and the bound (§4:3, §4:4) ---------------------------------------------


async def test_a_run_takes_the_oldest_pending_first_up_to_its_bound() -> None:
    clock = _Clock()
    stories = _stories(clock)
    model = _Model()
    clock.at = AT + timedelta(hours=2)
    newest = await _story(stories, "newest")
    clock.at = AT
    oldest = await _story(stories, "oldest")
    clock.at = AT + timedelta(hours=1)
    middle = await _story(stories, "middle")
    clock.at = AT + timedelta(hours=3)
    tidy_up = _tidy_up(model, stories, await _memory())

    report = await _scheduled(tidy_up, stories, clock, threshold=1, per_run=2).run()

    assert report == ScheduledTidyUpReport(due=3, tidied=2, written=2, exhausted=False)
    assert model.seen == ["oldest", "middle"]
    assert [await _pending(stories, one) for one in (oldest, middle, newest)] == [0, 0, 2]


async def test_a_failed_story_goes_after_every_other_and_the_oldest_failure_first() -> None:
    """§4:4: a reply that never parses holds neither the front of the queue nor every retry."""
    clock = _Clock()
    stories = _stories(clock)
    model = _Model("first", "second")
    await _story(stories, "first")
    clock.at = AT + timedelta(minutes=1)
    await _story(stories, "second")
    clock.at = AT + timedelta(minutes=2)
    third = await _story(stories, "third")
    tidy_up = _tidy_up(model, stories, await _memory())

    def one_at_a_time() -> ScheduledTidyUp:
        return _scheduled(tidy_up, stories, clock, threshold=1, per_run=1)

    once = await one_at_a_time().run()
    assert once == ScheduledTidyUpReport(due=3, tidied=1, not_written=1, exhausted=False)
    # "first" failed, so "second", next oldest of those that have not, is next.
    assert (await one_at_a_time().run()).not_written == 1
    assert model.seen == ["first", "second"]

    every = await _scheduled(tidy_up, stories, clock, threshold=1, per_run=3).run()

    assert every == ScheduledTidyUpReport(due=3, tidied=3, written=1, not_written=2)
    assert model.seen[2:] == ["third", "first", "second"]
    assert await _pending(stories, third) == 0


async def test_a_story_the_tidy_up_does_not_start_on_is_passed_over_and_not_counted() -> None:
    """§4:6: outside content alone, a run already going, nothing it can read: not counted."""
    clock = _Clock()
    stories = _stories(clock)
    memory = await _memory(episode("a-out", channel=EVENTS))
    model = _Model()
    await _story(stories, members=("a-out",))
    clock.at = AT + timedelta(minutes=1)
    await _story(stories, members=("a-gone",))
    clock.at = AT + timedelta(minutes=2)
    held = await _story(stories, "held")
    clock.at = AT + timedelta(minutes=3)
    tidied = await _story(stories, "tidied")
    tidy_up = _tidy_up(model, stories, memory)
    # Planning's tidy-up call is running on it (ADR-0300 §5:10).
    tidy_up._running.add(held)

    report = await _scheduled(tidy_up, stories, clock, threshold=1, per_run=1).run()

    assert report == ScheduledTidyUpReport(due=4, tidied=1, written=1, passed_over=3)
    assert model.seen == ["tidied"]
    assert await _pending(stories, tidied) == 0
    assert tidy_up.last_failure(held) is None, "a run that did not start is no failure"


async def test_no_tidy_up_starts_once_the_run_s_budget_has_passed() -> None:
    clock = _Clock()
    stories = _stories(clock)
    model = _Model()
    await _story(stories, "first")
    await _story(stories, "second")
    tidy_up = _tidy_up(model, stories, await _memory())
    scheduled = _scheduled(tidy_up, stories, clock, threshold=1, budget=timedelta(microseconds=1))

    report = await scheduled.run()

    assert report == ScheduledTidyUpReport(due=2, tidied=1, written=1, exhausted=False)
    assert len(model.seen) == 1, "the first due story is always tried"


# --- the failures the order reads ----------------------------------------------------


async def test_a_failure_is_held_until_a_run_on_the_story_writes() -> None:
    """Whoever started the run: planning's call runs the same operation."""
    clock = _Clock()
    stories = _stories(clock)
    model = _Model("trip")
    trip = await _story(stories, "trip")
    other = await _story(stories, "other")
    model.broken.add("other")
    tidy_up = _tidy_up(model, stories, await _memory())

    assert (await tidy_up.run(trip)).result is TidyUpResult.REFUSED
    assert (await tidy_up.run(other)).result is TidyUpResult.REFUSED
    first, second = tidy_up.last_failure(trip), tidy_up.last_failure(other)
    assert first is not None
    assert second is not None
    assert first < second

    model.broken.clear()
    assert (await tidy_up.run(trip)).result is TidyUpResult.WRITTEN
    assert tidy_up.last_failure(trip) is None
    assert (await tidy_up.run(trip)).result is TidyUpResult.NOTHING_TO_READ
    assert tidy_up.last_failure(trip) is None
    assert tidy_up.last_failure(other) == second


# --- what it raises and logs ---------------------------------------------------------


async def test_a_store_that_cannot_be_read_while_finding_what_is_due_is_raised() -> None:
    clock = _Clock()
    stories = _stories(clock)
    await _story(stories, "trip")
    model = _Model()
    scheduled = _scheduled(
        _tidy_up(model, stories, await _memory()), failing(stories, "stories"), clock
    )

    with pytest.raises(StoryStoreError):
        await scheduled.run()
    assert model.seen == []


async def test_it_logs_code_owned_counts_only() -> None:
    clock = _Clock()
    stories = _stories(clock)
    await _story(stories, "Camping at Riverside.")
    tidy_up = _tidy_up(_Model(), stories, await _memory())

    with capture_logs() as captured:
        await _scheduled(tidy_up, stories, clock, threshold=1).run()

    (entry,) = [one for one in captured if one["event"] == "scheduled_tidy_up"]
    assert entry == {
        "event": "scheduled_tidy_up",
        "log_level": "info",
        "stage": "scheduled_tidy_up",
        "due": 1,
        "tidied": 1,
        "written": 1,
        "not_written": 0,
        "passed_over": 0,
        "exhausted": True,
    }


@pytest.mark.parametrize(
    ("threshold", "quiet", "per_run", "budget"),
    [
        (0, _QUIET, 10, _BUDGET),
        (5, timedelta(0), 10, _BUDGET),
        (5, _QUIET, 0, _BUDGET),
        (5, _QUIET, 10, timedelta(0)),
    ],
)
async def test_its_bounds_are_positive(
    threshold: int, quiet: timedelta, per_run: int, budget: timedelta
) -> None:
    clock = _Clock()
    stories = _stories(clock)
    tidy_up = _tidy_up(_Model(), stories, await _memory())

    with pytest.raises(ValueError, match="positive"):
        ScheduledTidyUp(
            tidy_up=tidy_up,
            stories=stories,
            threshold=threshold,
            quiet=quiet,
            per_run=per_run,
            budget=budget,
            now=clock,
        )
