"""Planning's story calls that write (ADR-0300 §10, ADR-0303 §9, ADR-0306 §3, ADR-0307 §5).

Each call's declaration, that it runs through acting's own-records seam and never the
invoker, the duplicate backstop refusing a repeated start or grouping, a note's writer,
what it was written during and its mark, link and unlink, the tidy-up's run, move, merge,
split and group, planning refusing a label it was never shown before anything is
authorized, and the hub's check refusing a move or a split naming a note not held, or
naming any note on a pass that may not show the owner's records.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from structured_support import structured

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    ActionRequest,
    CapabilityEffect,
    CapabilityResult,
    EpisodicMemory,
    InputOrigin,
    LabelKind,
    MemorySource,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanningLabel,
    PlanningRound,
    ProposedCall,
    Provenance,
    RoundResponse,
    StoryActor,
    StoryChange,
    StoryHeader,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
    ToolResult,
)
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    ActingStage,
    AuthorizedCall,
    AuthorizedRound,
    OwnRecordsByCapability,
)
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.planning import (
    DELIBERATE_REPEAT,
    PLANNING_PROMPT,
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    RefusedCall,
    offered_tools,
)
from ai_assistant.orchestration.remembering import EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT
from ai_assistant.orchestration.story_calls import (
    EPISODES_ARGUMENT,
    GROUP_STORY,
    INSIDE_ARGUMENT,
    INTO_ARGUMENT,
    LINK_STORY,
    MEMBER_EPISODE_ARGUMENT,
    MEMBER_STORY_ARGUMENT,
    MERGE_STORY,
    MOVE_STORY,
    NOTE_ARGUMENT,
    NOTE_STORY,
    NOTES_ARGUMENT,
    SPLIT_STORY,
    START_STORY,
    STORIES_ARGUMENT,
    STORY_ARGUMENT,
    STORY_CALL_CAPABILITIES,
    STORY_CALLS,
    STORY_LABEL_ARGUMENTS,
    TIDY_STORY,
    TO_ARGUMENT,
    UNLINK_STORY,
    StartUnfinishedError,
    StoryCalls,
)
from ai_assistant.orchestration.story_tidy_up import STORY_TIDY_UP_PROMPT, StoryTidyUp
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
    FakeToolCallingCompleter,
    default_prompt,
)

if TYPE_CHECKING:
    from ai_assistant.core.protocols import StoryStore
    from ai_assistant.core.types import FrozenJson, ToolDefinition

_AT: Final = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_ACTIVATION: Final = "act-1"
_EPISODE: Final = f"activation:{_ACTIVATION}"


def _now() -> datetime:
    return _AT


def _episode(episode_id: str) -> EpisodicMemory:
    return EpisodicMemory(
        id=episode_id,
        content="",
        provenance=Provenance(source=MemorySource.OBSERVED, confidence=0.5, last_updated=_AT),
        occurred_at=_AT - timedelta(days=1),
    )


def _call(
    tool: ToolDefinition,
    arguments: Mapping[str, FrozenJson],
    *,
    decision: str = "decision:1",
    effect: str | None = None,
) -> ToolCall:
    filled: dict[str, FrozenJson] = dict(arguments)
    if EPISODE_ARGUMENT in tool.system_supplied:
        filled.setdefault(EPISODE_ARGUMENT, _EPISODE)
    if OUTSIDE_CONTENT_ARGUMENT in tool.system_supplied:
        filled.setdefault(OUTSIDE_CONTENT_ARGUMENT, False)
    request = ActionRequest(tool=tool, parameters=filled)
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    if effect is None and not tool.safe_to_repeat:
        effect = f"effect:{decision}"
    made = PermissionDecision.from_request(
        request, ruling, id=decision, decided_at=_AT, effect=effect
    )
    return ToolCall(request=request, decision=made)


async def _stores() -> tuple[FakeStoryStore, FakeMemoryStore]:
    stories = FakeStoryStore(now=_now)
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(_EPISODE))
    await memory.add(_episode("activation:act-0"))
    return stories, memory


async def _story(stories: FakeStoryStore, *members: StoryMember) -> str:
    created = await stories.create(
        list(members) or [StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-0")],
        actor=StoryActor.OWNER,
    )
    assert created.story_id is not None
    return str(created.story_id)


async def _notes(stories: FakeStoryStore, story_id: str) -> list[Any]:
    page = await stories.notes(story_id)
    assert page is not None
    return list(page.notes)


async def _members(stories: FakeStoryStore, story_id: str) -> list[StoryMember]:
    page = await stories.view(story_id)
    assert page is not None
    return [entry.member for entry in page.entries]


class _NoInvoker:
    """A ``ToolInvoker`` a story call must never reach (ADR-0306 §3:3)."""

    async def invoke(self, call: ToolCall, *, timeout: timedelta) -> ToolResult:  # noqa: ASYNC109 — the seam's own signature
        del call, timeout
        msg = "a call to the assistant's own records never reaches the invoker"
        raise AssertionError(msg)


def _acting(plans: FakePlanStore, calls: StoryCalls) -> ActingStage:
    return ActingStage(
        plans=plans,
        invoker=_NoInvoker(),
        own_records=OwnRecordsByCapability(dict.fromkeys(STORY_CALL_CAPABILITIES, calls)),
        timeout=timedelta(seconds=5),
        now=_now,
    )


# --- the declarations --------------------------------------------------------------------


@pytest.mark.parametrize("tool", STORY_CALLS, ids=lambda tool: str(tool.capability))
def test_each_story_call_is_declared_as_ruled(tool: ToolDefinition) -> None:
    """ADR-0306 §3:1: own records, never leaves the hub, no result, never unknown."""
    assert tool.effect is CapabilityEffect.OWN_RECORDS
    assert tool.leaves_hub is False
    assert tool.result is CapabilityResult.NONE
    assert tool.outcome_can_be_unknown is False
    # Starting and grouping are not safe to repeat; every other story call is (ADR-0300
    # §10's table, ADR-0303 §9's).
    assert tool.safe_to_repeat is (tool not in {START_STORY, GROUP_STORY})


def test_the_hub_fills_the_episode_and_the_mark_and_planning_is_never_offered_them() -> None:
    """ADR-0254 §3, ADR-0306 §2:9-§2:10: what the hub fills is not offered; start alone
    is offered the deliberate-repeat mark."""
    offered = {one.name: one for one in offered_tools(STORY_CALLS)}

    assert set(offered) == set(STORY_CALL_CAPABILITIES)
    for name, tool in offered.items():
        properties = tool.parameters["properties"]
        assert isinstance(properties, Mapping)
        assert EPISODE_ARGUMENT not in properties
        assert OUTSIDE_CONTENT_ARGUMENT not in properties
        assert (DELIBERATE_REPEAT in properties) is (
            name in {str(START_STORY.capability), str(GROUP_STORY.capability)}
        )
    for marked in (START_STORY, NOTE_STORY, GROUP_STORY):
        assert marked.system_supplied == (EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT)
    for unmarked in (LINK_STORY, UNLINK_STORY, MOVE_STORY, MERGE_STORY, SPLIT_STORY):
        assert unmarked.system_supplied == (EPISODE_ARGUMENT,)
    assert TIDY_STORY.system_supplied == ()


def test_story_arguments_are_labels() -> None:
    """ADR-0307 §5:2: stories by ``S`` label, another activation by its episode's ``E``."""
    assert STORY_LABEL_ARGUMENTS[str(NOTE_STORY.capability)] == {STORY_ARGUMENT: LabelKind.STORY}
    assert STORY_LABEL_ARGUMENTS[str(START_STORY.capability)] == {INSIDE_ARGUMENT: LabelKind.STORY}
    for tool in (LINK_STORY, UNLINK_STORY):
        assert STORY_LABEL_ARGUMENTS[str(tool.capability)] == {
            STORY_ARGUMENT: LabelKind.STORY,
            MEMBER_STORY_ARGUMENT: LabelKind.STORY,
            MEMBER_EPISODE_ARGUMENT: LabelKind.EPISODE,
        }
    # ADR-0303 §9:4: stories by S, members by E or S, and notes by N.
    assert STORY_LABEL_ARGUMENTS[str(MOVE_STORY.capability)] == {
        STORY_ARGUMENT: LabelKind.STORY,
        TO_ARGUMENT: LabelKind.STORY,
        EPISODES_ARGUMENT: LabelKind.EPISODE,
        NOTES_ARGUMENT: LabelKind.NOTE,
    }
    assert STORY_LABEL_ARGUMENTS[str(MERGE_STORY.capability)] == {
        STORY_ARGUMENT: LabelKind.STORY,
        INTO_ARGUMENT: LabelKind.STORY,
    }
    assert STORY_LABEL_ARGUMENTS[str(SPLIT_STORY.capability)] == {
        STORY_ARGUMENT: LabelKind.STORY,
        EPISODES_ARGUMENT: LabelKind.EPISODE,
        STORIES_ARGUMENT: LabelKind.STORY,
        NOTES_ARGUMENT: LabelKind.NOTE,
    }
    assert STORY_LABEL_ARGUMENTS[str(GROUP_STORY.capability)] == {STORIES_ARGUMENT: LabelKind.STORY}
    # Every story call's declaration takes each label argument it names.
    for tool in STORY_CALLS:
        properties = tool.parameters_schema["properties"]
        assert isinstance(properties, Mapping)
        assert set(STORY_LABEL_ARGUMENTS[str(tool.capability)]) <= set(properties)


# --- start ---------------------------------------------------------------------------------


async def test_a_start_holds_this_activation_its_first_notes_and_sits_inside_a_story() -> None:
    """ADR-0300 §10:3: the activation's episode joins it; it sits inside the larger one."""
    stories, memory = await _stores()
    summer = await _story(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(
            START_STORY,
            {NOTES_ARGUMENT: ["A camping trip.", "Waiting on the reply."], INSIDE_ARGUMENT: summer},
        )
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    (started,) = await stories.stories_of(own)
    notes = await _notes(stories, str(started.story_id))
    assert [one.text for one in notes] == ["A camping trip.", "Waiting on the reply."]
    assert {(one.author, one.written_during, one.outside) for one in notes} == {
        (StoryNoteAuthor.PLANNING, _ACTIVATION, False)
    }
    assert await _members(stories, summer) == [
        StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-0"),
        StoryMember(kind=StoryMemberKind.STORY, id=started.story_id),
    ]
    log = await stories.log(str(started.story_id))
    assert log is not None
    assert {(line.actor, line.trigger) for line in log.lines} == {
        (StoryActor.PLANNING, _ACTIVATION)
    }


async def test_a_start_inside_a_story_not_there_starts_nothing() -> None:
    stories, memory = await _stores()
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(START_STORY, {NOTES_ARGUMENT: ["A trip."], INSIDE_ARGUMENT: "story:gone"})
    )

    assert result.outcome is ToolOutcome.FAILED
    own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    assert await stories.stories_of(own) == ()


async def test_a_start_repeated_identically_is_refused_as_already_done() -> None:
    """ADR-0306 §3:1, §5:9: not safe to repeat, so the backstop refuses the second."""
    stories, memory = await _stores()
    plans = FakePlanStore(now=_now)
    acting = _acting(plans, StoryCalls(stories=stories, memory=memory))
    notes: dict[str, FrozenJson] = {NOTES_ARGUMENT: ["A camping trip."]}

    first = await acting.act(
        AuthorizedRound(
            _ACTIVATION, "round:1", (AuthorizedCall(_call(START_STORY, notes, decision="d1")),)
        ),
        held=HeldResults(),
    )
    second = await acting.act(
        AuthorizedRound(
            _ACTIVATION, "round:2", (AuthorizedCall(_call(START_STORY, notes, decision="d2")),)
        ),
        held=HeldResults(),
    )

    assert [one.outcome for one in first.calls] == [ActedOutcome.DONE]
    assert [one.outcome for one in second.calls] == [ActedOutcome.NOT_DONE]
    assert second.calls[0].reason is not None
    assert second.calls[0].reason.startswith("already done")
    own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    assert len(await stories.stories_of(own)) == 1
    # Started differently, it is another start.
    third = await acting.act(
        AuthorizedRound(
            _ACTIVATION,
            "round:3",
            (
                AuthorizedCall(
                    _call(START_STORY, {NOTES_ARGUMENT: ["Visiting Mum."]}, decision="d3")
                ),
            ),
        ),
        held=HeldResults(),
    )
    assert [one.outcome for one in third.calls] == [ActedOutcome.DONE]
    assert len(await stories.stories_of(own)) == 2


class _FailsAfterCreate:
    """A story store that fails one write a start makes after creating its story.

    It wraps the canonical fake, which is final, and hands every other read and write
    to it.
    """

    def __init__(self, *, note_at: int | None = None, link: bool = False) -> None:
        self.inner = FakeStoryStore(now=_now)
        self._note_at = note_at
        self._link = link
        self._notes = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def append_note(self, story_id: str, text: str, **kwargs: Any) -> Any:
        self._notes += 1
        if self._notes == self._note_at:
            msg = "the store could not write the note"
            raise StoryStoreError(msg)
        return await self.inner.append_note(story_id, text, **kwargs)

    async def link(self, story_id: str, members: Any, **kwargs: Any) -> Any:
        if self._link and any(one.kind is StoryMemberKind.STORY for one in members):
            msg = "the store could not write the link"
            raise StoryStoreError(msg)
        return await self.inner.link(story_id, members, **kwargs)


@pytest.mark.parametrize(
    "stories",
    [
        pytest.param(_FailsAfterCreate(note_at=1), id="the-first-note"),
        pytest.param(_FailsAfterCreate(note_at=2), id="between-the-notes"),
        pytest.param(_FailsAfterCreate(link=True), id="placing-it-inside"),
    ],
)
async def test_a_start_that_made_its_story_is_never_reported_not_done(
    stories: _FailsAfterCreate,
) -> None:
    """ADR-0306 §5:6, §5:11: its record stays unfinished, so a repeat is already done.

    Reported not done, the backstop would let an identical start make a second story;
    reported done, it would claim what was not all written.
    """
    memory = FakeMemoryStore(now=_now)
    await memory.add(_episode(_EPISODE))
    await memory.add(_episode("activation:act-0"))
    summer = await _story(stories.inner)
    plans = FakePlanStore(now=_now)
    acting = _acting(plans, StoryCalls(stories=cast("StoryStore", stories), memory=memory))
    arguments: dict[str, FrozenJson] = {
        NOTES_ARGUMENT: ["A camping trip.", "Waiting on the reply."],
        INSIDE_ARGUMENT: summer,
    }

    with pytest.raises(StartUnfinishedError):
        await acting.act(
            AuthorizedRound(
                _ACTIVATION,
                "round:1",
                (AuthorizedCall(_call(START_STORY, arguments, decision="d1")),),
            ),
            held=HeldResults(),
        )
    (claimed,) = await plans.activation_effects([_ACTIVATION])
    assert claimed.outcome is None
    repeated = await acting.act(
        AuthorizedRound(
            _ACTIVATION, "round:2", (AuthorizedCall(_call(START_STORY, arguments, decision="d2")),)
        ),
        held=HeldResults(),
    )

    assert [one.outcome for one in repeated.calls] == [ActedOutcome.NOT_DONE]
    assert repeated.calls[0].reason is not None
    assert repeated.calls[0].reason.startswith("already done")
    own = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    assert len(await stories.inner.stories_of(own)) == 1


# --- note ----------------------------------------------------------------------------------


@pytest.mark.parametrize("outside", [False, True])
async def test_a_note_is_planning_s_written_during_this_activation_and_marked_by_the_hub(
    *, outside: bool
) -> None:
    """ADR-0303 §3:1, §9:3: the mark is the hub's record of what was read, never planning's."""
    stories, memory = await _stores()
    trip = await _story(stories)
    plans = FakePlanStore(now=_now)
    acting = _acting(plans, StoryCalls(stories=stories, memory=memory))
    call = _call(
        NOTE_STORY,
        {STORY_ARGUMENT: trip, NOTE_ARGUMENT: "Next: check the dog policy."}
        | {OUTSIDE_CONTENT_ARGUMENT: outside},
    )

    acted = await acting.act(
        AuthorizedRound(_ACTIVATION, "round:1", (AuthorizedCall(call),)), held=HeldResults()
    )

    assert [one.outcome for one in acted.calls] == [ActedOutcome.DONE]
    (note,) = await _notes(stories, trip)
    assert note.text == "Next: check the dog policy."
    assert note.author is StoryNoteAuthor.PLANNING
    assert note.written_during == _ACTIVATION
    assert note.outside is outside
    # Safe to repeat, so no effect record was claimed for it (ADR-0306 §5:3).
    assert await plans.activation_effects([_ACTIVATION]) == ()


async def test_a_note_on_a_merged_story_is_written_where_it_went() -> None:
    """ADR-0289 §3: a merged story is followed, never written."""
    stories, memory = await _stores()
    trip = await _story(stories)
    larger = await _story(stories, StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION))
    await stories.merge(trip, larger, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(NOTE_STORY, {STORY_ARGUMENT: trip, NOTE_ARGUMENT: "noted"}))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert [one.text for one in await _notes(stories, larger)] == ["noted"]


async def test_a_note_on_a_story_not_there_is_not_done() -> None:
    stories, memory = await _stores()
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(NOTE_STORY, {STORY_ARGUMENT: "story:gone", NOTE_ARGUMENT: "noted"})
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INVALID_REQUEST


#: Longer than the 32 merges a named story was once followed through (#2880).
_LONG_CHAIN: Final = 40


async def test_a_note_follows_a_chain_of_merges_however_long_to_the_story_standing() -> None:
    """ADR-0289 §3: the store bounds no chain, so neither does following one."""
    stories, memory = await _stores()
    chain = [await _story(stories) for _ in range(_LONG_CHAIN + 1)]
    for absorbed, into in pairwise(chain):
        await stories.merge(absorbed, into, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(NOTE_STORY, {STORY_ARGUMENT: chain[0], NOTE_ARGUMENT: "noted"}))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert [one.text for one in await _notes(stories, chain[-1])] == ["noted"]


class _MergedInALoop:
    """A story store whose two stories each name the other as merged into: a contradiction.

    The store never makes one (ADR-0289 §3), so the canonical fake cannot hold it and is
    wrapped. Its header reads are counted, and fail the test well before a loop followed
    for ever would.
    """

    _LOOP: Final = {"story:a": "story:b", "story:b": "story:a"}

    def __init__(self) -> None:
        self.inner = FakeStoryStore(now=_now)
        self.headers_read = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def header(self, story_id: str) -> StoryHeader | None:
        self.headers_read += 1
        assert self.headers_read <= _LONG_CHAIN, "a loop of merges was followed for ever"
        onward = self._LOOP.get(story_id)
        if onward is None:
            return await self.inner.header(story_id)
        return StoryHeader(story_id=story_id, created_at=_AT, merged_into=onward)


async def test_a_loop_of_merges_is_the_store_s_failure_and_writes_nothing() -> None:
    """#2880: a story met twice is not followed again; the call fails as the store failing."""
    stories = _MergedInALoop()
    memory = FakeMemoryStore(now=_now)
    calls = StoryCalls(stories=cast("StoryStore", stories), memory=memory)

    result = await calls.run(_call(NOTE_STORY, {STORY_ARGUMENT: "story:a", NOTE_ARGUMENT: "noted"}))
    reason = await calls.refusal(_carrying("move_story", "story:a", ["1"]), owner_records=True)

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INTERNAL
    assert result.failure.message == "the story store could not be written"
    # The hub's check fails closed on it, as on any store it cannot read (ADR-0307 §5:4).
    assert reason == "the stories could not be read, so the notes named could not be checked"
    assert await stories.inner.notes("story:a") is None


# --- link and unlink -----------------------------------------------------------------------


async def test_link_and_unlink_this_activation_another_and_a_story() -> None:
    """ADR-0300 §10:3, ADR-0303 §9:1: each member kind, linked then unlinked."""
    stories, memory = await _stores()
    trip = await _story(stories)
    inner = await _story(stories)
    calls = StoryCalls(stories=stories, memory=memory)
    this = StoryMember(kind=StoryMemberKind.ACTIVATION, id=_ACTIVATION)
    story = StoryMember(kind=StoryMemberKind.STORY, id=inner)

    for arguments in ({}, {MEMBER_STORY_ARGUMENT: inner}):
        linked = await calls.run(_call(LINK_STORY, {STORY_ARGUMENT: trip, **arguments}))
        assert linked.outcome is ToolOutcome.SUCCEEDED
    assert await _members(stories, trip) == [
        StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-0"),
        this,
        story,
    ]

    for arguments in ({MEMBER_EPISODE_ARGUMENT: "activation:act-0"}, {}):
        unlinked = await calls.run(_call(UNLINK_STORY, {STORY_ARGUMENT: trip, **arguments}))
        assert unlinked.outcome is ToolOutcome.SUCCEEDED
    assert await _members(stories, trip) == [story]
    # Unlinking a member the story no longer holds is passed over (ADR-0303 §9's table).
    again = await calls.run(_call(UNLINK_STORY, {STORY_ARGUMENT: trip}))
    assert again.outcome is ToolOutcome.SUCCEEDED
    log = await stories.log(trip)
    assert log is not None
    changes = [(line.change, line.actor) for line in log.lines if line.actor is StoryActor.PLANNING]
    assert changes == [
        (StoryChange.ADDED, StoryActor.PLANNING),
        (StoryChange.ADDED, StoryActor.PLANNING),
        (StoryChange.REMOVED, StoryActor.PLANNING),
        (StoryChange.REMOVED, StoryActor.PLANNING),
    ]


@pytest.mark.parametrize(
    ("arguments", "kind"),
    [
        pytest.param(
            {MEMBER_STORY_ARGUMENT: "story:x", MEMBER_EPISODE_ARGUMENT: "activation:act-0"},
            ToolFailureKind.INVALID_REQUEST,
            id="two-members",
        ),
        pytest.param(
            {MEMBER_EPISODE_ARGUMENT: "memory:not-an-activation"},
            ToolFailureKind.INVALID_REQUEST,
            id="no-activations-episode",
        ),
        pytest.param(
            {MEMBER_EPISODE_ARGUMENT: "activation:never-ran"},
            ToolFailureKind.INVALID_REQUEST,
            id="an-activation-with-no-episode",
        ),
    ],
)
async def test_a_link_naming_what_cannot_be_linked_links_nothing(
    arguments: dict[str, FrozenJson], kind: ToolFailureKind
) -> None:
    stories, memory = await _stores()
    trip = await _story(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(LINK_STORY, {STORY_ARGUMENT: trip, **arguments}))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is kind
    assert await _members(stories, trip) == [
        StoryMember(kind=StoryMemberKind.ACTIVATION, id="act-0")
    ]


async def test_a_link_that_would_make_a_loop_is_refused_by_the_store() -> None:
    stories, memory = await _stores()
    trip = await _story(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(LINK_STORY, {STORY_ARGUMENT: trip, MEMBER_STORY_ARGUMENT: trip}))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED


# --- tidy-up -------------------------------------------------------------------------------


async def test_a_tidy_up_writes_the_story_s_version_log() -> None:
    """ADR-0307 §7:1, ADR-0300 §10:4: its outcome is the version it wrote."""
    stories, memory = await _stores()
    trip = await _story(stories)
    await stories.append_note(trip, "A camping trip.", author=StoryNoteAuthor.OWNER)
    tidy_up = StoryTidyUp(
        model=structured(FakeModelProvider(reply=json.dumps({"lines": ["A camping trip."]}))),
        stories=stories,
        memory=memory,
        excerpt_chars=200,
        other_stories=0,
        decisions=0,
        budget=timedelta(seconds=5),
        threshold=0.0,
        prompt=default_prompt(STORY_TIDY_UP_PROMPT),
    )
    calls = StoryCalls(stories=stories, memory=memory, tidy_up=tidy_up)

    result = await calls.run(_call(TIDY_STORY, {STORY_ARGUMENT: trip}))

    assert result.outcome is ToolOutcome.SUCCEEDED
    versions = await stories.summary_versions(trip)
    assert versions is not None
    (version,) = versions.versions
    assert len(version.took_in_notes) == 1
    state = await stories.current_summary(trip)
    assert state is not None
    assert state.summary is not None
    assert [line.text for line in state.summary.lines] == ["A camping trip."]


async def test_a_tidy_up_with_none_wired_or_a_refused_reply_is_not_done() -> None:
    stories, memory = await _stores()
    trip = await _story(stories)
    await stories.append_note(trip, "A camping trip.", author=StoryNoteAuthor.OWNER)
    unwired = StoryCalls(stories=stories, memory=memory)
    refusing = StoryCalls(
        stories=stories,
        memory=memory,
        tidy_up=StoryTidyUp(
            model=structured(FakeModelProvider(reply="not json")),
            stories=stories,
            memory=memory,
            excerpt_chars=200,
            other_stories=0,
            decisions=0,
            budget=timedelta(seconds=5),
            threshold=0.0,
            prompt=default_prompt(STORY_TIDY_UP_PROMPT),
        ),
    )

    for calls in (unwired, refusing):
        result = await calls.run(_call(TIDY_STORY, {STORY_ARGUMENT: trip}))
        assert result.outcome is ToolOutcome.FAILED
    versions = await stories.summary_versions(trip)
    assert versions is not None
    assert versions.versions == ()


async def test_a_call_that_is_no_story_call_is_not_done() -> None:
    stories, memory = await _stores()
    calls = StoryCalls(stories=stories, memory=memory)
    other = TIDY_STORY.model_copy(update={"id": "other", "capability": "other"})

    result = await calls.run(_call(other, {STORY_ARGUMENT: "story:x"}))

    assert result.outcome is ToolOutcome.FAILED


# --- planning's own check ------------------------------------------------------------------


class _Recorder:
    async def record(
        self, planning_round: PlanningRound, labels: tuple[PlanningLabel, ...]
    ) -> None:
        del planning_round, labels


async def test_a_story_label_planning_was_never_shown_refuses_the_call_whole() -> None:
    """ADR-0307 §5:3: refused before authorizing, with its reason; a shown one maps to its id."""
    shown = PlanningLabel(label="S1", kind=LabelKind.STORY, id="story:trip")
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _proposed("c1", "note_story", story="S1", note="noted"),
                _proposed("c2", "note_story", story="S9", note="noted"),
                _proposed("c3", "link_story", story="S1", member_episode="S1"),
            )
        )
    )
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
    )

    planned = await stage.plan(
        PlanningInputs(
            activation_id=_ACTIVATION,
            place=PlaceWindow(takes_message=True),
            trigger_origin=InputOrigin.USER,
            labels=(shown,),
            capabilities=STORY_CALLS,
            label_arguments=STORY_LABEL_ARGUMENTS,
        )
    )

    (passed,) = planned.calls
    assert passed.call.arguments[STORY_ARGUMENT] == "story:trip"
    refused = {one.call.call_id: one for one in planned.refused}
    assert set(refused) == {"c2", "c3"}
    assert all(isinstance(one, RefusedCall) for one in refused.values())
    assert refused["c2"].reason == "'S9' names nothing you were shown"
    assert refused["c3"].reason == "'S1' names a story, not an episode"


def _proposed(call_id: str, name: str, **arguments: Any) -> ProposedCall:
    return ProposedCall(call_id=call_id, name=name, arguments=arguments)


async def test_an_earlier_tidy_up_is_shown_as_started_and_nothing_more() -> None:
    """ADR-0307 §7:1: its outcome is the story's version log's, never the episode's."""
    earlier = PlanningRound(
        id="round:0",
        recorded_at=_AT,
        calls=(_proposed("c0", "tidy_story", story="story:trip"),),
    )
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="ok"))
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
    )

    await stage.plan(
        PlanningInputs(
            activation_id=_ACTIVATION,
            place=PlaceWindow(takes_message=True),
            rounds=(earlier,),
            capabilities=STORY_CALLS,
            label_arguments=STORY_LABEL_ARGUMENTS,
        )
    )

    (shown,) = json.loads(completer.last_call.messages[1].content)["rounds"][0]["calls"]
    assert shown["outcome"].startswith("started: it runs on its own")


# --- move, merge, split and group ----------------------------------------------------------


def _activation_member(activation_id: str) -> StoryMember:
    return StoryMember(kind=StoryMemberKind.ACTIVATION, id=activation_id)


async def _noted(stories: FakeStoryStore, story_id: str, text: str) -> int:
    written = await stories.append_note(
        story_id, text, author=StoryNoteAuthor.PLANNING, written_during="act-0", outside=False
    )
    assert written.note is not None
    return int(written.note.note_id)


async def _two_stories(stories: FakeStoryStore) -> tuple[str, str]:
    trip = await _story(stories, _activation_member("act-0"), _activation_member(_ACTIVATION))
    other = await _story(stories, _activation_member("act-2"))
    return trip, other


@pytest.mark.parametrize("tool", [MOVE_STORY, MERGE_STORY, SPLIT_STORY, GROUP_STORY])
async def test_each_reorganising_call_runs_through_the_own_records_seam(
    tool: ToolDefinition,
) -> None:
    """ADR-0306 §3:3: acting reaches the runner, never the invoker, and it is done."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    note = await _noted(stories, trip, "Goes.")
    by_call: dict[str, dict[str, FrozenJson]] = {
        str(MOVE_STORY.capability): {
            STORY_ARGUMENT: trip,
            TO_ARGUMENT: other,
            EPISODES_ARGUMENT: ["activation:act-0"],
            NOTES_ARGUMENT: [str(note)],
        },
        str(MERGE_STORY.capability): {STORY_ARGUMENT: trip, INTO_ARGUMENT: other},
        str(SPLIT_STORY.capability): {
            STORY_ARGUMENT: trip,
            EPISODES_ARGUMENT: ["activation:act-0"],
            NOTES_ARGUMENT: [str(note)],
        },
        str(GROUP_STORY.capability): {STORIES_ARGUMENT: [trip, other]},
    }
    arguments = by_call[str(tool.capability)]
    plans = FakePlanStore(now=_now)
    acting = _acting(plans, StoryCalls(stories=stories, memory=memory))

    acted = await acting.act(
        AuthorizedRound(_ACTIVATION, "round:1", (AuthorizedCall(_call(tool, arguments)),)),
        held=HeldResults(),
    )

    assert [one.outcome for one in acted.calls] == [ActedOutcome.DONE]
    page = await stories.stories()
    written = set()
    for header in page.stories:
        log = await stories.log(str(header.story_id))
        assert log is not None
        written |= {(line.actor, line.trigger) for line in log.lines}
    assert (StoryActor.PLANNING, _ACTIVATION) in written


async def test_a_move_carries_the_activations_and_the_notes_it_names() -> None:
    """ADR-0303 §6:1-§6:2: exactly the notes named, by planning, triggered here."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    goes = await _noted(stories, trip, "Goes.")
    await _noted(stories, trip, "Stays.")
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(
            MOVE_STORY,
            {
                STORY_ARGUMENT: trip,
                TO_ARGUMENT: other,
                EPISODES_ARGUMENT: ["activation:act-0"],
                NOTES_ARGUMENT: [str(goes)],
            },
        )
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert await _members(stories, trip) == [_activation_member(_ACTIVATION)]
    assert await _members(stories, other) == [
        _activation_member("act-2"),
        _activation_member("act-0"),
    ]
    assert [one.text for one in await _notes(stories, other)] == ["Goes."]
    assert [one.text for one in await _notes(stories, trip)] == ["Stays."]


async def test_a_note_move_alone_carries_only_the_note() -> None:
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    goes = await _noted(stories, trip, "Goes.")
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(MOVE_STORY, {STORY_ARGUMENT: trip, TO_ARGUMENT: other, NOTES_ARGUMENT: [str(goes)]})
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert [one.text for one in await _notes(stories, other)] == ["Goes."]
    assert len(await _members(stories, trip)) == 2


async def test_a_move_naming_a_note_the_story_no_longer_holds_is_refused_whole_by_the_store() -> (
    None
):
    """ADR-0307 §5:4: a note moved away after the hub's check still refuses the call."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    third = await _story(stories, _activation_member("act-3"))
    goes = await _noted(stories, trip, "Goes.")
    gone = await _noted(stories, trip, "Moved away meanwhile.")
    await stories.move(trip, third, actor=StoryActor.MATTERS_PASS, notes=[gone])
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(
            MOVE_STORY,
            {
                STORY_ARGUMENT: trip,
                TO_ARGUMENT: other,
                EPISODES_ARGUMENT: ["activation:act-0"],
                NOTES_ARGUMENT: [str(goes), str(gone)],
            },
        )
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.REFUSED
    assert result.failure.message == "the story store refused it: note_not_held"
    assert len(await _members(stories, trip)) == 2
    assert [one.text for one in await _notes(stories, trip)] == ["Goes."]


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({}, id="nothing-moves"),
        pytest.param({NOTES_ARGUMENT: ["N1"]}, id="a-label-not-mapped"),
        pytest.param({EPISODES_ARGUMENT: ["memory:x"]}, id="no-activations-episode"),
    ],
)
async def test_a_move_naming_nothing_that_can_go_is_not_done(
    arguments: dict[str, FrozenJson],
) -> None:
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(MOVE_STORY, {STORY_ARGUMENT: trip, TO_ARGUMENT: other, **arguments})
    )

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert result.failure.kind is ToolFailureKind.INVALID_REQUEST
    assert len(await _members(stories, trip)) == 2


async def test_a_move_from_a_merged_story_is_made_from_where_it_went() -> None:
    """ADR-0289 §3: the story moved from is followed; a move into itself is not done."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    larger = await _story(stories, _activation_member("act-4"))
    await stories.merge(trip, larger, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    moved = await calls.run(
        _call(
            MOVE_STORY,
            {STORY_ARGUMENT: trip, TO_ARGUMENT: other, EPISODES_ARGUMENT: ["activation:act-0"]},
        )
    )
    into_itself = await calls.run(
        _call(
            MOVE_STORY,
            {STORY_ARGUMENT: trip, TO_ARGUMENT: larger, EPISODES_ARGUMENT: ["activation:act-4"]},
        )
    )

    assert moved.outcome is ToolOutcome.SUCCEEDED
    assert _activation_member("act-0") in await _members(stories, other)
    assert into_itself.outcome is ToolOutcome.FAILED


async def test_a_merge_carries_everything_and_a_repeat_is_refused_changing_nothing() -> None:
    """ADR-0303 §9's table: a repeat names a merged story, never followed, and is refused."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    await _noted(stories, trip, "Comes along.")
    calls = StoryCalls(stories=stories, memory=memory)
    merge = _call(MERGE_STORY, {STORY_ARGUMENT: trip, INTO_ARGUMENT: other})

    first = await calls.run(merge)
    before = await stories.log(other)
    second = await calls.run(merge)

    assert first.outcome is ToolOutcome.SUCCEEDED
    assert [one.text for one in await _notes(stories, other)] == ["Comes along."]
    assert second.outcome is ToolOutcome.FAILED
    assert second.failure is not None
    assert second.failure.message == "the story store refused it: merged_story"
    assert await stories.log(other) == before


async def test_a_merge_into_a_merged_story_joins_where_it_went() -> None:
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    larger = await _story(stories, _activation_member("act-4"))
    await stories.merge(other, larger, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(MERGE_STORY, {STORY_ARGUMENT: trip, INTO_ARGUMENT: other}))

    assert result.outcome is ToolOutcome.SUCCEEDED
    header = await stories.header(trip)
    assert header is not None
    assert header.merged_into == larger


async def test_a_split_carries_activations_stories_and_the_notes_it_names() -> None:
    """ADR-0303 §6, §9:1: members by E or S, notes by N, into a new story."""
    stories, memory = await _stores()
    inner = await _story(stories, _activation_member("act-5"))
    trip = await _story(
        stories,
        _activation_member("act-0"),
        _activation_member(_ACTIVATION),
        StoryMember(kind=StoryMemberKind.STORY, id=inner),
    )
    goes = await _noted(stories, trip, "Goes.")
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(
            SPLIT_STORY,
            {
                STORY_ARGUMENT: trip,
                EPISODES_ARGUMENT: ["activation:act-0"],
                STORIES_ARGUMENT: [inner],
                NOTES_ARGUMENT: [str(goes)],
            },
        )
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert await _members(stories, trip) == [_activation_member(_ACTIVATION)]
    (split_off,) = [
        header
        for header in await stories.stories_of(_activation_member("act-0"))
        if header.story_id != trip
    ]
    assert await _members(stories, str(split_off.story_id)) == [
        _activation_member("act-0"),
        StoryMember(kind=StoryMemberKind.STORY, id=inner),
    ]
    assert [one.text for one in await _notes(stories, str(split_off.story_id))] == ["Goes."]


async def test_a_split_naming_no_member_or_a_non_member_is_not_done() -> None:
    """ADR-0303 §9's table: a repeat names members the story no longer holds."""
    stories, memory = await _stores()
    trip, _ = await _two_stories(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    nothing = await calls.run(_call(SPLIT_STORY, {STORY_ARGUMENT: trip, NOTES_ARGUMENT: ["1"]}))
    stranger = await calls.run(
        _call(SPLIT_STORY, {STORY_ARGUMENT: trip, EPISODES_ARGUMENT: ["activation:act-9"]})
    )

    assert nothing.outcome is ToolOutcome.FAILED
    assert stranger.outcome is ToolOutcome.FAILED
    assert stranger.failure is not None
    assert stranger.failure.message == "the story store refused it: not_a_member"
    assert len(await _members(stories, trip)) == 2


async def test_a_group_puts_the_stories_under_a_new_larger_one_with_its_first_notes() -> None:
    """ADR-0303 §9:1: the store's create, with story members; merged ones followed."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    absorbed = await _story(stories, _activation_member("act-6"))
    await stories.merge(absorbed, other, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(
        _call(
            GROUP_STORY,
            {
                STORIES_ARGUMENT: [trip, absorbed, other],
                NOTES_ARGUMENT: ["The summer."],
                OUTSIDE_CONTENT_ARGUMENT: True,
            },
        )
    )

    assert result.outcome is ToolOutcome.SUCCEEDED
    (larger,) = await stories.stories_of(StoryMember(kind=StoryMemberKind.STORY, id=trip))
    assert await _members(stories, str(larger.story_id)) == [
        StoryMember(kind=StoryMemberKind.STORY, id=trip),
        StoryMember(kind=StoryMemberKind.STORY, id=other),
    ]
    (note,) = await _notes(stories, str(larger.story_id))
    assert (note.text, note.author, note.written_during, note.outside) == (
        "The summer.",
        StoryNoteAuthor.PLANNING,
        _ACTIVATION,
        True,
    )


async def test_a_group_repeated_identically_is_refused_as_already_done() -> None:
    """ADR-0303 §9's table, ADR-0306 §5:9: not safe to repeat."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    plans = FakePlanStore(now=_now)
    acting = _acting(plans, StoryCalls(stories=stories, memory=memory))
    arguments: dict[str, FrozenJson] = {STORIES_ARGUMENT: [trip, other]}

    first = await acting.act(
        AuthorizedRound(
            _ACTIVATION, "round:1", (AuthorizedCall(_call(GROUP_STORY, arguments, decision="d1")),)
        ),
        held=HeldResults(),
    )
    second = await acting.act(
        AuthorizedRound(
            _ACTIVATION, "round:2", (AuthorizedCall(_call(GROUP_STORY, arguments, decision="d2")),)
        ),
        held=HeldResults(),
    )

    assert [one.outcome for one in first.calls] == [ActedOutcome.DONE]
    assert [one.outcome for one in second.calls] == [ActedOutcome.NOT_DONE]
    assert second.calls[0].reason is not None
    assert second.calls[0].reason.startswith("already done")
    assert len(await stories.stories_of(StoryMember(kind=StoryMemberKind.STORY, id=trip))) == 1


async def test_a_group_that_made_its_story_is_never_reported_not_done() -> None:
    """ADR-0306 §5:6, §5:11: as a start, its record stays unfinished."""
    stories = _FailsAfterCreate(note_at=1)
    memory = FakeMemoryStore(now=_now)
    trip = await _story(stories.inner)
    calls = StoryCalls(stories=cast("StoryStore", stories), memory=memory)

    with pytest.raises(StartUnfinishedError):
        await calls.run(
            _call(GROUP_STORY, {STORIES_ARGUMENT: [trip], NOTES_ARGUMENT: ["The summer."]})
        )
    assert (
        len(await stories.inner.stories_of(StoryMember(kind=StoryMemberKind.STORY, id=trip))) == 1
    )


async def test_a_group_naming_a_story_not_there_makes_nothing() -> None:
    stories, memory = await _stores()
    trip, _ = await _two_stories(stories)
    calls = StoryCalls(stories=stories, memory=memory)

    result = await calls.run(_call(GROUP_STORY, {STORIES_ARGUMENT: [trip, "story:gone"]}))

    assert result.outcome is ToolOutcome.FAILED
    assert await stories.stories_of(StoryMember(kind=StoryMemberKind.STORY, id=trip)) == ()


# --- the hub's check before authorizing ------------------------------------------------------


def _carrying(name: str, story: str, notes: list[str], **rest: FrozenJson) -> ProposedCall:
    return ProposedCall(
        call_id="c1", name=name, arguments={STORY_ARGUMENT: story, NOTES_ARGUMENT: notes, **rest}
    )


@pytest.mark.parametrize("name", ["move_story", "split_story"])
async def test_the_hub_refuses_a_move_or_a_split_naming_a_note_not_held(name: str) -> None:
    """ADR-0307 §5:3-§5:4: against the stories as they stand, naming the note by its label."""
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    held = await _noted(stories, trip, "Held.")
    elsewhere = await _noted(stories, other, "Elsewhere.")
    calls = StoryCalls(stories=stories, memory=memory)
    labels = {str(held): "N1", str(elsewhere): "N2"}

    refused = await calls.refusal(
        _carrying(name, trip, [str(held), str(elsewhere)]), owner_records=True, labels=labels
    )
    passed = await calls.refusal(
        _carrying(name, trip, [str(held)]), owner_records=True, labels=labels
    )

    assert refused == "N2 is not on the story it would leave, so nothing was moved"
    assert passed is None


class _PagesCounted:
    """A story store whose note pages are counted; the canonical fake is final, so wrapped."""

    def __init__(self) -> None:
        self.inner = FakeStoryStore(now=_now)
        self.pages_read = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def notes(self, story_id: str, **kwargs: Any) -> Any:
        self.pages_read += 1
        return await self.inner.notes(story_id, **kwargs)


async def _past_one_page() -> tuple[_PagesCounted, StoryCalls, str, list[int]]:
    """A story holding one note more than a page of the hub's check reads."""
    stories = _PagesCounted()
    memory = FakeMemoryStore(now=_now)
    trip = await _story(stories.inner)
    held = [await _noted(stories.inner, trip, f"Note {n}.") for n in range(MAX_STORY_PAGE + 1)]
    return stories, StoryCalls(stories=cast("StoryStore", stories), memory=memory), trip, held


@pytest.mark.parametrize("name", ["move_story", "split_story"])
async def test_the_hub_accepts_a_note_held_on_the_second_page(name: str) -> None:
    """#2882: the check reads the story's notes page by page, past the first."""
    stories, calls, trip, held = await _past_one_page()

    reason = await calls.refusal(_carrying(name, trip, [str(held[-1])]), owner_records=True)

    assert reason is None
    assert stories.pages_read == 2  # one page more than a page holds


@pytest.mark.parametrize("name", ["move_story", "split_story"])
async def test_the_hub_refuses_held_and_missing_notes_after_reading_every_page(name: str) -> None:
    """#2882: the held note on the second page is found; the missing one is named."""
    stories, calls, trip, held = await _past_one_page()
    missing = held[-1] + 1
    labels = {str(held[-1]): "N101", str(held[0]): "N1", str(missing): "N102"}

    reason = await calls.refusal(
        _carrying(name, trip, [str(held[-1]), str(held[0]), str(missing)]),
        owner_records=True,
        labels=labels,
    )

    assert reason == "N102 is not on the story it would leave, so nothing was moved"
    assert stories.pages_read == 2  # one page more than a page holds


async def test_the_hub_checks_the_story_a_merged_one_went_into() -> None:
    stories, memory = await _stores()
    trip, other = await _two_stories(stories)
    note = await _noted(stories, trip, "Held.")
    await stories.merge(trip, other, actor=StoryActor.OWNER)
    calls = StoryCalls(stories=stories, memory=memory)

    assert await calls.refusal(_carrying("move_story", trip, [str(note)]), owner_records=True) is (
        None
    )


async def test_on_an_owner_only_pass_a_move_or_a_split_carries_members_only() -> None:
    """ADR-0307 §6:5: one naming notes is refused with the reason; members alone pass."""
    stories, memory = await _stores()
    trip, _ = await _two_stories(stories)
    note = await _noted(stories, trip, "Held.")
    calls = StoryCalls(stories=stories, memory=memory)

    with_notes = await calls.refusal(
        _carrying("split_story", trip, [str(note)]), owner_records=False
    )
    members_only = await calls.refusal(
        _carrying("split_story", trip, [], episodes=["activation:act-0"]), owner_records=False
    )

    assert with_notes is not None
    assert with_notes.startswith("on this pass a move or a split carries members only")
    assert members_only is None


class _Unreadable:
    """A story store whose notes cannot be read; the canonical fake is final, so wrapped."""

    def __init__(self) -> None:
        self.inner = FakeStoryStore(now=_now)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def notes(self, story_id: str, **kwargs: Any) -> Any:
        del story_id, kwargs
        msg = "the store could not be read"
        raise StoryStoreError(msg)


async def test_the_hub_check_fails_closed_where_the_stories_cannot_be_read() -> None:
    stories = _Unreadable()
    memory = FakeMemoryStore(now=_now)
    trip = await _story(stories.inner)
    calls = StoryCalls(stories=cast("StoryStore", stories), memory=memory)

    reason = await calls.refusal(_carrying("move_story", trip, ["1"]), owner_records=True)

    assert reason == "the stories could not be read, so the notes named could not be checked"


async def test_the_hub_check_passes_every_other_call() -> None:
    stories, memory = await _stores()
    calls = StoryCalls(stories=stories, memory=memory)

    for call in (
        ProposedCall(call_id="c1", name="note_story", arguments={STORY_ARGUMENT: "story:x"}),
        _carrying("merge_stories", "story:x", ["1"]),
        _carrying("move_story", "story:x", []),
    ):
        assert await calls.refusal(call, owner_records=False) is None


async def test_the_hub_check_refuses_a_story_not_there_with_the_reason() -> None:
    stories, memory = await _stores()
    calls = StoryCalls(stories=stories, memory=memory)

    reason = await calls.refusal(_carrying("move_story", "story:gone", ["1"]), owner_records=True)

    assert reason == "the story named is not there"


async def test_planning_refuses_a_note_label_it_was_never_shown() -> None:
    """ADR-0307 §5:3: an N label never shown refuses the move whole; one shown maps to its id."""
    shown = (
        PlanningLabel(label="S1", kind=LabelKind.STORY, id="story:trip"),
        PlanningLabel(label="S2", kind=LabelKind.STORY, id="story:other"),
        PlanningLabel(label="N1", kind=LabelKind.NOTE, id="7"),
    )
    completer = FakeToolCallingCompleter.scripted(
        RoundResponse(
            calls=(
                _proposed("c1", "move_story", story="S1", to="S2", notes=["N1"]),
                _proposed("c2", "move_story", story="S1", to="S2", notes=["N1", "N4"]),
            )
        )
    )
    stage = PlanningStage(
        prompt=default_prompt(PLANNING_PROMPT),
        completer=completer,
        recorder=_Recorder(),
        excerpt_chars=200,
        now=_now,
    )

    planned = await stage.plan(
        PlanningInputs(
            activation_id=_ACTIVATION,
            place=PlaceWindow(takes_message=True),
            trigger_origin=InputOrigin.USER,
            labels=shown,
            capabilities=STORY_CALLS,
            label_arguments=STORY_LABEL_ARGUMENTS,
        )
    )

    (passed,) = planned.calls
    arguments = passed.call.arguments
    assert (arguments[STORY_ARGUMENT], arguments[TO_ARGUMENT]) == ("story:trip", "story:other")
    notes = arguments[NOTES_ARGUMENT]
    assert isinstance(notes, tuple | list)
    assert list(notes) == ["7"]
    (refused,) = planned.refused
    assert refused.reason == "'N4' names nothing you were shown"
