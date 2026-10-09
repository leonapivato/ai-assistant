"""ADR-0303 §3's privacy default: the walk behind a summary, and what a reader is shown.

Decided from identities alone (§3:9-§3:12): the version logs say what stands behind a
summary, and the reader's own answers say which of it the reader may be shown.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any, Final

from story_support import AT, activation, episode

from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    StoryActor,
    StoryNote,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    StorySummaryVersionName,
)
from ai_assistant.orchestration.story_privacy import (
    Behind,
    SummaryVisibility,
    activation_of,
    behind,
)
from ai_assistant.testing import FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.types import StorySummaryVersionList


def _note(note_id: int, **fields: Any) -> StoryNote:
    values: dict[str, Any] = {
        "note_id": note_id,
        "text": "a note",
        "author": StoryNoteAuthor.PLANNING,
        "written_during": "a-1",
        "outside": False,
        "written_at": AT,
    }
    return StoryNote.model_validate(values | fields)


_PLANNED: Final = _note(1)
_OWNER: Final = _note(3, author=StoryNoteAuthor.OWNER, written_during=None)


def _stories() -> FakeStoryStore:
    ids = count(1)
    return FakeStoryStore(now=lambda: AT, new_id=lambda: f"story:{next(ids)}")


async def _story(stories: FakeStoryStore, *activations: str) -> str:
    created = await stories.create([activation(one) for one in activations], actor=StoryActor.OWNER)
    assert created.story_id is not None
    return created.story_id


async def _note_on(stories: FakeStoryStore, story_id: str, text: str) -> int:
    written = await stories.append_note(story_id, text, author=StoryNoteAuthor.OWNER)
    assert written.note is not None
    return written.note.note_id


async def _summary(
    stories: FakeStoryStore,
    story_id: str,
    *,
    episodes: tuple[str, ...] = (),
    notes: tuple[int, ...] = (),
    read: tuple[tuple[str, int], ...] = (),
) -> int:
    """Write a summary taking in ``episodes`` and ``notes``, having read the ``read`` ones."""
    state = await stories.current_summary(story_id)
    assert state is not None
    written = await stories.write_summary(
        story_id,
        StorySummaryDraft(
            lines=(StorySummaryLine(text="A line."),),
            took_in_notes=notes,
            took_in_episodes=episodes,
            read_pages=tuple(StorySummaryVersionName(story=s, version=v) for s, v in read),
            outside=False,
        ),
        as_of=state.as_of,
    )
    assert written.version is not None, written
    return written.version.version


# --- the walk (§3:10) ---------------------------------------------------------------


async def test_behind_a_version_is_everything_every_earlier_version_of_its_story_took_in() -> None:
    """Each run reads the summary it replaces, so what an earlier version took in stays."""
    stories = _stories()
    trip = await _story(stories, "a-1", "a-2")
    first_note = await _note_on(stories, trip, "No Fridays")
    await _summary(stories, trip, episodes=("a-1",), notes=(first_note,))
    second = await _summary(stories, trip, episodes=("a-2",))

    found = await behind(stories, trip, second)

    assert found == Behind(
        notes=frozenset({first_note}), episodes=frozenset({"a-1", "a-2"}), complete=True
    )


async def test_behind_a_version_is_nothing_its_story_took_in_after_it() -> None:
    stories = _stories()
    trip = await _story(stories, "a-1", "a-2")
    first = await _summary(stories, trip, episodes=("a-1",))
    await _summary(stories, trip, episodes=("a-2",))

    assert (await behind(stories, trip, first)).episodes == frozenset({"a-1"})


async def test_the_walk_follows_the_summaries_a_run_read_into_other_stories_and_their_history() -> (
    None
):
    """A line shown for a flag may have been copied, so what stands behind it stands here."""
    stories = _stories()
    trip = await _story(stories, "a-1")
    car = await _story(stories, "c-1", "c-2", "c-3")
    garage = await _story(stories, "g-1")
    garage_read = await _summary(stories, garage, episodes=("g-1",))
    await _summary(stories, car, episodes=("c-1",))
    car_read = await _summary(stories, car, episodes=("c-2",), read=((garage, garage_read),))
    await _summary(stories, car, episodes=("c-3",))  # after the version the trip read
    version = await _summary(stories, trip, episodes=("a-1",), read=((car, car_read),))

    found = await behind(stories, trip, version)

    assert found.episodes == frozenset({"a-1", "c-1", "c-2", "g-1"})
    assert found.complete


async def test_the_walk_reads_each_story_s_log_once_and_ends_on_a_cycle() -> None:
    """A story's summary can reach its own earlier versions through another's."""
    stories = _stories()
    trip = await _story(stories, "a-1", "a-2")
    car = await _story(stories, "c-1")
    trip_first = await _summary(stories, trip, episodes=("a-1",))
    car_first = await _summary(stories, car, episodes=("c-1",), read=((trip, trip_first),))
    version = await _summary(stories, trip, episodes=("a-2",), read=((car, car_first),))
    listing = stories.summary_versions
    reads: list[str] = []

    async def counted(
        story_id: str, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StorySummaryVersionList | None:
        reads.append(story_id)
        return await listing(story_id, cursor=cursor, limit=limit)

    stories.summary_versions = counted  # type: ignore[method-assign]  # counting the reads

    found = await behind(stories, trip, version)

    assert found.episodes == frozenset({"a-1", "a-2", "c-1"})
    assert sorted(reads) == sorted([trip, car])


async def test_a_log_read_page_by_page_is_walked_whole() -> None:
    stories = _stories()
    trip = await _story(stories, *(f"a-{index}" for index in range(105)))
    for index in range(105):
        version = await _summary(stories, trip, episodes=(f"a-{index}",))

    found = await behind(stories, trip, version)

    assert len(found.episodes) == 105
    assert found.complete


async def test_a_version_the_store_does_not_answer_for_leaves_the_walk_incomplete() -> None:
    """A story the store no longer holds, or a version past its log's end, is unread."""
    stories = _stories()
    trip = await _story(stories, "a-1")
    car = await _story(stories, "c-1")
    car_read = await _summary(stories, car, episodes=("c-1",))
    version = await _summary(stories, trip, episodes=("a-1",), read=((car, car_read),))
    listing = stories.summary_versions

    async def car_gone(
        story_id: str, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StorySummaryVersionList | None:
        if story_id == car:
            return None
        return await listing(story_id, cursor=cursor, limit=limit)

    beyond = await behind(stories, trip, version + 1)
    stories.summary_versions = car_gone  # type: ignore[method-assign]  # a story no longer held
    gone = await behind(stories, trip, version)

    assert not beyond.complete
    assert not gone.complete
    assert gone.episodes == frozenset({"a-1"})


# --- what a reader is shown (§3:9, §3:11, §3:12) -------------------------------------


def test_a_note_is_shown_where_an_owner_record_may_be_whoever_wrote_it() -> None:
    """§3:9: the activation it was written during decides nothing (§2:4)."""
    episodes = [episode("a-1")]
    for note in (_PLANNED, _OWNER):
        assert SummaryVisibility.of(episodes, owner_notes=True).note(note)
        assert not SummaryVisibility.of(episodes, owner_notes=False).note(note)


def test_a_summary_is_shown_only_where_every_episode_behind_it_may_be() -> None:
    standing = Behind(notes=frozenset(), episodes=frozenset({"a-1", "a-2"}), complete=True)

    assert SummaryVisibility.of([episode("a-1"), episode("a-2")], owner_notes=False).summary(
        standing
    )
    # One not looked up, or refused, withholds it as surely (§3:12).
    assert not SummaryVisibility.of([episode("a-1")], owner_notes=True).summary(standing)


def test_a_summary_with_a_note_behind_it_is_shown_only_where_an_owner_record_may_be() -> None:
    standing = Behind(notes=frozenset({7}), episodes=frozenset({"a-1"}), complete=True)

    assert SummaryVisibility.of([episode("a-1")], owner_notes=True).summary(standing)
    assert not SummaryVisibility.of([episode("a-1")], owner_notes=False).summary(standing)


def test_an_incomplete_walk_withholds_the_summary_from_every_reader() -> None:
    standing = Behind(notes=frozenset(), episodes=frozenset(), complete=False)

    assert not SummaryVisibility.of([episode("a-1")], owner_notes=True).summary(standing)


def test_a_summary_with_nothing_behind_it_is_shown_to_every_reader() -> None:
    standing = Behind(notes=frozenset(), episodes=frozenset(), complete=True)

    assert SummaryVisibility.of([], owner_notes=False).summary(standing)


def test_an_episode_recording_no_activation_contributes_nothing() -> None:
    legacy = episode("a-1").model_copy(update={"processing_record": None})

    assert activation_of(legacy) is None
    assert SummaryVisibility.of([legacy], owner_notes=False).activations == frozenset()
    assert activation_of(episode("a-1")) == "a-1"
