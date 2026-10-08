"""ADR-0300 §8:1: where a matter stands, assembled from the records for one reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    STORY_STANDING_RECENT,
    ActivationUnderstanding,
    ChannelContext,
    ChannelIdentity,
    EpisodeProcessingRecord,
    EpisodicMemory,
    InputOrigin,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryRelated,
    StoryRelation,
    StoryStandingEarlier,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.story_standing import OWNER_READER, story_standing
from ai_assistant.testing import FakeMemoryStore, FakeStoryStore
from ai_assistant.testing.activation import ended_pass

_AT: Final = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
_NOW: Final = _AT + timedelta(days=30)
_CONVERSATION: Final = ChannelIdentity(channel_type="conversation", instance_id="c1")
_EVENTS: Final = ChannelIdentity(channel_type="informational_event", instance_id="mail")
_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=frozenset())


def _trigger(origin: InputOrigin) -> RecordedChannelTrigger:
    channel = _EVENTS if origin is InputOrigin.OUTSIDE else _CONVERSATION
    return RecordedChannelTrigger(
        target=channel,
        channel=channel,
        payload=RecordedTextInput(text="the raw input, never shown here"),
        context=ChannelContext(),
        reply=None if origin is InputOrigin.OUTSIDE else WholeTextReply(),
        origin=origin,
    )


def _understanding(meaning: str, version: int = 1) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=meaning,
        meaning_ground=UnderstandingGround.STATED,
    )


def _episode(  # noqa: PLR0913 — one keyword per part of the record a case varies
    activation_id: str,
    *,
    at: datetime = _AT,
    meanings: tuple[str, ...] = (),
    origin: InputOrigin = InputOrigin.USER,
    external: bool = False,
    open_: bool = False,
    owner_only: bool = False,
) -> EpisodicMemory:
    understanding = tuple(
        _understanding(meaning, version) for version, meaning in enumerate(meanings, start=1)
    )
    ending: dict[str, object] = {}
    if not open_:
        ending = {
            "ended_at": at,
            "status": ProcessingStatus.COMPLETED,
            "reason": ProcessingReason.RETURNED,
            "stages": ended_pass(at),
            "understanding_omitted": None if understanding else UnderstandingOmission.NOT_REACHED,
        }
    processing = EpisodeProcessingRecord.model_validate(
        {
            "activation_id": activation_id,
            "started_at": at,
            "trigger": _trigger(origin),
            "understanding": understanding,
            **ending,
        }
    )
    placement = (
        Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=at)
        if open_ or owner_only
        else Placement()
    )
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="" if open_ else f"the search text of {activation_id}",
        occurred_at=at,
        provenance=Provenance(
            source=MemorySource.OBSERVED,
            confidence=0.9,
            last_updated=at,
            derived_from_external=external,
        ),
        placement=placement,
        processing_record=processing,
    )


def _activation(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def _story_member(story_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


class _World:
    def __init__(self) -> None:
        self.stories = FakeStoryStore(now=lambda: _NOW)
        self.memory = FakeMemoryStore(now=lambda: _NOW)

    async def story(self, *members: StoryMember) -> str:
        outcome = await self.stories.create(list(members), actor=StoryActor.OWNER)
        assert outcome.story_id is not None
        return outcome.story_id

    async def episodes(self, *records: EpisodicMemory) -> None:
        for record in records:
            await self.memory.add(record)


async def test_story_standing_unknown_story_is_none() -> None:
    world = _World()

    standing = await story_standing(
        world.stories, world.memory, "story:missing", reader=OWNER_READER
    )

    assert standing is None


async def test_story_standing_timeline_runs_by_when_things_happened_most_recent_first() -> None:
    world = _World()
    await world.episodes(
        _episode("a", at=_AT, meanings=("booking a campsite",)),
        _episode("b", at=_AT + timedelta(days=2), meanings=("first reading", "moved to Sunday")),
        _episode("c", at=_AT + timedelta(days=1)),
    )
    story = await world.story(_activation("b"), _activation("a"), _activation("c"))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert [moment.activation_id for moment in standing.recent] == ["b", "c", "a"]
    assert [moment.meaning for moment in standing.recent] == [
        "moved to Sunday",
        None,
        "booking a campsite",
    ]
    assert standing.earlier is None
    assert standing.done == ()
    assert standing.related == ()


async def test_story_standing_older_episodes_are_summarised_as_counts() -> None:
    world = _World()
    total = STORY_STANDING_RECENT + 3
    ids = [f"e{index:02d}" for index in range(total)]
    await world.episodes(
        *(_episode(id_, at=_AT + timedelta(hours=index)) for index, id_ in enumerate(ids))
    )
    story = await world.story(*(_activation(id_) for id_ in ids))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert [moment.activation_id for moment in standing.recent] == ids[::-1][:STORY_STANDING_RECENT]
    assert standing.earlier == StoryStandingEarlier(
        episodes=3, first_at=_AT, last_at=_AT + timedelta(hours=2)
    )


async def test_story_standing_reads_every_page_of_a_large_story() -> None:
    world = _World()
    total = MAX_STORY_PAGE + 5
    ids = [f"m{index:03d}" for index in range(total)]
    await world.episodes(
        *(_episode(id_, at=_AT + timedelta(minutes=index)) for index, id_ in enumerate(ids))
    )
    story = await world.story(*(_activation(id_) for id_ in ids))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert standing.recent[0].activation_id == ids[-1]
    assert standing.earlier is not None
    assert standing.earlier.episodes == total - STORY_STANDING_RECENT
    assert standing.earlier.first_at == _AT


async def test_story_standing_a_tie_goes_to_the_member_linked_later() -> None:
    world = _World()
    await world.episodes(_episode("first"), _episode("second"))
    story = await world.story(_activation("first"), _activation("second"))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert [moment.activation_id for moment in standing.recent] == ["second", "first"]


async def test_story_standing_a_forgotten_episode_is_neither_shown_nor_counted() -> None:
    world = _World()
    await world.episodes(_episode("kept"))
    story = await world.story(_activation("kept"), _activation("gone"))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert [moment.activation_id for moment in standing.recent] == ["kept"]
    assert standing.earlier is None


async def test_story_standing_the_owner_sees_an_open_episode_in_progress() -> None:
    world = _World()
    await world.episodes(
        _episode("done", meanings=("the trip",)),
        _episode("running", at=_AT + timedelta(days=1), meanings=("still going",), open_=True),
    )
    story = await world.story(_activation("done"), _activation("running"))

    owner = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)
    model = await story_standing(world.stories, world.memory, story, reader=_BOUNDED)

    assert owner is not None
    assert [(m.activation_id, m.in_progress, m.meaning) for m in owner.recent] == [
        ("running", True, "still going"),
        ("done", False, "the trip"),
    ]
    assert model is not None
    assert [moment.activation_id for moment in model.recent] == ["done"]


async def test_story_standing_a_model_reader_is_shown_only_what_its_audience_admits() -> None:
    world = _World()
    await world.episodes(
        _episode("open-to-all", meanings=("the campsite",)),
        _episode("owner-only", at=_AT + timedelta(days=1), owner_only=True),
    )
    story = await world.story(_activation("open-to-all"), _activation("owner-only"))

    unbounded = await story_standing(world.stories, world.memory, story, reader=_UNBOUNDED)
    bounded = await story_standing(world.stories, world.memory, story, reader=_BOUNDED)
    owner = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert unbounded is not None
    assert [moment.activation_id for moment in unbounded.recent] == ["open-to-all"]
    assert unbounded.earlier is None
    assert bounded is not None
    assert [moment.activation_id for moment in bounded.recent] == ["owner-only", "open-to-all"]
    assert owner is not None
    assert [moment.activation_id for moment in owner.recent] == ["owner-only", "open-to-all"]


async def test_story_standing_withheld_episodes_are_not_counted_among_the_earlier() -> None:
    world = _World()
    shown = [f"s{index:02d}" for index in range(STORY_STANDING_RECENT)]
    await world.episodes(
        *(
            _episode(id_, at=_AT + timedelta(days=1, hours=index))
            for index, id_ in enumerate(shown)
        ),
        _episode("withheld", owner_only=True),
    )
    story = await world.story(_activation("withheld"), *(_activation(id_) for id_ in shown))

    unbounded = await story_standing(world.stories, world.memory, story, reader=_UNBOUNDED)
    owner = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert unbounded is not None
    assert unbounded.earlier is None
    assert owner is not None
    assert owner.earlier == StoryStandingEarlier(episodes=1, first_at=_AT, last_at=_AT)


@pytest.mark.parametrize(
    ("origin", "external", "marked"),
    [
        (InputOrigin.USER, False, False),
        (InputOrigin.OUTSIDE, False, True),
        (InputOrigin.USER, True, True),
    ],
)
async def test_story_standing_an_episode_resting_on_outside_content_is_marked(
    origin: InputOrigin, *, external: bool, marked: bool
) -> None:
    world = _World()
    await world.episodes(_episode("e", origin=origin, external=external, meanings=("a reply",)))
    story = await world.story(_activation("e"))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert [moment.outside for moment in standing.recent] == [marked]


async def test_story_standing_related_matters_are_one_membership_away() -> None:
    world = _World()
    await world.episodes(_episode("a"), _episode("b"), _episode("c"))
    inner = await world.story(_activation("a"), _activation("b"))
    story = await world.story(_activation("c"), _story_member(inner))
    outer = await world.story(_story_member(story))
    beside = await world.story(_activation("a"), _story_member(story))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert standing.related == (
        StoryRelated(relation=StoryRelation.PART_OF, story_id=beside, member_count=2),
        StoryRelated(relation=StoryRelation.PART_OF, story_id=outer, member_count=1),
        StoryRelated(relation=StoryRelation.CONTAINS, story_id=inner, member_count=2),
    )
    assert [moment.activation_id for moment in standing.recent] == ["c"]


async def test_story_standing_a_merged_story_carries_its_header_alone() -> None:
    world = _World()
    await world.episodes(_episode("a"), _episode("b"))
    absorbed = await world.story(_activation("a"))
    kept = await world.story(_activation("b"))
    await world.stories.merge(absorbed, kept, actor=StoryActor.OWNER)

    standing = await story_standing(world.stories, world.memory, absorbed, reader=OWNER_READER)

    assert standing is not None
    assert standing.story.merged_into == kept
    assert standing.recent == ()
    assert standing.related == ()
