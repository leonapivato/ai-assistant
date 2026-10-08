"""Shared story surface obligations from ADR-0289 §4 and ADR-0300 §8.

Run through the engine, the canonical fake engine and the wire client, each over an
injected memory store the suite seeds episodes into, so the existence check, the
resolved view and the payload fit are held to one answer on every implementation.
What the story store itself owes is ``tests/memory/story_store_contract.py``'s; this
suite asserts what the engine adds: the actor ``owner`` and no trigger on every
write, the activation check on create and link only, the view's resolution of
activation and story members, and the reads' pages fitting the payload limit; and,
for ADR-0300 §8's story commands, the owner's page under §11's default, where the
matter stands for the owner, the owner's note, and a move that checks no activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import OversizedValueError
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
    StoryDraftLine,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StoryPageDraft,
    StoryPageRefusalReason,
    StoryRefusalReason,
    StoryRelation,
    UnderstandingOmission,
)
from ai_assistant.orchestration.payloads import canonical_payload
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from ai_assistant.core.protocols import AssistantEngine, StoryStore
    from ai_assistant.testing import FakeMemoryStore

#: The payload limit every subject is built at: small enough that a page of a few
#: resolved members does not fit, so the fit is exercised rather than assumed.
STORY_LIMIT = 2048

#: The instant the injected stores read.
STORY_SURFACE_AT = datetime(2026, 10, 4, 12, tzinfo=UTC)

_CHANNEL = ChannelIdentity(channel_type="informational_event", instance_id="source")


@dataclass(frozen=True)
class StorySurfaceSubject:
    """An engine, the memory store its activation checks read, and its story store.

    The story store is the one the engine answers from, handed to the suite so it can
    write what no command writes: planning's notes and a tidy-up's page.
    """

    engine: AssistantEngine
    memory: FakeMemoryStore
    stories: StoryStore


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

    @pytest.mark.parametrize("operation", ["create_story", "link_story"])
    async def test_a_refusal_too_large_for_the_limit_is_refused_as_oversized(
        self, story_surface: StorySurfaceSubject, operation: str
    ) -> None:
        """An argument that fits can earn a refusal that does not; both engines refuse it.

        The refusal names the member back, so an activation id just under the argument
        limit makes an outcome over the result limit (ADR-0085 §8c).
        """
        subject = story_surface
        await _seeded(subject, "a1")
        story_id = await _created(subject, act("a1"))
        long_id = "x" * (STORY_LIMIT - 100)
        call = (
            subject.engine.create_story([act(long_id)])
            if operation == "create_story"
            else subject.engine.link_story(story_id, [act(long_id)])
        )
        with pytest.raises(OversizedValueError):
            await call
        assert [h.story_id for h in (await subject.engine.stories()).stories] == [story_id]

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

    # --- the story commands (ADR-0300 §8) ---------------------------------------

    async def test_a_note_the_owner_adds_is_pending_on_the_page(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """§8:3: written by ``owner``, resting on nothing, unmarked, and pending."""
        subject = story_surface
        await _seeded(subject, "a1")
        story_id = await _created(subject, act("a1"))
        outcome = await subject.engine.add_story_note(story_id, "Leaning against Saturday")
        assert outcome.refusal is None
        note = outcome.note
        assert note is not None
        assert note.author is StoryNoteAuthor.OWNER
        assert note.rests_on is None
        assert not note.outside
        assert note.text == "Leaning against Saturday"
        page = await subject.engine.story_page(story_id)
        assert page is not None
        assert page.story.story_id == story_id
        assert page.version is None
        assert page.tidied_at is None
        assert page.lines == ()
        assert page.pending_notes == (note,)
        assert page.pending_episodes == ("a1",)
        assert (page.withheld_lines, page.withheld_notes) == (0, 0)
        log = await subject.engine.story_log(story_id)
        assert log is not None
        assert len(log.lines) == 2  # a note is not a membership change

    async def test_a_note_to_no_story_or_a_merged_one_is_refused(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        absorbed = await _created(subject, act("a1"))
        kept = await _created(subject, act("a2"))
        await subject.engine.merge_stories(absorbed, kept)
        missing = await subject.engine.add_story_note("story:nowhere", "a note")
        assert missing.refusal is not None
        assert missing.refusal.reason is StoryPageRefusalReason.UNKNOWN_STORY
        assert missing.refusal.story_id == "story:nowhere"
        merged = await subject.engine.add_story_note(absorbed, "a note")
        assert merged.refusal is not None
        assert merged.refusal.reason is StoryPageRefusalReason.MERGED_STORY
        assert merged.refusal.merged_into == kept
        page = await subject.engine.story_page(kept)
        assert page is not None
        assert page.pending_notes == ()

    async def test_a_malformed_note_or_move_is_refused_before_any_write(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1")
        story_id = await _created(subject, act("a1"))
        other = await _created(subject, act("a1"))
        for text in ("", "   ", "x" * 2001):
            with pytest.raises(ValueError, match="note's text"):
                await subject.engine.add_story_note(story_id, text)
        with pytest.raises(ValueError, match="story_id"):
            await subject.engine.add_story_note(" ", "a note")
        with pytest.raises(ValueError, match="from one story to another"):
            await subject.engine.move_story_members(story_id, story_id, [act("a1")])
        with pytest.raises(ValueError, match="activation members only"):
            await subject.engine.move_story_members(story_id, other, [sub(other)])
        with pytest.raises(ValueError, match="story_id"):
            await subject.engine.story_page("")
        with pytest.raises(ValueError, match="story_id"):
            await subject.engine.story_standing("")
        page = await subject.engine.story_page(story_id)
        assert page is not None
        assert page.pending_notes == ()
        view = await subject.engine.story(story_id)
        assert view is not None
        assert [m.member for m in view.members] == [act("a1")]

    async def test_the_page_shows_its_lines_and_marks_and_withholds_what_rests_on_the_forgotten(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """§8:3-§8:4, §11: the tidied page, marked, with the forgotten's notes withheld."""
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        await subject.memory.add(episode("running", running=True))
        story_id = await _created(subject, act("a1"), act("a2"), act("running"))
        stories = subject.stories
        from_email = await stories.append_note(
            story_id,
            "The campground's email gives Riverside",
            author=StoryNoteAuthor.PLANNING,
            rests_on="a1",
            outside=True,
        )
        on_a2 = await stories.append_note(
            story_id, "Booked Sunday", author=StoryNoteAuthor.PLANNING, rests_on="a2"
        )
        own = await subject.engine.add_story_note(story_id, "No Fridays")
        assert from_email.note is not None
        assert on_a2.note is not None
        assert own.note is not None
        state = await stories.current_page(story_id)
        assert state is not None
        written = await stories.write_page(
            story_id,
            StoryPageDraft(
                lines=(
                    StoryDraftLine(
                        text="A camping trip, Riverside",
                        cites=(from_email.note.note_id,),
                        outside=True,
                    ),
                    StoryDraftLine(
                        text="Booked Sunday", cites=(on_a2.note.note_id,), outside=False
                    ),
                    StoryDraftLine(text="No Fridays", cites=(own.note.note_id,), outside=False),
                ),
                took_in_notes=tuple(note.note_id for note in state.pending_notes),
                took_in_episodes=("a1", "a2"),
            ),
            as_of=state.as_of,
        )
        assert written.version is not None
        later = await stories.append_note(
            story_id, "Waiting on the canoe", author=StoryNoteAuthor.PLANNING, rests_on="running"
        )
        gone = await stories.append_note(
            story_id, "Check the dog policy", author=StoryNoteAuthor.PLANNING, rests_on="a2"
        )
        assert later.note is not None
        page = await subject.engine.story_page(story_id)
        assert page is not None
        assert page.version == written.version.version
        assert page.tidied_at == written.version.written_at
        assert [(line.text, line.outside) for line in page.lines] == [
            ("A camping trip, Riverside", True),
            ("Booked Sunday", False),
            ("No Fridays", False),
        ]
        # A note resting on an open episode is shown to the owner, who reads every record.
        assert [note.text for note in page.pending_notes] == [
            "Waiting on the canoe",
            "Check the dog policy",
        ]
        assert page.pending_episodes == ("running",)
        assert await subject.memory.delete("activation:a2")
        withheld = await subject.engine.story_page(story_id)
        assert withheld is not None
        assert [line.text for line in withheld.lines] == ["A camping trip, Riverside", "No Fridays"]
        assert withheld.withheld_lines == 1
        assert withheld.pending_notes == (later.note,)
        assert withheld.withheld_notes == 1
        assert gone.note is not None

    async def test_a_note_resting_on_an_episode_with_no_processing_record_is_shown(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """Held at its address is enough for the owner: no field of the record decides."""
        subject = story_surface
        at = STORY_SURFACE_AT
        await subject.memory.add(
            EpisodicMemory(
                id="activation:bare",
                content="captured",
                occurred_at=at,
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.9, last_updated=at
                ),
            )
        )
        story_id = await _created(subject, act("bare"))
        written = await subject.stories.append_note(
            story_id, "Rests on a bare record", author=StoryNoteAuthor.PLANNING, rests_on="bare"
        )
        assert written.note is not None
        page = await subject.engine.story_page(story_id)
        assert page is not None
        assert page.pending_notes == (written.note,)
        assert page.withheld_notes == 0

    async def test_a_merged_or_unknown_story_page_and_standing(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        subject = story_surface
        await _seeded(subject, "a1", "a2")
        absorbed = await _created(subject, act("a1"))
        kept = await _created(subject, act("a2"))
        await subject.engine.add_story_note(absorbed, "Goes with the merge")
        await subject.engine.merge_stories(absorbed, kept)
        page = await subject.engine.story_page(absorbed)
        assert page is not None
        assert page.story.merged_into == kept
        assert (page.version, page.lines, page.pending_notes) == (None, (), ())
        moved = await subject.engine.story_page(kept)
        assert moved is not None
        assert [note.text for note in moved.pending_notes] == ["Goes with the merge"]
        standing = await subject.engine.story_standing(absorbed)
        assert standing is not None
        assert standing.story.merged_into == kept
        assert standing.recent == ()
        assert await subject.engine.story_page("story:nowhere") is None
        assert await subject.engine.story_standing("story:nowhere") is None

    async def test_where_the_matter_stands_for_the_owner(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """§8:1 for the owner: every live episode, an open one in progress, and its parents."""
        subject = story_surface
        await _seeded(subject, "a1")
        await subject.memory.add(episode("running", running=True))
        inner = await _created(subject, act("a1"), act("running"))
        outer = await _created(subject, sub(inner))
        standing = await subject.engine.story_standing(inner)
        assert standing is not None
        assert standing.story.story_id == inner
        assert standing.done == ()
        assert {moment.activation_id for moment in standing.recent} == {"a1", "running"}
        progress = {moment.activation_id: moment.in_progress for moment in standing.recent}
        assert progress == {"a1": False, "running": True}
        # The suite's episodes are outside content, by their trigger's origin.
        assert all(moment.outside for moment in standing.recent)
        assert standing.earlier is None
        assert [(item.relation, item.story_id) for item in standing.related] == [
            (StoryRelation.PART_OF, outer)
        ]

    async def test_a_move_takes_the_notes_with_it_and_checks_no_activation(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """ADR-0300 §3:14 as the owner; like a merge or a split, no record is read."""
        subject = story_surface
        await _seeded(subject, "a1", "a2", "a3")
        source = await _created(subject, act("a1"), act("a2"))
        target = await _created(subject, act("a3"))
        resting = await subject.stories.append_note(
            source, "Leaning against Saturday", author=StoryNoteAuthor.PLANNING, rests_on="a1"
        )
        assert resting.note is not None
        assert await subject.memory.delete("activation:a1")
        moved = await subject.engine.move_story_members(source, target, [act("a1")])
        assert moved.refusal is None
        assert moved.story_id == target
        assert moved.logged == 2
        view = await subject.engine.story(target)
        assert view is not None
        assert [m.member for m in view.members] == [act("a3"), act("a1")]
        log = await subject.engine.story_log(target)
        assert log is not None
        assert log.lines[-1].change is StoryChange.ADDED
        assert all(line.actor is StoryActor.OWNER for line in log.lines)
        assert all(line.trigger is None for line in log.lines)
        page = await subject.engine.story_page(target)
        assert page is not None
        # Moved, and withheld: its episode is forgotten, so §11 shows the owner a count.
        assert page.withheld_notes == 1
        refused = await subject.engine.move_story_members(source, target, [act("a3")])
        assert refused.refusal is not None
        assert refused.refusal.reason is StoryRefusalReason.NOT_A_MEMBER
        assert refused.refusal.member == act("a3")
        unknown = await subject.engine.move_story_members("story:nowhere", target, [act("a2")])
        assert unknown.refusal is not None
        assert unknown.refusal.reason is StoryRefusalReason.UNKNOWN_STORY
        empty = await subject.engine.move_story_members(source, target, [])
        assert empty.refusal is not None
        assert empty.refusal.reason is StoryRefusalReason.NO_MEMBERS

    async def test_a_page_too_large_for_the_limit_is_refused_as_oversized(
        self, story_surface: StorySurfaceSubject
    ) -> None:
        """The page is read whole (§8:3); one over the limit earns the size refusal."""
        subject = story_surface
        await _seeded(subject, "a1")
        story_id = await _created(subject, act("a1"))
        for index in range(3):
            written = await subject.engine.add_story_note(story_id, f"{index} " + "n" * 800)
            assert written.note is not None
        with pytest.raises(OversizedValueError):
            await subject.engine.story_page(story_id)
