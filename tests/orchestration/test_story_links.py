"""ADR-0300 §6 and §11: understanding's candidate stories and the story-links stage.

The candidates (§6:1-§6:4) and the stage (§6:12-§6:13) over the canonical fakes, apart
from any engine; what a pass records is in ``test_engine_story_links.py``, and what the
prompt renders in ``test_understanding_stories.py``.
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import (
    AT,
    OWNER_ONLY,
    activation,
    address,
    episode,
    failing,
    memory_of,
    story,
)

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    StageOutcome,
    StoryActor,
    StoryChange,
    StoryDraftLine,
    StoryNoteAuthor,
    StoryPageDraft,
    StoryRefusalReason,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import MemoryRecord, StoryHeader, StoryMember, StoryViewPage

BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"{next(ids)}")


async def _story(stories: FakeStoryStore, *members: StoryMember) -> str:
    outcome = await stories.create(members, actor=StoryActor.OWNER)
    assert outcome.story_id is not None
    return outcome.story_id


def _candidates(  # noqa: PLR0913 — the two stores and §6's four numbers
    stories: FakeStoryStore,
    memory: FakeMemoryStore,
    *,
    limit: int = 5,
    lines: int = 3,
    notes: int = 2,
    episodes: int = 2,
) -> StoryCandidates:
    return StoryCandidates(
        stories=stories,
        memory=memory,
        limit=limit,
        lines=lines,
        notes=notes,
        episodes=episodes,
    )


# --- the candidates: which stories, in which order (§6:1) --------------------------


async def test_the_window_s_stories_are_candidates_in_the_window_s_order_each_once() -> None:
    stories = _stories()
    first = await _story(stories, activation("a-1"))
    second = await _story(stories, activation("a-2"))
    third = await _story(stories, activation("a-2"), activation("a-1"))
    window = (episode("a-1"), episode("a-2"))
    memory = await memory_of(*window)

    candidates = await _candidates(stories, memory).assemble(window, audience=BOUNDED)

    # a-1's stories come first, newest first as the store returns them, then a-2's
    # that are not already candidates.
    assert [view.story_id for view in candidates.views] == [third, first, second]
    assert not candidates.unreadable


async def test_the_candidates_stop_at_the_limit() -> None:
    stories = _stories()
    for index in range(4):
        await _story(stories, activation(f"a-{index}"))
    window = tuple(episode(f"a-{index}") for index in range(4))
    memory = await memory_of(*window)

    candidates = await _candidates(stories, memory, limit=2).assemble(window, audience=BOUNDED)

    assert len(candidates.views) == 2


async def test_recall_s_stories_join_after_the_window_s_and_are_not_repeated() -> None:
    stories = _stories()
    windowed = await _story(stories, activation("a-1"))
    recalled = await _story(stories, activation("a-9"))
    window = (episode("a-1"),)
    memory = await memory_of(*window)

    candidates = await _candidates(stories, memory).assemble(
        window, audience=BOUNDED, recalled=(windowed, recalled)
    )

    assert [view.story_id for view in candidates.views] == [windowed, recalled]


async def test_an_episode_recording_no_activation_belongs_to_no_story() -> None:
    stories = _stories()
    await _story(stories, activation("a-1"))
    legacy = episode("a-1").model_copy(update={"processing_record": None})
    memory = await memory_of(legacy)

    candidates = await _candidates(stories, memory).assemble((legacy,), audience=BOUNDED)

    assert candidates.views == ()


# --- the short view (§6:2, §6:3) ----------------------------------------------------


async def _paged(stories: FakeStoryStore, story_id: str, *lines: str) -> tuple[int, ...]:
    """Write one note per line and a page whose lines cite them in order."""
    ids = []
    for text in lines:
        written = await stories.append_note(
            story_id, text, author=StoryNoteAuthor.PLANNING, rests_on="a-1"
        )
        assert written.note is not None
        ids.append(written.note.note_id)
    state = await stories.current_page(story_id)
    assert state is not None
    draft = StoryPageDraft(
        lines=tuple(
            StoryDraftLine(text=text, cites=(note_id,), outside=False)
            for text, note_id in zip(lines, ids, strict=True)
        ),
        took_in_notes=tuple(ids),
    )
    written_page = await stories.write_page(story_id, draft, as_of=state.as_of)
    assert written_page.refusal is None
    return tuple(ids)


async def test_a_short_view_is_the_first_lines_the_newest_notes_and_the_latest_episodes() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"), activation("a-2"), activation("a-3"))
    await _paged(stories, trip, "A camping trip to Riverside.", "Leaning to Sunday.", "Canoe?")
    for text in ("first pending", "second pending", "third pending"):
        await stories.append_note(trip, text, author=StoryNoteAuthor.PLANNING, rests_on="a-2")
    window = (episode("a-1"),)
    memory = await memory_of(episode("a-1"), episode("a-2"), episode("a-3"))

    candidates = await _candidates(stories, memory, lines=2).assemble(window, audience=BOUNDED)

    (view,) = candidates.views
    assert [line.text for line in view.lines] == [
        "A camping trip to Riverside.",
        "Leaning to Sunday.",
    ]
    assert [note.text for note in view.notes] == ["third pending", "second pending"]
    assert [record.id for record in view.episodes] == [address("a-3"), address("a-2")]


async def test_the_latest_episodes_are_the_latest_by_occurrence_not_by_link_order() -> None:
    """A merge appends the absorbed story's members (ADR-0289 §3), old or not."""
    stories = _stories()
    recent = await _story(stories, activation("r-1"), activation("r-2"))
    old = await _story(stories, activation("o-1"), activation("o-2"))
    await stories.merge(old, recent, actor=StoryActor.OWNER)
    earlier = AT - timedelta(days=30)
    memory = await memory_of(
        episode("r-1", at=AT - timedelta(hours=2)),
        episode("r-2", at=AT - timedelta(hours=1)),
        episode("o-1", at=earlier),
        episode("o-2", at=earlier + timedelta(hours=1)),
    )
    window = (episode("r-2", at=AT - timedelta(hours=1)),)

    (view,) = (await _candidates(stories, memory).assemble(window, audience=BOUNDED)).views

    assert [record.id for record in view.episodes] == [address("r-2"), address("r-1")]


async def test_a_member_relinked_while_the_members_are_read_is_shown_once() -> None:
    """A member unlinked and linked again between two pages comes back on the later one."""
    stories = _stories()
    members = [activation(f"a-{index:03}") for index in range(101)]
    trip = await _story(stories, *members)
    pages = stories.view
    calls = count()

    async def relinking(story_id: str, **kwargs: Any) -> StoryViewPage | None:
        page = await pages(story_id, **kwargs)
        if not next(calls):
            # After the first page: the newest episode's member moves to the end.
            await stories.unlink(trip, [members[0]], actor=StoryActor.OWNER)
            await stories.link(trip, [members[0]], actor=StoryActor.OWNER)
        return page

    stories.view = relinking  # type: ignore[method-assign]  # an interleaving point
    records = [
        episode(member.id, at=AT - timedelta(minutes=index)) for index, member in enumerate(members)
    ]
    window = (records[0],)
    memory = await memory_of(*records)

    (view,) = (await _candidates(stories, memory).assemble(window, audience=BOUNDED)).views

    assert [record.id for record in view.episodes] == [address("a-000"), address("a-001")]


async def test_a_story_with_no_page_shows_its_pending_notes_and_episodes() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"))
    await stories.append_note(trip, "check the dog policy", author=StoryNoteAuthor.OWNER)
    window = (episode("a-1"),)
    memory = await memory_of(*window)

    (view,) = (await _candidates(stories, memory).assemble(window, audience=BOUNDED)).views

    assert view.lines == ()
    assert [note.text for note in view.notes] == ["check the dog policy"]
    assert [record.id for record in view.episodes] == [address("a-1")]


async def test_an_open_episode_is_neither_shown_nor_lets_its_notes_be() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"), activation("a-2"))
    await stories.append_note(
        trip, "from the open one", author=StoryNoteAuthor.PLANNING, rests_on="a-2"
    )
    window = (episode("a-1"),)
    memory = await memory_of(episode("a-1"), episode("a-2", open_=True))

    candidates = await _candidates(stories, memory).assemble(window, audience=BOUNDED)

    (view,) = candidates.views
    assert view.notes == ()
    assert [record.id for record in view.episodes] == [address("a-1")]
    # ADR-0282 §2:7-§2:8: only what was chosen, admitted, is fetched and recorded.
    assert (candidates.fetched, candidates.missing) == ((address("a-1"),), ())


@pytest.mark.parametrize("change", ["forgotten", "narrowed"])
async def test_an_episode_changed_between_the_choice_and_the_fetch_withholds_what_rests_on_it(
    change: str,
) -> None:
    """§11:1 is decided from the fetch: what rests on a changed episode is not shown."""
    stories = _stories()
    trip = await _story(stories, activation("a-1"), activation("a-2"))
    written = await stories.append_note(
        trip, "on a-2", author=StoryNoteAuthor.PLANNING, rests_on="a-2"
    )
    assert written.note is not None
    state = await stories.current_page(trip)
    assert state is not None
    draft = StoryPageDraft(
        lines=(StoryDraftLine(text="from a-2", cites=(written.note.note_id,), outside=False),),
        took_in_notes=(written.note.note_id,),
    )
    assert (await stories.write_page(trip, draft, as_of=state.as_of)).refusal is None
    await stories.append_note(trip, "also on a-2", author=StoryNoteAuthor.PLANNING, rests_on="a-2")
    window = (episode("a-1"),)
    memory = await memory_of(episode("a-1"), episode("a-2", at=AT + timedelta(minutes=1)))
    reads = memory.get_many
    calls = count()

    async def changing(record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        found = dict(await reads(record_ids))
        if next(calls) and address("a-2") in found:
            # The second read, the fetch: a-2 changed after it was chosen.
            if change == "forgotten":
                del found[address("a-2")]
            else:
                found[address("a-2")] = found[address("a-2")].model_copy(
                    update={"placement": OWNER_ONLY}
                )
        return found

    memory.get_many = changing  # type: ignore[method-assign]  # an interleaving point

    candidates = await _candidates(stories, memory).assemble(window, audience=UNBOUNDED)

    (view,) = candidates.views
    assert (view.lines, view.notes) == ((), ())
    assert [record.id for record in view.episodes] == [address("a-1")]
    assert candidates.fetched == (address("a-2"), address("a-1"))
    assert candidates.missing == (address("a-2"),)


# --- §11's default --------------------------------------------------------------------


async def test_an_unbounded_audience_is_shown_nothing_resting_on_an_owner_placed_episode() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"), activation("a-2"))
    # Both lines cite notes resting on a-1, which either audience may be shown.
    await _paged(stories, trip, "shared line", "another shared line")
    private_note = await stories.append_note(
        trip, "about the private one", author=StoryNoteAuthor.PLANNING, rests_on="a-2"
    )
    assert private_note.note is not None
    window = (episode("a-1"),)
    memory = await memory_of(episode("a-1"), episode("a-2", placement=OWNER_ONLY))

    unbounded = await _candidates(stories, memory).assemble(window, audience=UNBOUNDED)
    bounded = await _candidates(stories, memory).assemble(window, audience=BOUNDED)

    (seen,) = unbounded.views
    assert [line.text for line in seen.lines] == ["shared line", "another shared line"]
    assert seen.notes == ()
    assert [record.id for record in seen.episodes] == [address("a-1")]
    # §6:3 with ADR-0282 §2:8: the refused episode is neither fetched nor recorded.
    assert address("a-2") not in (*unbounded.fetched, *unbounded.missing)
    (whole,) = bounded.views
    assert [note.text for note in whole.notes] == ["about the private one"]
    assert [record.id for record in whole.episodes] == [address("a-2"), address("a-1")]


async def test_a_line_citing_a_note_that_may_not_be_shown_is_not_shown() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"))
    owner = await stories.append_note(trip, "my own words", author=StoryNoteAuthor.OWNER)
    planning = await stories.append_note(
        trip, "the assistant's", author=StoryNoteAuthor.PLANNING, rests_on="a-1"
    )
    assert owner.note is not None
    assert planning.note is not None
    state = await stories.current_page(trip)
    assert state is not None
    draft = StoryPageDraft(
        lines=(
            StoryDraftLine(text="A trip.", cites=(planning.note.note_id,), outside=False),
            StoryDraftLine(text="my own words", cites=(owner.note.note_id,), outside=False),
            StoryDraftLine(
                text="Both.", cites=(planning.note.note_id, owner.note.note_id), outside=False
            ),
        ),
        took_in_notes=(owner.note.note_id, planning.note.note_id),
    )
    assert (await stories.write_page(trip, draft, as_of=state.as_of)).refusal is None
    window = (episode("a-1"),)
    memory = await memory_of(*window)

    unbounded = await _candidates(stories, memory).assemble(window, audience=UNBOUNDED)
    bounded = await _candidates(stories, memory).assemble(window, audience=BOUNDED)

    # §11:1: a note the user wrote directly is shown only where a record placed for the
    # owner alone may be, and a line citing it carries its restriction.
    assert [line.text for line in unbounded.views[0].lines] == ["A trip."]
    assert [line.text for line in bounded.views[0].lines] == ["A trip.", "my own words", "Both."]


# --- a story store that cannot be read (§6:4) ----------------------------------------


@pytest.mark.parametrize("read", ["stories_of", "current_page", "notes", "view"])
async def test_a_story_store_error_leaves_no_candidates_and_says_so(read: str) -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"))
    # A page whose line cites a note no longer pending, so every one of the four reads
    # is made.
    await _paged(stories, trip, "A camping trip.")
    window = (episode("a-1"),)
    memory = await memory_of(*window)
    stories = failing(stories, read)

    candidates = await _candidates(stories, memory).assemble(window, audience=BOUNDED)

    assert (candidates.views, candidates.unreadable) == ((), True)


@pytest.mark.parametrize(
    ("limit", "notes", "episodes"), [(0, 2, 2), (5, 0, 2), (5, 3, 2), (5, 2, 3)]
)
def test_the_short_view_s_numbers_are_bounded(limit: int, notes: int, episodes: int) -> None:
    with pytest.raises(ValueError, match="ADR-0300"):
        StoryCandidates(
            stories=_stories(),
            memory=FakeMemoryStore(now=lambda: AT),
            limit=limit,
            lines=3,
            notes=notes,
            episodes=episodes,
        )


# --- the story-links stage (§6:12, §6:13) --------------------------------------------


async def _view(stories: FakeStoryStore, story_id: str) -> StoryViewPage:
    view = await stories.view(story_id)
    assert view is not None
    return view


async def _lines_of(stories: FakeStoryStore, story_id: str) -> list[tuple[StoryChange, str | None]]:
    page = await stories.log(story_id)
    assert page is not None
    return [(line.change, None if line.member is None else line.member.id) for line in page.lines]


async def test_a_story_link_links_the_activation_with_the_understanding_actor() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"))

    decision = await StoryLinksStage(stories=stories).record([story(trip)], activation_id="now")

    assert (decision.outcome, decision.linked, decision.started) == (
        StageOutcome.DONE,
        (trip,),
        None,
    )
    log = await stories.log(trip)
    assert log is not None
    added = log.lines[-1]
    assert (added.change, added.member, added.actor, added.trigger) == (
        StoryChange.ADDED,
        activation("now"),
        StoryActor.UNDERSTANDING,
        "now",
    )


async def test_a_link_to_a_merged_story_follows_it_to_where_it_went() -> None:
    stories = _stories()
    absorbed = await _story(stories, activation("a-1"))
    middle = await _story(stories, activation("a-2"))
    last = await _story(stories, activation("a-3"))
    await stories.merge(absorbed, middle, actor=StoryActor.OWNER)
    await stories.merge(middle, last, actor=StoryActor.OWNER)

    decision = await StoryLinksStage(stories=stories).record([story(absorbed)], activation_id="now")

    assert decision.linked == (last,)
    assert (StoryChange.ADDED, "now") in await _lines_of(stories, last)


async def test_every_merge_is_followed_however_long_the_chain() -> None:
    stories = _stories()
    chain = [await _story(stories, activation(f"a-{index}")) for index in range(70)]
    for absorbed, into in itertools.pairwise(chain):
        await stories.merge(absorbed, into, actor=StoryActor.OWNER)

    decision = await StoryLinksStage(stories=stories).record([story(chain[0])], activation_id="now")

    assert (decision.linked, decision.refused) == ((chain[-1],), ())


async def test_two_activations_linking_one_unstoried_episode_start_one_story() -> None:
    """§6:12's read-then-create, run for two activations at once, starts one story."""
    stories = _stories()
    reads = stories.stories_of

    async def yielding(member: StoryMember) -> tuple[StoryHeader, ...]:
        # Read first, then hand the loop to the other activation: between this read
        # and this run's create, the other reads the same "no story". Without the
        # stage's serialization this starts two stories.
        found = await reads(member)
        await asyncio.sleep(0)
        return found

    stories.stories_of = yielding  # type: ignore[method-assign]  # an interleaving point
    stage = StoryLinksStage(stories=stories)

    first, second = await asyncio.gather(
        stage.record([activation("e-1")], activation_id="a"),
        stage.record([activation("e-1")], activation_id="b"),
    )

    assert first.started is not None
    assert (second.started, second.linked) == (None, (first.started,))
    assert [entry.member for entry in (await _view(stories, first.started)).entries] == [
        activation("e-1"),
        activation("a"),
        activation("b"),
    ]


async def test_an_earlier_episode_s_stories_take_the_activation() -> None:
    stories = _stories()
    first = await _story(stories, activation("a-1"))
    second = await _story(stories, activation("a-1"), activation("a-2"))

    decision = await StoryLinksStage(stories=stories).record(
        [activation("a-1"), story(first)], activation_id="now"
    )

    assert decision.linked == (second, first)
    assert decision.started is None


async def test_earlier_episodes_in_no_story_start_one_story_with_the_activation() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-9"))

    decision = await StoryLinksStage(stories=stories).record(
        [activation("a-1"), story(trip), activation("a-2")], activation_id="now"
    )

    assert decision.started is not None
    assert decision.linked == (trip,)
    view = await stories.view(decision.started)
    assert view is not None
    assert [entry.member for entry in view.entries] == [
        activation("a-1"),
        activation("a-2"),
        activation("now"),
    ]
    assert {entry.actor for entry in view.entries} == {StoryActor.UNDERSTANDING}


async def test_no_links_write_nothing() -> None:
    stories = _stories()

    decision = await StoryLinksStage(stories=stories).record((), activation_id="now")

    assert (decision.outcome, decision.linked, decision.started) == (StageOutcome.DONE, (), None)
    assert (await stories.stories()).stories == ()


async def test_a_refused_link_is_recorded_and_the_rest_goes_on() -> None:
    stories = _stories()
    trip = await _story(stories, activation("a-1"))

    decision = await StoryLinksStage(stories=stories).record(
        [story("story:missing"), story(trip)], activation_id="now"
    )

    assert decision.outcome is StageOutcome.DONE
    assert [refusal.reason for refusal in decision.refused] == [StoryRefusalReason.UNKNOWN_STORY]
    assert decision.linked == (trip,)


async def test_a_story_store_error_is_a_failed_decision_carrying_it() -> None:
    stories = _stories()
    created = await stories.create([activation("a-1")], actor=StoryActor.OWNER)
    assert created.story_id is not None
    stories = failing(stories, "link")

    decision = await StoryLinksStage(stories=stories).record(
        [story(created.story_id)], activation_id="now"
    )

    assert decision.outcome is StageOutcome.FAILED
    assert isinstance(decision.error, StoryStoreError)
