"""What planning is shown of stories, read from the stores (ADR-0307 §6:1, §6:3-§6:4).

:class:`~ai_assistant.orchestration.phase_path.StoryReads` over the canonical fakes:
the stories the activation belongs to, each with its summary state, the episodes newer
than it and its latest, the stories it is part of and where its matter stands, and the
stories understanding cited; each read under the pass's audience. The rendering is
``test_planning_stories.py``'s, and the path end to end ``test_engine_phases.py``'s.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import activation, address, episode, failing, memory_of, story
from test_engine import AT

from ai_assistant.core.errors import PlanningError, StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ActivationEffect,
    ActivationUnderstanding,
    Placement,
    PlacementReach,
    PlacementSetter,
    StoryActor,
    StoryEffectState,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    ToolOutcome,
    UnderstandingProducer,
    UnderstandingReferent,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.lookups import OLDER_NOTES_PAGE
from ai_assistant.orchestration.phase_path import StoryReads
from ai_assistant.orchestration.story_links import StoryCandidates
from ai_assistant.testing import FakePlanStore, FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import EpisodicMemory
    from ai_assistant.orchestration.planning import PlanningStories, PlanningStory
    from ai_assistant.testing import FakeMemoryStore

_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())
_OWNER_ONLY: Final = Placement(
    reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=AT
)
_DAY: Final = timedelta(days=1)

#: The activation being planned: running, so its own episode is open.
_NOW: Final = "now"


class _World:
    """One story store, memory store and plan store, and the reads over them."""

    def __init__(self, memory: FakeMemoryStore, *, episodes: int = 2) -> None:
        ids = count(1)
        self.stories = FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")
        self.memory = memory
        self.plans = FakePlanStore(now=lambda: AT)
        self.reads = StoryReads(
            stories=self.stories,
            memory=memory,
            plans=self.plans,
            short_views=StoryCandidates(
                stories=self.stories, memory=memory, limit=5, lines=3, notes=2, episodes=2
            ),
            episodes=episodes,
        )

    async def story(self, *activations: str) -> str:
        outcome = await self.stories.create(
            [activation(one) for one in activations], actor=StoryActor.OWNER
        )
        assert outcome.story_id is not None
        return outcome.story_id

    async def tidied(self, story_id: str, *lines: str, outside: bool = False) -> None:
        """Write a summary taking in everything pending on the story now."""
        state = await self.stories.current_summary(story_id)
        assert state is not None
        draft = StorySummaryDraft(
            lines=tuple(StorySummaryLine(text=line) for line in lines),
            took_in_notes=tuple(note.note_id for note in state.pending_notes),
            took_in_episodes=state.pending_episodes,
            outside=outside,
        )
        written = await self.stories.write_summary(story_id, draft, as_of=state.as_of)
        assert written.refusal is None

    async def note(self, story_id: str, text: str, *, outside: bool = False) -> None:
        written = await self.stories.append_note(
            story_id,
            text,
            author=StoryNoteAuthor.PLANNING,
            written_during="earlier",
            outside=outside,
        )
        assert written.refusal is None

    async def read(
        self,
        *,
        owner_records: bool = True,
        understanding: ActivationUnderstanding | None = None,
    ) -> PlanningStories:
        return await self.reads.read(
            _NOW,
            understanding=understanding,
            audience=_BOUNDED if owner_records else _UNBOUNDED,
            owner_records=owner_records,
        )


async def _world(*records: EpisodicMemory, episodes: int = 2) -> _World:
    return _World(await memory_of(episode(_NOW, open_=True), *records), episodes=episodes)


def _ids(records: Sequence[EpisodicMemory]) -> list[str]:
    return [record.id for record in records]


def _one(given: PlanningStories) -> PlanningStory:
    assert not given.unreadable
    (only,) = given.stories
    return only


async def test_a_story_the_activation_belongs_to_is_read_with_each_part() -> None:
    """§6:1, §6:3: summary, what is newer and the count, latest, inherited and standing."""
    world = await _world(
        episode("a", at=AT - 3 * _DAY),
        episode("b", at=AT - 2 * _DAY),
        episode("c", at=AT - _DAY),
    )
    trip = await world.story("a")
    await world.tidied(trip, "A camping trip to Riverside.")
    await world.stories.link(trip, [activation("b"), activation("c")], actor=StoryActor.OWNER)
    await world.note(trip, "Next: check the dog policy.")
    await world.stories.link(trip, [activation(_NOW)], actor=StoryActor.UNDERSTANDING)
    summer = await world.story("a")
    await world.tidied(summer, "Plan our summer.")
    await world.stories.link(summer, [story(trip)], actor=StoryActor.OWNER)

    view = _one(await world.read())

    assert view.story_id == trip
    assert view.written
    assert [line.text for line in view.lines] == ["A camping trip to Riverside."]
    assert view.tidied_at == AT
    assert not view.withheld
    # One count: the note and the three episodes linked since, the running one included.
    assert view.changes == 4
    assert [note.text for note in view.notes] == ["Next: check the dog policy."]
    # The running activation's own episode is open, and never a model input.
    assert _ids(view.newer) == [address("c"), address("b")]
    assert _ids(view.latest) == [address("c"), address("b")]
    (parent,) = view.inherited
    assert parent.story_id == summer
    assert [line.text for line in parent.lines] == ["Plan our summer."]
    assert view.standing is not None
    assert [one.activation_id for one in view.standing.recent] == ["c", "b", "a"]


async def test_how_many_newer_episodes_are_shown_is_bounded_and_all_are_counted() -> None:
    world = await _world(*(episode(f"e{n}", at=AT - n * _DAY) for n in range(1, 5)), episodes=2)
    trip = await world.story("e1", "e2", "e3", "e4")
    await world.stories.link(trip, [activation(_NOW)], actor=StoryActor.UNDERSTANDING)

    view = _one(await world.read())

    assert view.tidied_at is None
    assert not view.written
    assert view.changes == 5
    assert _ids(view.newer) == [address("e1"), address("e2")]
    assert _ids(view.latest) == [address("e1"), address("e2")]


async def test_what_was_done_is_read_from_the_effect_records() -> None:
    """ADR-0300 §8:1: unknown first, then not done, then done."""
    world = await _world(episode("a", at=AT - 2 * _DAY), episode("b", at=AT - _DAY))
    trip = await world.story("a", "b", _NOW)
    for effect_id, activation_id, outcome in (
        ("e1", "a", ToolOutcome.SUCCEEDED),
        ("e2", "b", ToolOutcome.INDETERMINATE),
        ("e3", _NOW, ToolOutcome.SUCCEEDED),
    ):
        await world.plans.claim_activation_effect(
            _call_effect(effect_id, activation_id), match=None
        )
        await world.plans.finish_activation_effect(effect_id, outcome)

    view = _one(await world.read())

    assert view.story_id == trip
    assert view.standing is not None
    # The running activation's own effects are its rounds' outcomes, not the story's.
    assert [(one.activation_id, one.state) for one in view.standing.done] == [
        ("b", StoryEffectState.UNKNOWN),
        ("a", StoryEffectState.DONE),
    ]


def _call_effect(effect_id: str, activation_id: str) -> ActivationEffect:
    return ActivationEffect(
        id=effect_id,
        activation_id=activation_id,
        round="round:1",
        capability="book",
        values_digest="0" * 64,
        decision_id=f"decision:{effect_id}",
        claimed_at=AT,
    )


async def test_where_owner_records_may_not_be_shown_the_view_follows_understandings() -> None:
    """§6:4: summary withheld, notes absent, episodes and standing only what is admitted.

    When it was last tidied and how many changes have come since are read whatever the
    audience.
    """
    world = await _world(
        episode("shared", at=AT - 2 * _DAY),
        episode("private", at=AT - _DAY, placement=_OWNER_ONLY),
    )
    trip = await world.story("shared")
    await world.tidied(trip, "A camping trip.")
    await world.stories.link(trip, [activation("private")], actor=StoryActor.OWNER)
    await world.note(trip, "A note the room may not hear.")
    await world.stories.link(trip, [activation(_NOW)], actor=StoryActor.UNDERSTANDING)
    summer = await world.story("shared")
    await world.tidied(summer, "Plan our summer.")
    await world.note(summer, "Another note.")
    await world.stories.link(summer, [story(trip)], actor=StoryActor.OWNER)

    view = _one(await world.read(owner_records=False))

    assert view.withheld
    assert view.lines == ()
    assert not view.outside
    assert view.notes == ()
    assert view.notes_withheld
    assert view.tidied_at == AT
    assert view.changes == 3
    assert _ids(view.newer) == []
    assert _ids(view.latest) == [address("shared")]
    assert view.standing is not None
    assert [one.activation_id for one in view.standing.recent] == ["shared"]
    (parent,) = view.inherited
    assert parent.withheld
    assert parent.notes == ()
    assert parent.notes_withheld


async def test_a_story_cited_as_a_referent_and_not_one_of_the_activations_is_read() -> None:
    """§6:1, ADR-0304 §8: a cited story the activation is in, or inherits, is not repeated."""
    world = await _world(episode("a"), episode("b"))
    trip = await world.story("a", _NOW)
    car = await world.story("b")
    await world.tidied(car, "The car repair.")
    understanding = _citing(trip, car, car)

    given = await world.read(understanding=understanding)

    assert [one.story_id for one in given.stories] == [trip]
    (cited,) = given.cited
    assert cited.story_id == car
    assert [line.text for line in cited.lines] == ["The car repair."]


def _citing(*story_ids: str) -> ActivationUnderstanding:
    """An understanding whose ``cites`` resolved to every story named, in order."""
    first, *rest = (
        UnderstandingReferent(kind="story", id=one, source="story", excerpt="") for one in story_ids
    )
    return ActivationUnderstanding(
        version=1,
        recorded_at=AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning="the trip depends on the car",
        meaning_referents=(first, *rest),
    )


async def test_an_activation_in_no_story_is_shown_none() -> None:
    world = await _world()

    given = await world.read()

    assert given.stories == ()
    assert given.cited == ()
    assert not given.unreadable


@pytest.mark.parametrize("method", ["stories_of", "current_summary"])
async def test_a_story_store_that_cannot_be_read_says_the_stories_are_unreadable(
    method: str,
) -> None:
    world = await _world(episode("a"))
    await world.story("a", _NOW)
    failing(world.stories, method)

    given = await world.read()

    assert given.unreadable
    assert given.stories == ()


async def test_a_plan_store_that_cannot_be_read_says_the_stories_are_unreadable() -> None:
    world = await _world(episode("a"))
    await world.story("a", _NOW)

    async def down(*_args: Any) -> Any:
        msg = "the plan store is down"
        raise PlanningError(msg)

    world.plans.activation_effects = down  # type: ignore[method-assign]  # an unreadable store

    given = await world.read()

    assert given.unreadable


# --- a story read's full view: the older notes (#2893) -------------------------------------


async def _with_older(world: _World, taken_in: int, *, pending: int = 0) -> str:
    """A story with ``taken_in`` notes a tidy-up took in, then ``pending`` newer ones."""
    trip = await world.story("a")
    for n in range(1, taken_in + 1):
        await world.note(trip, f"older {n}")
    await world.tidied(trip, "A camping trip to Riverside.")
    for n in range(1, pending + 1):
        await world.note(trip, f"newer {n}")
    return trip


async def test_a_full_view_shows_the_newest_page_of_older_notes() -> None:
    """#2893: newest first, a page at a time, none of them pending, and how many more."""
    world = await _world(episode("a"))
    trip = await _with_older(world, OLDER_NOTES_PAGE + 2, pending=1)

    view = await world.reads.view(trip, audience=_BOUNDED, owner_records=True)

    assert view is not None
    assert [note.text for note in view.notes] == ["newer 1"]
    assert view.older is not None
    assert [note.text for note in view.older] == [
        f"older {n}" for n in range(OLDER_NOTES_PAGE + 2, 2, -1)
    ]
    assert (view.older_page, view.older_more) == (1, 2)


async def test_a_full_view_pages_past_the_first_page_of_older_notes() -> None:
    world = await _world(episode("a"))
    trip = await _with_older(world, OLDER_NOTES_PAGE + 2)

    second = await world.reads.view(trip, audience=_BOUNDED, owner_records=True, older_page=2)
    beyond = await world.reads.view(trip, audience=_BOUNDED, owner_records=True, older_page=3)

    assert second is not None
    assert second.older is not None
    assert [note.text for note in second.older] == ["older 2", "older 1"]
    assert (second.older_page, second.older_more) == (2, 0)
    assert beyond is not None
    assert (beyond.older, beyond.older_more) == ((), 0)


async def test_a_full_view_reads_every_page_the_store_holds() -> None:
    """More notes than one store page holds: every page is read, none lost."""
    world = await _world(episode("a"))
    trip = await _with_older(world, MAX_STORY_PAGE + 1)

    last = (MAX_STORY_PAGE + OLDER_NOTES_PAGE) // OLDER_NOTES_PAGE
    view = await world.reads.view(trip, audience=_BOUNDED, owner_records=True, older_page=last)

    assert view is not None
    assert view.older is not None
    assert view.older[-1].text == "older 1"
    assert view.older_more == 0


def _written_while_read(world: _World, story_id: str, *, times: int) -> None:
    """The story store, a note appended to ``story_id`` as each of ``times`` note reads runs."""
    read = world.stories.notes
    left = [times]

    async def notes(*args: Any, **kwargs: Any) -> Any:
        if left[0] > 0:
            left[0] -= 1
            await world.note(story_id, "written meanwhile")
        return await read(*args, **kwargs)

    world.stories.notes = notes  # type: ignore[method-assign]  # a write lands mid-read


async def test_a_note_written_while_a_full_view_reads_is_never_taken_for_an_older_one() -> None:
    """The notes are read between two reads of the summary's state, and read again.

    A note appended after the state was read is pending, not taken in: the read that
    missed it is not kept, and the next shows it among the notes since the summary.
    """
    world = await _world(episode("a"))
    trip = await world.story("a")
    _written_while_read(world, trip, times=1)

    view = await world.reads.view(trip, audience=_BOUNDED, owner_records=True)

    assert view is not None
    assert [note.text for note in view.notes] == ["written meanwhile"]
    assert view.older == ()


async def test_a_story_written_every_time_its_notes_are_read_cannot_be_read() -> None:
    world = await _world(episode("a"))
    trip = await world.story("a")
    _written_while_read(world, trip, times=5)

    with pytest.raises(StoryStoreError, match="every time they were read"):
        await world.reads.view(trip, audience=_BOUNDED, owner_records=True)


async def test_where_no_note_may_be_shown_a_full_view_reads_no_older_note() -> None:
    """ADR-0307 §6:4, ADR-0305 §4: absent, as every story note is on such a pass."""
    world = await _world(episode("a"))
    trip = await _with_older(world, 2, pending=1)

    view = await world.reads.view(trip, audience=_UNBOUNDED, owner_records=False)

    assert view is not None
    assert view.notes_withheld
    assert (view.notes, view.older, view.older_more) == ((), None, 0)


async def test_the_views_planning_is_given_each_round_read_no_older_note() -> None:
    """#2893: the default view is unchanged, the summary and what is newer than it."""
    world = await _world(episode("a"))
    trip = await _with_older(world, 2, pending=1)
    await world.stories.link(trip, [activation(_NOW)], actor=StoryActor.UNDERSTANDING)

    view = _one(await world.read())

    assert [note.text for note in view.notes] == ["newer 1"]
    assert view.older is None


def test_a_story_view_shows_at_least_one_episode() -> None:
    stories = FakeStoryStore()
    with pytest.raises(ValueError, match="at least one episode"):
        StoryReads(
            stories=stories,
            memory=None,  # type: ignore[arg-type]  # never reached
            plans=FakePlanStore(),
            short_views=None,  # type: ignore[arg-type]  # never reached
            episodes=0,
        )
