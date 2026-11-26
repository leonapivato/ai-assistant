"""A work's story reads and story calls go through its sight (ADR-0383 §7, §8).

Milestone 22's B8c: understanding's story candidates, the story-links stage, the story
views planning reads and planning's story calls read and write only through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the sight the work
carries (§7:7, §9:1). With stores built to withhold, an unidentified sender's work is
offered no candidates, shown no story, links to nothing, and a call naming a story of the
owner's is told exactly what one naming a story never written is told (§7:5, §8:2); a
story it starts takes its work's home (§4:1, §4:4). The owner's work reads and writes as
today at every level (§6:9). In the counting build every read answers as today and writes
its count as the work's (§11:1).
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import (
    AT,
    WORK_ACTIVATION,
    activation,
    address,
    episode,
    story,
    work_of,
)
from structlog.testing import capture_logs
from understanding_support import bound_stores

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    InputSender,
    MemoryWrite,
    MemoryWriteMode,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    ProposedCall,
    RecordHome,
    SightMode,
    StoryActor,
    StoryNoteAuthor,
    StoryRefusalReason,
    Sureness,
    ToolCall,
    ToolOutcome,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.phase_path import StoryReads
from ai_assistant.orchestration.remembering import EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT
from ai_assistant.orchestration.story_calls import (
    EPISODES_ARGUMENT,
    GROUP_STORY,
    INSIDE_ARGUMENT,
    INTO_ARGUMENT,
    LINK_STORY,
    MERGE_STORY,
    MOVE_STORY,
    NOTE_ARGUMENT,
    NOTE_STORY,
    NOTES_ARGUMENT,
    SPLIT_STORY,
    START_STORY,
    STORIES_ARGUMENT,
    STORY_ARGUMENT,
    TO_ARGUMENT,
    UNLINK_STORY,
    StartUnfinishedError,
    StoryCalls,
)
from ai_assistant.orchestration.story_links import StoryCandidates, StoryLinksStage
from ai_assistant.orchestration.story_privacy import SummaryVisibility
from ai_assistant.testing import FakeMemoryStore, FakePlanStore, FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson, Sight, ToolDefinition, ToolResult
    from ai_assistant.orchestration.activation_state import ActivationState

_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
_OWNER_WEAK: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.WEAK)
_UNIDENTIFIED: Final = InputSender(person=None, level=Sureness.NONE)
_LEVELS: Final = pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])

#: An earlier work of the owner's, in their story.
_EARLIER: Final = "a-earlier"
#: An id of the store's shape that no story was ever written under.
_NEVER: Final = "story:never"
_NOTE: Final = "Bring the tent."


class _World:
    """The story, memory and plan stores, all built to ``mode``, and the story stages over
    the one holder, as the composition root wires them; the owner's story holds an earlier
    episode of theirs and the running work's own, and carries a note."""

    def __init__(self, mode: SightMode) -> None:
        ids = count(1)
        self.stories = FakeStoryStore(
            now=lambda: AT, new_id=lambda: f"{next(ids)}", sight_mode=mode
        )
        self.memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
        self.plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
        stores = bound_stores(self.memory, self.stories, plans=self.plans)
        self.candidates = StoryCandidates(stores=stores, limit=5, lines=3, notes=2, episodes=2)
        self.links = StoryLinksStage(stores=stores)
        self.reads = StoryReads(stores=stores, short_views=self.candidates, episodes=2)
        self.calls = StoryCalls(stores=stores, stories=self.stories, memory=self.memory)
        self.trip = ""

    async def seed(self) -> None:
        await self.memory.write_atomic(
            [
                MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT)
                for one in (episode(_EARLIER), episode(WORK_ACTIVATION, open_=True))
            ]
        )
        made = await self.stories.create(
            [activation(_EARLIER), activation(WORK_ACTIVATION)],
            home=RecordHome.owners(),
            actor=StoryActor.OWNER,
        )
        assert made.story_id is not None
        self.trip = made.story_id
        await self.stories.append_note(self.trip, _NOTE, author=StoryNoteAuthor.OWNER)

    async def candidates_of(self, sight: Sight) -> Any:
        return await self.candidates.assemble(
            (episode(_EARLIER),),
            sight=sight,
            audience=_BOUNDED,
            recalled=(self.trip,),
            place=(_EARLIER,),
        )

    async def held(self) -> tuple[Any, ...]:
        """What the store holds of the owner's story, read unbound: members and notes."""
        view = await self.stories.view(self.trip)
        notes = await self.stories.notes(self.trip)
        assert view is not None
        assert notes is not None
        return (
            tuple(entry.member for entry in view.entries),
            tuple(note.text for note in notes.notes),
        )


async def _world(mode: SightMode) -> _World:
    world = _World(mode)
    await world.seed()
    return world


def _sight(state: ActivationState) -> Sight:
    sight = state.sight
    assert sight is not None
    return sight


def _call(tool: ToolDefinition, arguments: Mapping[str, FrozenJson], *, decision: str) -> ToolCall:
    """The call acting hands the runner, the hub's arguments filled for the running work."""
    filled: dict[str, FrozenJson] = dict(arguments)
    if EPISODE_ARGUMENT in tool.system_supplied:
        filled.setdefault(EPISODE_ARGUMENT, address(WORK_ACTIVATION))
    if OUTSIDE_CONTENT_ARGUMENT in tool.system_supplied:
        filled.setdefault(OUTSIDE_CONTENT_ARGUMENT, False)
    request = ActionRequest(tool=tool, parameters=filled)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    effect = None if tool.safe_to_repeat else f"effect:{decision}"
    made = PermissionDecision.from_request(
        request, ruling, id=decision, decided_at=AT, effect=effect
    )
    return ToolCall(request=request, decision=made)


def _naming(story_id: str) -> list[tuple[ToolDefinition, dict[str, FrozenJson]]]:
    """Every call but the tidy-up, each naming ``story_id`` wherever it names a story."""
    episodes: list[FrozenJson] = [address(_EARLIER)]
    return [
        (NOTE_STORY, {STORY_ARGUMENT: story_id, NOTE_ARGUMENT: "Pack light."}),
        (LINK_STORY, {STORY_ARGUMENT: story_id}),
        (UNLINK_STORY, {STORY_ARGUMENT: story_id}),
        (MERGE_STORY, {STORY_ARGUMENT: story_id, INTO_ARGUMENT: story_id}),
        (
            MOVE_STORY,
            {STORY_ARGUMENT: story_id, TO_ARGUMENT: story_id, EPISODES_ARGUMENT: episodes},
        ),
        (SPLIT_STORY, {STORY_ARGUMENT: story_id, EPISODES_ARGUMENT: episodes}),
        (GROUP_STORY, {STORIES_ARGUMENT: [story_id], NOTES_ARGUMENT: []}),
        (START_STORY, {NOTES_ARGUMENT: ["A trip."], INSIDE_ARGUMENT: story_id}),
    ]


async def _run_each(world: _World, story_id: str) -> list[ToolResult]:
    return [
        await world.calls.run(_call(tool, arguments, decision=f"d-{index}"))
        for index, (tool, arguments) in enumerate(_naming(story_id))
    ]


# --- an unidentified sender's work, with stores that withhold (§6's second row) -----------


async def test_an_unidentified_senders_work_is_offered_no_story_candidates() -> None:
    world = await _world(SightMode.WITHHOLD)
    with work_of(_UNIDENTIFIED) as work:
        candidates = await world.candidates_of(_sight(work))
        shown = await world.candidates.short_views(
            [world.trip],
            sight=_sight(work),
            audience=_BOUNDED,
            visibility=SummaryVisibility(owner_records=True),
        )
    assert (candidates.views, candidates.fetched, candidates.unreadable) == ((), (), False)
    assert shown == ()


async def test_an_unidentified_senders_work_sees_no_story_view() -> None:
    """Its own activation is in the owner's story, which it does not see (§7:4 names its
    episode, never a story holding it)."""
    world = await _world(SightMode.WITHHOLD)
    with work_of(_UNIDENTIFIED) as work:
        sight = _sight(work)
        read = await world.reads.read(
            WORK_ACTIVATION, sight=sight, understanding=None, audience=_BOUNDED, owner_records=True
        )
        view = await world.reads.view(
            world.trip, sight=sight, audience=_BOUNDED, owner_records=True
        )
        members = await world.reads.members([world.trip], sight=sight)
        states = await world.reads.states([world.trip], sight=sight)
    assert (read.stories, read.cited, read.unreadable) == ((), (), False)
    assert view is None
    assert members == {}
    assert states == {world.trip: None}


async def test_an_unidentified_senders_work_links_to_nothing() -> None:
    """A link naming the owner's story is refused as one naming a story never written."""
    world = await _world(SightMode.WITHHOLD)
    before = await world.held()
    with work_of(_UNIDENTIFIED) as work:
        sight = _sight(work)
        owners = await world.links.record(
            [story(world.trip)], sight=sight, activation_id=WORK_ACTIVATION, home=work.home
        )
        never = await world.links.record(
            [story(_NEVER)], sight=sight, activation_id=WORK_ACTIVATION, home=work.home
        )
    assert (owners.linked, owners.started) == (never.linked, never.started) == ((), None)
    assert [one.reason for one in owners.refused] == [one.reason for one in never.refused]
    assert [one.reason for one in owners.refused] == [StoryRefusalReason.UNKNOWN_STORY]
    assert await world.held() == before


async def test_a_story_an_unidentified_senders_work_starts_takes_its_works_home() -> None:
    """§4:1, §4:4: the owner's, whose connection it came by; and once written, the work
    does not see it (§7:4's own records are its episode, effects and approvals)."""
    world = await _world(SightMode.WITHHOLD)
    with work_of(_UNIDENTIFIED) as work:
        sight = _sight(work)
        decision = await world.links.record(
            [activation("a-never-written")],
            sight=sight,
            activation_id=WORK_ACTIVATION,
            home=work.home,
        )
        assert decision.started is not None
        seen = await world.stories.bound(sight).header(decision.started)
    header = await world.stories.header(decision.started)
    assert header is not None
    assert header.home == RecordHome.owners()
    assert seen is None


async def test_a_story_call_naming_the_owners_story_is_told_what_one_never_written_is() -> None:
    """§8:2: every call naming a story the work does not see gets exactly the answer the
    same call naming a story never written gets, and nothing of the owner's is written."""
    world = await _world(SightMode.WITHHOLD)
    before = await world.held()
    with work_of(_UNIDENTIFIED):
        owners = await _run_each(world, world.trip)
        never = await _run_each(world, _NEVER)
    assert owners == never
    assert all(one.outcome is ToolOutcome.FAILED for one in owners)
    assert await world.held() == before


def _proposed(story_id: str) -> ProposedCall:
    """A move naming a note, its labels already ids, as planning's own check leaves it."""
    return ProposedCall(
        call_id="c1",
        name="move_to_matter",
        arguments={STORY_ARGUMENT: story_id, TO_ARGUMENT: _NEVER, NOTES_ARGUMENT: ["1"]},
    )


async def test_the_hub_check_naming_the_owners_story_says_what_one_never_written_says() -> None:
    world = await _world(SightMode.WITHHOLD)
    with work_of(_UNIDENTIFIED) as work:
        reasons = [
            await world.calls.refusal(_proposed(story_id), sight=_sight(work), owner_records=True)
            for story_id in (world.trip, _NEVER)
        ]
    assert reasons[0] == reasons[1] == "the story named is not there"


async def test_a_start_by_an_unidentified_senders_work_lands_in_its_works_home_unfinished() -> None:
    """The story it creates is the owner's (§4:4) and not its own (§7:4), so its first
    notes, written next through the same bound store, are refused as written to a story
    it does not hold (§7:5): the start is unfinished, never reported done or not done
    (ADR-0306 §5:6). Recorded, not widened (#3743)."""
    world = await _world(SightMode.WITHHOLD)
    with work_of(_UNIDENTIFIED), pytest.raises(StartUnfinishedError):
        await world.calls.run(_call(START_STORY, {NOTES_ARGUMENT: ["A trip."]}, decision="d"))
    page = await world.stories.stories()
    (started,) = [one for one in page.stories if one.story_id != world.trip]
    assert started.home == RecordHome.owners()
    notes = await world.stories.notes(started.story_id)
    assert notes is not None
    assert notes.notes == ()


# --- the owner's work, with stores that withhold: as today (§6's first row, §6:9) --------


@_LEVELS
async def test_the_owners_work_reads_its_stories_as_today(sender: InputSender) -> None:
    withheld = await _world(SightMode.WITHHOLD)
    counted = await _world(SightMode.COUNT)
    with work_of(sender) as work:
        sight = _sight(work)
        assert await withheld.candidates_of(sight) == await counted.candidates_of(sight)
        for world in (withheld, counted):
            assert (await world.candidates_of(sight)).views
        reads = [
            (
                await world.reads.read(
                    WORK_ACTIVATION,
                    sight=sight,
                    understanding=None,
                    audience=_BOUNDED,
                    owner_records=True,
                ),
                await world.reads.view(
                    world.trip, sight=sight, audience=_BOUNDED, owner_records=True
                ),
                await world.reads.members([world.trip], sight=sight),
            )
            for world in (withheld, counted)
        ]
    assert reads[0] == reads[1]
    assert reads[0][0].stories
    assert reads[0][2] == {withheld.trip: 2}


@_LEVELS
async def test_the_owners_work_links_and_writes_as_today(sender: InputSender) -> None:
    world = await _world(SightMode.WITHHOLD)
    other = await world.stories.create(
        [activation(_EARLIER)], home=RecordHome.owners(), actor=StoryActor.OWNER
    )
    assert other.story_id is not None
    with work_of(sender) as work:
        decision = await world.links.record(
            [story(other.story_id)],
            sight=_sight(work),
            activation_id=WORK_ACTIVATION,
            home=work.home,
        )
        noted = await world.calls.run(
            _call(
                NOTE_STORY, {STORY_ARGUMENT: world.trip, NOTE_ARGUMENT: "Pack light."}, decision="d"
            )
        )
    assert decision.linked == (other.story_id,)
    assert decision.refused == ()
    assert noted.outcome is ToolOutcome.SUCCEEDED
    _, notes = await world.held()
    assert notes == (_NOTE, "Pack light.")


# --- the counting build: as today, each read the work's (§11:1) ----------------------------


async def test_in_the_counting_build_an_unidentified_senders_work_reads_as_today() -> None:
    world = await _world(SightMode.COUNT)
    with work_of(_OWNER) as owners:
        today = await world.candidates_of(_sight(owners))
    with work_of(_UNIDENTIFIED) as work, capture_logs() as logs:
        sight = _sight(work)
        candidates = await world.candidates_of(sight)
        read = await world.reads.read(
            WORK_ACTIVATION, sight=sight, understanding=None, audience=_BOUNDED, owner_records=True
        )
        noted = await world.calls.run(
            _call(
                NOTE_STORY, {STORY_ARGUMENT: world.trip, NOTE_ARGUMENT: "Pack light."}, decision="d"
            )
        )
    assert candidates == today
    assert read.stories
    assert noted.outcome is ToolOutcome.SUCCEEDED
    counted = [one for one in logs if one["event"] == "sight_counted"]
    assert {(one["store"], one["member"]) for one in counted} >= {
        ("stories", "stories_of"),
        ("stories", "current_summary"),
        ("stories", "view"),
        ("stories", "header"),
        ("memory", "get_many"),
        ("plans", "activation_effects"),
    }
    assert all(one["reader"] == "work" for one in counted)
    # What a work of the owner's would not have been withheld, this one is: counted, not
    # withheld, as anything seen by an anyone bound sees nothing.
    assert any(one["sees_nothing"] for one in counted)


async def test_the_engines_pass_hands_the_story_stages_its_works_sight() -> None:
    """On a chat turn from the owner's device, every story read the candidates and the
    links stage make counts as a work's, bound to the owner."""
    from phases_support import chat_turn  # noqa: PLC0415 — one harness
    from test_phases_before_planning import (  # noqa: PLC0415 — one harness
        _TURN,
        _linked,
        _proposal,
        _seeded,
        _stories,
    )

    from ai_assistant.testing import FakeModelProvider  # noqa: PLC0415

    stories = _stories()
    trip = (
        await stories.create([activation("a-1")], home=RecordHome.owners(), actor=StoryActor.OWNER)
    ).story_id
    assert trip is not None
    harness = _linked(
        await _seeded(), stories, model=FakeModelProvider(_proposal(belongs_to=["S1"]))
    )
    with capture_logs() as logs:
        await chat_turn(harness, _TURN)
    counts = [one for one in logs if one["event"] == "sight_counted" and one["store"] == "stories"]
    assert {one["member"] for one in counts} >= {"stories_of", "current_summary", "header"}
    assert all(one["reader"] == "work" for one in counts)
    assert all(one["bounds"] == ["person_owner"] for one in counts)
    assert all(one["other_home"] == one["no_home"] == one["sees_nothing"] == 0 for one in counts)
