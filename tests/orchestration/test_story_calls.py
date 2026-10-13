"""Planning's story calls that write (ADR-0300 §10, ADR-0303 §9, ADR-0306 §3, ADR-0307 §5).

Each call's declaration, that it runs through acting's own-records seam and never the
invoker, the duplicate backstop refusing a repeated start, a note's writer, what it was
written during and its mark, link and unlink, the tidy-up's run, and planning refusing a
label it was never shown before anything is authorized.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, cast

import pytest

from ai_assistant.core.errors import StoryStoreError
from ai_assistant.core.types import (
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
    PlaceWindow,
    PlanningInputs,
    PlanningStage,
    RefusedCall,
    offered_tools,
)
from ai_assistant.orchestration.remembering import EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT
from ai_assistant.orchestration.story_calls import (
    INSIDE_ARGUMENT,
    LINK_STORY,
    MEMBER_EPISODE_ARGUMENT,
    MEMBER_STORY_ARGUMENT,
    NOTE_ARGUMENT,
    NOTE_STORY,
    NOTES_ARGUMENT,
    START_STORY,
    STORY_ARGUMENT,
    STORY_CALL_CAPABILITIES,
    STORY_CALLS,
    STORY_LABEL_ARGUMENTS,
    TIDY_STORY,
    UNLINK_STORY,
    StartUnfinishedError,
    StoryCalls,
)
from ai_assistant.orchestration.story_tidy_up import StoryTidyUp
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakePlanStore,
    FakeStoryStore,
    FakeToolCallingCompleter,
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
    # Starting is not safe to repeat; every other story call is (ADR-0300 §10's table,
    # ADR-0303 §9's).
    assert tool.safe_to_repeat is (tool is not START_STORY)


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
        assert (DELIBERATE_REPEAT in properties) is (name == str(START_STORY.capability))
    assert START_STORY.system_supplied == (EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT)
    assert NOTE_STORY.system_supplied == (EPISODE_ARGUMENT, OUTSIDE_CONTENT_ARGUMENT)
    assert LINK_STORY.system_supplied == (EPISODE_ARGUMENT,)
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
        model=FakeModelProvider(reply=json.dumps({"lines": ["A camping trip."]})),
        stories=stories,
        memory=memory,
        excerpt_chars=200,
        other_stories=0,
        decisions=0,
        budget=timedelta(seconds=5),
        threshold=0.0,
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
            model=FakeModelProvider(reply="not json"),
            stories=stories,
            memory=memory,
            excerpt_chars=200,
            other_stories=0,
            decisions=0,
            budget=timedelta(seconds=5),
            threshold=0.0,
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
    stage = PlanningStage(completer=completer, recorder=_Recorder(), excerpt_chars=200, now=_now)

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
    # The story calls' paragraph is in the instruction where they are offered.
    assert "Stories are yours to keep" in completer.last_call.messages[0].content


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
    stage = PlanningStage(completer=completer, recorder=_Recorder(), excerpt_chars=200, now=_now)

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
