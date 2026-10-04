"""Shared story surface obligations from ADR-0289 §4.

Run through the engine, the canonical fake engine and the wire client, each over an
injected memory store the suite seeds episodes into, so the existence check, the
resolved view and the payload fit are held to one answer on every implementation.
What the story store itself owes is ``tests/memory/story_store_contract.py``'s; this
suite asserts what the engine adds: the actor ``owner`` and no trigger on every
write, the activation check on create and link only, the view's resolution of
activation and story members, and the reads' pages fitting the payload limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    ControllerRule,
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
    StoryChange,
    StoryMember,
    StoryMemberKind,
    StoryRefusalReason,
    UnderstandingOmission,
)
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.testing import FakeMemoryStore

#: The payload limit every subject is built at: small enough that a page of a few
#: resolved members does not fit, so the fit is exercised rather than assumed.
STORY_LIMIT = 2048

#: The instant the injected stores read.
STORY_SURFACE_AT = datetime(2026, 10, 4, 12, tzinfo=UTC)

_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")


@dataclass(frozen=True)
class StorySurfaceSubject:
    """An engine and the memory store its activation checks read."""

    engine: AssistantEngine
    memory: FakeMemoryStore


def episode(activation_id: str, *, running: bool = False) -> EpisodicMemory:
    """The episode at ``activation:<activation_id>``, frozen or still open."""
    at = STORY_SURFACE_AT
    return EpisodicMemory(
        id=f"activation:{activation_id}",
        content="",
        occurred_at=at,
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.9, last_updated=at),
        processing_record=EpisodeProcessingRecord(
            activation_id=activation_id,
            started_at=at,
            ended_at=None if running else at,
            trigger=RecordedChannelTrigger(
                target=_CHANNEL,
                channel=_CHANNEL,
                payload=RecordedTextInput(text="input"),
                context=ChannelContext(),
                reply=None,
                origin=InputOrigin.OUTSIDE,
            ),
            status=None if running else ProcessingStatus.FAILED,
            reason=None if running else ProcessingReason.PROCESSING_FAILED,
            understanding_omitted=None if running else UnderstandingOmission.NOT_REACHED,
            stages=() if running else ended_pass(at, ControllerRule.STAGE_FAILED),
        ),
        placement=Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=at)
        if running
        else Placement(),
    )


def act(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


def sub(story_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.STORY, id=story_id)


async def _seeded(subject: StorySurfaceSubject, *activation_ids: str) -> None:
    for activation_id in activation_ids:
        await subject.memory.add(episode(activation_id))


async def _created(subject: StorySurfaceSubject, *members: StoryMember) -> str:
    outcome = await subject.engine.create_story(members)
    assert outcome.refusal is None, outcome
    assert outcome.story_id is not None
    return outcome.story_id


class StorySurfaceContract:
    """The nine story methods, through every ``AssistantEngine`` implementation."""

    @pytest.fixture
    def story_surface(self) -> StorySurfaceSubject:
        """Override: an implementation at ``STORY_LIMIT`` over a seedable memory store."""
        raise NotImplementedError

    async def test_a_created_story_resolves_its_members(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """Activation members resolve to their episodes; the write is the owner's."""
        subject = story_surface
        await _seeded(subject, "a1")
        await subject.memory.add(episode("running", running=True))
        story_id = await _created(subject, act("a1"), act("running"))
        view = await subject.engine.story(story_id)
        assert view is not None
        assert view.story.story_id == story_id
        assert view.member_count == 2
        assert [m.member for m in view.members] == [act("a1"), act("running")]
        first, second = view.members
        assert first.episode is not None
        assert first.episode.position.episode_id == "activation:a1"
        assert first.episode.status is ProcessingStatus.FAILED
        assert not first.forgotten
        assert second.episode is not None
        assert second.episode.status is None  # an open episode: its activation runs on
        assert all(m.actor is StoryActor.OWNER for m in view.members)
        log = await subject.engine.story_log(story_id)
        assert log is not None
        assert [line.change for line in log.lines] == [
            StoryChange.CREATED,
            StoryChange.ADDED,
            StoryChange.ADDED,
        ]
        assert all(line.actor is StoryActor.OWNER for line in log.lines)
        assert all(line.trigger is None for line in log.lines)

    async def test_create_or_link_naming_an_activation_with_no_record_is_refused(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1")
        outcome = await subject.engine.create_story([act("a1"), act("ghost")])
        assert outcome.story_id is None
        assert outcome.refusal is not None
        assert outcome.refusal.reason is StoryRefusalReason.UNKNOWN_ACTIVATION
        assert outcome.refusal.member == act("ghost")
        assert (await subject.engine.stories()).stories == ()
        story_id = await _created(subject, act("a1"))
        linked = await subject.engine.link_story(story_id, [act("ghost")])
        assert linked.refusal is not None
        assert linked.refusal.reason is StoryRefusalReason.UNKNOWN_ACTIVATION
        log = await subject.engine.story_log(story_id)
        assert log is not None
        assert len(log.lines) == 2

    async def test_merge_and_split_move_a_forgotten_activation(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """Only create and link check a record; a forgotten member moves and is marked."""
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        source = await _created(subject, act("a1"), act("a2"))
        target = await _created(subject, act("a2"))
        assert await subject.memory.delete("activation:a1")
        split = await subject.engine.split_story(source, [act("a1")])
        assert split.refusal is None
        assert split.story_id is not None
        merged = await subject.engine.merge_stories(split.story_id, target)
        assert merged.refusal is None
        assert merged.story_id == target
        view = await subject.engine.story(target)
        assert view is not None
        assert [m.member for m in view.members] == [act("a2"), act("a1")]
        forgotten = view.members[1]
        assert forgotten.forgotten
        assert forgotten.episode is None
        assert forgotten.member_count is None
        unlinked = await subject.engine.unlink_story(target, [act("a1")])
        assert unlinked.logged == 1

    async def test_a_story_member_resolves_to_its_count_one_level_deep(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1", "a2", "a3")
        inner = await _created(subject, act("a1"), act("a2"))
        outer = await _created(subject, act("a3"))
        assert (await subject.engine.link_story(outer, [sub(inner)])).logged == 1
        view = await subject.engine.story(outer)
        assert view is not None
        nested = view.members[1]
        assert nested.member == sub(inner)
        assert nested.member_count == 2
        assert nested.episode is None
        assert not nested.forgotten
        loop = await subject.engine.link_story(inner, [sub(outer)])
        assert loop.refusal is not None
        assert loop.refusal.reason is StoryRefusalReason.LOOP
        assert loop.refusal.loop == (inner, outer)

    async def test_a_merged_story_reads_as_its_header(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        absorbed = await _created(subject, act("a1"))
        target = await _created(subject, act("a2"))
        await subject.engine.merge_stories(absorbed, target)
        view = await subject.engine.story(absorbed)
        assert view is not None
        assert view.story.merged_into == target
        assert view.members == ()
        refused = await subject.engine.link_story(absorbed, [act("a2")])
        assert refused.refusal is not None
        assert refused.refusal.reason is StoryRefusalReason.MERGED_STORY
        assert refused.refusal.merged_into == target
        assert await subject.engine.story("story:nowhere") is None
        assert await subject.engine.story_log("story:nowhere") is None

    async def test_the_activation_lookup_and_the_listing(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        first = await _created(subject, act("a1"))
        second = await _created(subject, act("a1"), act("a2"))
        found = await subject.engine.activation_stories("a1")
        assert [header.story_id for header in found] == [second, first]
        assert await subject.engine.activation_stories("nobody") == ()
        page = await subject.engine.stories(limit=1)
        assert [header.story_id for header in page.stories] == [second]
        assert page.next_cursor is not None
        rest = await subject.engine.stories(cursor=page.next_cursor, limit=1)
        assert [header.story_id for header in rest.stories] == [first]
        assert rest.next_cursor is None

    async def test_a_view_too_large_for_the_limit_is_shortened_and_resumes(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        ids = [f"activation-{n:02}" for n in range(12)]
        await _seeded(subject, *ids)
        story_id = await _created(subject, *(act(one) for one in ids))
        seen: list[StoryMember] = []
        cursor: int | None = None
        pages = 0
        while True:
            view = await subject.engine.story(story_id, cursor=cursor, limit=100)
            assert view is not None
            assert len(canonical_payload(view)) <= STORY_LIMIT
            assert view.members
            seen.extend(m.member for m in view.members)
            pages += 1
            if view.next_cursor is None:
                break
            cursor = view.next_cursor
        assert seen == [act(one) for one in ids]
        assert pages > 1
        log_lines = 0
        log_cursor: int | None = None
        while True:
            log = await subject.engine.story_log(story_id, cursor=log_cursor, limit=100)
            assert log is not None
            assert len(canonical_payload(log)) <= STORY_LIMIT
            log_lines += len(log.lines)
            if log.next_cursor is None:
                break
            log_cursor = log.next_cursor
        assert log_lines == 1 + len(ids)

    async def test_malformed_arguments_are_refused_before_any_write(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1")
        with pytest.raises(ValueError, match="member"):
            await subject.engine.create_story(["a1"])  # type: ignore[list-item]
        with pytest.raises(ValueError, match="story_id"):
            await subject.engine.link_story("  ", [act("a1")])
        with pytest.raises(ValueError, match="limit"):
            await subject.engine.stories(limit=0)
        with pytest.raises(ValueError, match="cursor"):
            await subject.engine.story_log("story:x", cursor=-1)
        with pytest.raises(ValueError, match="activation_id"):
            await subject.engine.activation_stories("")
        assert (await subject.engine.stories()).stories == ()
