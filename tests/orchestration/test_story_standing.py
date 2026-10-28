"""ADR-0300 §8:1: where a matter stands, assembled from the records for one reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    MAX_STORY_PAGE,
    STORY_STANDING_RECENT,
    ActivationEffect,
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
    StoryEffectState,
    StoryMember,
    StoryMemberKind,
    StoryRelated,
    StoryRelation,
    StoryStanding,
    StoryStandingEarlier,
    StoryStandingEffect,
    ToolOutcome,
    UnderstandingOmission,
    UnderstandingProducer,
    WholeTextReply,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.story_standing import OWNER_READER, story_standing
from ai_assistant.testing import FakeMemoryStore, FakePlanStore, FakeStoryStore
from ai_assistant.testing.activation import ended_pass
from ai_assistant.testing.parties import parties_for

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import StoryHeader, StoryViewPage

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
        parties=parties_for(origin),
    )


def _understanding(meaning: str, version: int = 1) -> ActivationUnderstanding:
    return ActivationUnderstanding(
        version=version,
        recorded_at=_AT,
        producer=UnderstandingProducer.INTERPRETATION,
        meaning=meaning,
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


class _Interleaved:
    """The two reads the assembler makes of a story store, with a write landing between.

    ``before_next_page`` runs once, before the first read of a page after the first;
    ``before_reverse_lookup`` once, before the reverse lookup of related stories.
    """

    def __init__(
        self,
        inner: FakeStoryStore,
        *,
        before_next_page: Callable[[], Awaitable[None]] | None = None,
        before_reverse_lookup: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._before_next_page = before_next_page
        self._before_reverse_lookup = before_reverse_lookup

    async def view(
        self, story_id: str, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryViewPage | None:
        if cursor is not None and (hook := self._before_next_page) is not None:
            self._before_next_page = None
            await hook()
        return await self._inner.view(story_id, cursor=cursor, limit=limit)

    async def stories_of(self, member: StoryMember) -> tuple[StoryHeader, ...]:
        if (hook := self._before_reverse_lookup) is not None:
            self._before_reverse_lookup = None
            await hook()
        return await self._inner.stories_of(member)


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


async def test_story_standing_a_member_relinked_between_pages_is_shown_once() -> None:
    world = _World()
    total = MAX_STORY_PAGE + 1
    ids = [f"m{index:03d}" for index in range(total)]
    # The first member read is also the newest episode, so a duplicate would show twice.
    await world.episodes(
        *(
            _episode(id_, at=_AT + timedelta(minutes=total if index == 0 else index))
            for index, id_ in enumerate(ids)
        )
    )
    story = await world.story(*(_activation(id_) for id_ in ids))

    async def relink_the_first() -> None:
        await world.stories.unlink(story, [_activation(ids[0])], actor=StoryActor.OWNER)
        await world.stories.link(story, [_activation(ids[0])], actor=StoryActor.OWNER)

    stories = _Interleaved(world.stories, before_next_page=relink_the_first)

    standing = await story_standing(
        stories,  # type: ignore[arg-type]  # the two reads the assembler makes, interleaved
        world.memory,
        story,
        reader=OWNER_READER,
    )

    assert standing is not None
    shown = [moment.activation_id for moment in standing.recent]
    assert shown[0] == ids[0]
    assert len(set(shown)) == len(shown)
    assert standing.earlier is not None
    assert standing.earlier.episodes == total - STORY_STANDING_RECENT


async def test_story_standing_a_story_moved_around_it_between_reads_is_listed_once() -> None:
    world = _World()
    await world.episodes(_episode("a"), _episode("b"))
    inner = await world.story(_activation("a"))
    story = await world.story(_activation("b"), _story_member(inner))

    async def turn_it_inside_out() -> None:
        await world.stories.unlink(story, [_story_member(inner)], actor=StoryActor.OWNER)
        await world.stories.link(inner, [_story_member(story)], actor=StoryActor.OWNER)

    stories = _Interleaved(world.stories, before_reverse_lookup=turn_it_inside_out)

    standing = await story_standing(
        stories,  # type: ignore[arg-type]  # the two reads the assembler makes, interleaved
        world.memory,
        story,
        reader=OWNER_READER,
    )

    assert standing is not None
    assert standing.related == (
        StoryRelated(relation=StoryRelation.PART_OF, story_id=inner, member_count=2),
    )


# --- what was done (ADR-0300 §8:1, ADR-0306 §6) ------------------------------------


async def _effect(  # noqa: PLR0913 — one keyword per part of the record a case varies
    plans: FakePlanStore,
    effect_id: str,
    activation_id: str,
    *,
    at: datetime,
    outcome: ToolOutcome | None,
    message: bool = False,
) -> None:
    """Claim one effect record for ``activation_id`` and, where given, finish it."""
    if message:
        effect = ActivationEffect(
            id=effect_id,
            activation_id=activation_id,
            round="round:1",
            place="conversation:c1",
            claimed_at=at,
        )
    else:
        effect = ActivationEffect(
            id=effect_id,
            activation_id=activation_id,
            round="round:1",
            capability="book",
            values_digest="0" * 64,
            decision_id=f"decision:{effect_id}",
            claimed_at=at,
        )
    await plans.claim_activation_effect(effect, match=None)
    if outcome is not None:
        position = 0 if message and outcome is ToolOutcome.SUCCEEDED else None
        await plans.finish_activation_effect(effect_id, outcome, position=position)


async def test_story_standing_what_was_done_is_unknown_first_then_not_done_then_done() -> None:
    """ADR-0300 §8:1: each call's record, by state, the most recent first within each.

    A record still carrying no outcome is unknown, never done (ADR-0306 §5:5), and a
    message's record is not listed.
    """
    world = _World()
    await world.episodes(_episode("a"), _episode("b", at=_AT + timedelta(days=1)))
    story = await world.story(_activation("a"), _activation("b"))
    plans = FakePlanStore(now=lambda: _NOW)
    day = timedelta(days=1)
    await _effect(plans, "e1", "a", at=_AT, outcome=ToolOutcome.SUCCEEDED)
    await _effect(plans, "e2", "a", at=_AT + day, outcome=ToolOutcome.INDETERMINATE)
    await _effect(plans, "e3", "b", at=_AT + 2 * day, outcome=ToolOutcome.FAILED)
    await _effect(plans, "e4", "b", at=_AT + 3 * day, outcome=ToolOutcome.SUCCEEDED)
    await _effect(plans, "e5", "b", at=_AT + 4 * day, outcome=None)
    await _effect(plans, "m1", "b", at=_AT + 5 * day, outcome=ToolOutcome.SUCCEEDED, message=True)

    standing = await story_standing(
        world.stories, world.memory, story, reader=OWNER_READER, plans=plans
    )

    assert standing is not None
    assert standing.done == (
        StoryStandingEffect(activation_id="b", state=StoryEffectState.UNKNOWN, at=_AT + 4 * day),
        StoryStandingEffect(activation_id="a", state=StoryEffectState.UNKNOWN, at=_AT + day),
        StoryStandingEffect(activation_id="b", state=StoryEffectState.NOT_DONE, at=_AT + 2 * day),
        StoryStandingEffect(activation_id="b", state=StoryEffectState.DONE, at=_AT + 3 * day),
        StoryStandingEffect(activation_id="a", state=StoryEffectState.DONE, at=_AT),
    )


async def test_story_standing_lists_only_what_its_reader_is_shown_was_done() -> None:
    """ADR-0307 §6:4: where the matter stands comes only from what the audience admits.

    A model-facing reader is told nothing of an episode it may not be shown, an open
    one included; the owner is told of every live episode's.
    """
    world = _World()
    await world.episodes(
        _episode("shared"),
        _episode("owner-only", owner_only=True),
        _episode("running", open_=True),
    )
    story = await world.story(
        _activation("shared"), _activation("owner-only"), _activation("running")
    )
    plans = FakePlanStore(now=lambda: _NOW)
    for activation in ("shared", "owner-only", "running", "not-a-member"):
        await _effect(plans, f"e-{activation}", activation, at=_AT, outcome=ToolOutcome.SUCCEEDED)

    def done_by(standing: StoryStanding | None) -> set[str]:
        assert standing is not None
        return {effect.activation_id for effect in standing.done}

    unbounded = await story_standing(
        world.stories, world.memory, story, reader=_UNBOUNDED, plans=plans
    )
    bounded = await story_standing(world.stories, world.memory, story, reader=_BOUNDED, plans=plans)
    owner = await story_standing(
        world.stories, world.memory, story, reader=OWNER_READER, plans=plans
    )

    assert done_by(unbounded) == {"shared"}
    assert done_by(bounded) == {"shared", "owner-only"}
    assert done_by(owner) == {"shared", "owner-only", "running"}


async def test_story_standing_with_no_plan_store_lists_nothing_done() -> None:
    world = _World()
    await world.episodes(_episode("a"))
    story = await world.story(_activation("a"))

    standing = await story_standing(world.stories, world.memory, story, reader=OWNER_READER)

    assert standing is not None
    assert standing.done == ()


async def test_story_standing_an_unreadable_plan_store_is_the_reads_error() -> None:
    world = _World()
    await world.episodes(_episode("a"))
    story = await world.story(_activation("a"))

    with pytest.raises(PlanningError):
        await story_standing(
            world.stories, world.memory, story, reader=OWNER_READER, plans=_DownPlans()
        )


class _DownPlans(FakePlanStore):
    """A plan store whose effect records cannot be read."""

    async def activation_effects(self, activation_ids: Sequence[str], /) -> tuple[Any, ...]:
        del activation_ids
        msg = "the plan store is down"
        raise PlanningError(msg)
