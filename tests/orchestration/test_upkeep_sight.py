"""The upkeep runs and a tidy-up a work asks for read through a sight (milestone 22's B9b).

ADR-0383 §6:8, §7:7 and ADR-0384 §3, §5, §6, §7: each run of the scheduled tidy-up, the
matters pass and the notification reconsideration reads and writes through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the run's sight,
made once for the run from the domain it tends
(:func:`~ai_assistant.orchestration.upkeep.upkeep_run`), its finding of what is due
included; and a tidy-up a work asks for reads by that work's sight with the story's
domain's bound (:meth:`~ai_assistant.core.types.Sight.of_tidy_up`).

With stores built to withhold, a run for the owner's domain reads, shows its model and
writes as the counting build does where every record is the owner's; with records of the
shared things beside them, the owner's run reads none of them and the shared things' run
none of the owner's. The four reads lane B5e left are pinned: the tidy-up's look-alike
stories, the matters pass's episodes, the stories a recorded decision concerns, and the
finding of what is due. In the counting build every run answers as today, each read
writing its count with the reader ``run`` (``work`` for a work's tidy-up), counting what
a withholding store would have kept back.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from datetime import datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import AT, WORK_ACTIVATION, activation, address, episode, work_of
from structlog.testing import capture_logs
from structured_support import structured
from test_engine import AT as ENGINE_AT
from test_engine import Harness
from test_notification_person_zone import _TOKYO, _engine, _Factory, _people
from test_notification_person_zone import _candidate as _notification

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActionRequest,
    ClassReach,
    InputSender,
    MemoryWrite,
    MemoryWriteMode,
    NotificationPreferences,
    NotificationReach,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordHome,
    Sight,
    SightMode,
    SightReader,
    StoryActor,
    StoryFlag,
    StoryFlagKind,
    StoryFlagName,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    Sureness,
    ToolCall,
    ToolFailureKind,
    ToolOutcome,
)
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.matters_pass import MATTERS_PASS_PROMPT, MattersPass
from ai_assistant.orchestration.remembering import EPISODE_ARGUMENT
from ai_assistant.orchestration.story_calls import (
    STORY_ARGUMENT,
    TIDY_STORY,
    StoryCalls,
    tidy_up_asked_by,
)
from ai_assistant.orchestration.story_tidy_up import (
    STORY_TIDY_UP_PROMPT,
    ScheduledTidyUp,
    StoryTidyUp,
)
from ai_assistant.orchestration.upkeep import UPKEEP_DOMAINS, upkeep_run
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeStoryStore,
    default_prompt,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    from ai_assistant.core.types import EpisodicMemory, HeldNotification, Message, ToolResult

_OWNERS: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()
_BUDGET: Final = timedelta(seconds=10)
_QUIET: Final = timedelta(hours=24)
_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda mode: mode.value)
_UNIDENTIFIED: Final = InputSender(person=None, level=Sureness.NONE)
_OWNER: Final = InputSender(person=OWNER_PERSON_ID, level=Sureness.NORMAL)
#: Above every score the fake memory store gives a match, so the look-alike search keeps
#: nothing and only a story sharing an episode is shown for the flag.
_NO_MATCH: Final = 1.5


def _of(home: RecordHome, record: EpisodicMemory) -> EpisodicMemory:
    """``record`` landed in ``home``."""
    return record.model_copy(update={"home": home})


class _Model:
    """Answers each completion with ``reply`` and keeps what each was shown, by its key."""

    def __init__(self, reply: str, *, key: str) -> None:
        self.shown: dict[str, dict[str, Any]] = {}
        self.messages: list[Sequence[Message]] = []
        self._key = key
        self.provider = FakeModelProvider(self._answer)
        self._reply = reply

    def _answer(self, messages: Sequence[Message]) -> str:
        self.messages.append(messages)
        shown: dict[str, Any] = json.loads(messages[-1].content)
        self.shown[_keyed(shown, self._key)] = shown
        return self._reply


def _keyed(shown: dict[str, Any], key: str) -> str:
    if key == "note":
        return str(shown["notes"][0]["text"])
    return str(shown["stories"][0]["its_summary"]["lines"][0])


class _World:
    """The story and memory stores built to ``mode``, and the holder over them."""

    def __init__(self, mode: SightMode) -> None:
        ids = count(1)
        #: The story store's clock, which a case moves to link later.
        self.at = AT
        self.stories = FakeStoryStore(
            now=lambda: self.at, new_id=lambda: f"{next(ids)}", sight_mode=mode
        )
        self.memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
        self.stores = BoundStores(memory=self.memory, stories=self.stories)

    async def hold(self, *records: EpisodicMemory) -> None:
        await self.memory.write_atomic(
            [MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT) for one in records]
        )

    async def story(self, home: RecordHome, *activations: str, note: str | None = None) -> str:
        made = await self.stories.create(
            [activation(one) for one in activations], home=home, actor=StoryActor.UNDERSTANDING
        )
        assert made.story_id is not None
        if note is not None:
            await self.stories.append_note(made.story_id, note, author=StoryNoteAuthor.OWNER)
        return made.story_id

    async def summarise(self, story_id: str, line: str, *flags: StoryFlag) -> StoryFlagName:
        """Write a summary of ``line`` raising ``flags``; the first flag's name."""
        state = await self.stories.current_summary(story_id)
        assert state is not None
        draft = StorySummaryDraft(lines=(StorySummaryLine(text=line),), flags=flags, outside=False)
        written = await self.stories.write_summary(story_id, draft, as_of=state.as_of)
        assert written.version is not None
        return StoryFlagName(story=story_id, version=written.version.version, flag=flags[0])

    def tidy_up(self, model: _Model, *, decisions: int = 5) -> StoryTidyUp:
        return StoryTidyUp(
            model=structured(model.provider),
            stores=self.stores,
            excerpt_chars=2000,
            other_stories=5,
            decisions=decisions,
            budget=_BUDGET,
            threshold=_NO_MATCH,
            prompt=default_prompt(STORY_TIDY_UP_PROMPT),
        )

    def scheduled(
        self, model: _Model, *, threshold: int = 1, now: datetime = AT
    ) -> ScheduledTidyUp:
        return ScheduledTidyUp(
            tidy_up=self.tidy_up(model),
            stores=self.stores,
            threshold=threshold,
            quiet=_QUIET,
            per_run=10,
            budget=_BUDGET,
            now=lambda: now,
        )

    def matters(self, model: _Model) -> MattersPass:
        return MattersPass(
            model=structured(model.provider),
            stores=self.stores,
            excerpt_chars=1000,
            flags_per_run=10,
            decisions=5,
            episodes=6,
            notes=5,
            budget=_BUDGET,
            prompt=default_prompt(MATTERS_PASS_PROMPT),
        )


def _counted(logs: Sequence[MutableMapping[str, Any]]) -> list[MutableMapping[str, Any]]:
    return [one for one in logs if one["event"] == "sight_counted"]


_TIDIED: Final = json.dumps({"lines": ["Tidied."], "flags": []})
_LEAVE: Final = json.dumps({"decision": "leave"})


# --- a run's sight --------------------------------------------------------------------


@pytest.mark.parametrize("domain", UPKEEP_DOMAINS, ids=["owners", "shared"])
def test_a_run_s_sight_is_made_from_the_domain_it_tends_and_sees_that_domain_alone(
    domain: RecordHome,
) -> None:
    """§6:8: a one-domain bound and the domain's person's, the owner for the shared things."""
    run = upkeep_run(domain)

    assert run.tends == domain
    assert run.sight == Sight.of_run(domain)
    assert run.sight.reader is SightReader.RUN
    assert run.sight.homes_seen == frozenset({domain})


# --- where every record is the owner's: as the counting build ---------------------------


async def _owners_only(mode: SightMode) -> tuple[_World, str]:
    world = _World(mode)
    await world.hold(episode("a-1", text="Plan the camping trip."), episode("a-2"))
    trip = await world.story(_OWNERS, "a-1", note="trip")
    other = await world.story(_OWNERS, "a-1", note="other")
    flag = await world.summarise(
        trip, "A trip.", StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other)
    )
    assert (await world.stories.leave_flag(flag, actor=StoryActor.MATTERS_PASS)).refusal is None
    await world.summarise(other, "Another.", StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    await world.stories.link(trip, [activation("a-2")], actor=StoryActor.OWNER)
    return world, trip


async def test_where_every_record_is_the_owners_a_withholding_run_is_as_the_counting_one() -> None:
    """§3:1 withholds nothing of the owner's own: the same reads, models shown and writes."""
    seen: dict[SightMode, tuple[object, ...]] = {}
    for mode in SightMode:
        world, trip = await _owners_only(mode)
        tidying = _Model(_TIDIED, key="note")
        deciding = _Model(_LEAVE, key="story")

        tidied = await world.scheduled(tidying).run()
        decided = await world.matters(deciding).run()

        state = await world.stories.current_summary(trip)
        assert state is not None
        seen[mode] = (
            tidied,
            decided,
            [[message.content for message in one] for one in tidying.messages],
            [[message.content for message in one] for one in deciding.messages],
            state.summary,
        )

    assert seen[SightMode.WITHHOLD] == seen[SightMode.COUNT]
    tidied_report, decided_report = seen[SightMode.COUNT][:2]
    assert tidied_report.written == 2  # type: ignore[attr-defined]
    assert decided_report.decided == 1  # type: ignore[attr-defined]


# --- the shared things beside the owner's -----------------------------------------------


async def _beside(mode: SightMode) -> tuple[_World, dict[str, str]]:
    """The owner's trip and the shared things' boiler, each holding, in error, an episode
    of the other's home; and a decision on the trip's flag naming the garage, a story of
    the owner's when the flag was raised and decided and of the shared things since."""
    world = _World(mode)
    await world.hold(
        episode("a-1", text="Plan the camping trip."),
        _of(_SHARED, episode("s-1", text="The boiler service.")),
        _of(_SHARED, episode("s-2", text="The garage door.")),
    )
    trip = await world.story(_OWNERS, "a-1", "s-1", note="trip")
    boiler = await world.story(_SHARED, "s-1", "a-1", note="boiler")
    garage = await world.story(_OWNERS, "s-2", note="garage")
    flag = await world.summarise(
        trip, "A trip.", StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=garage)
    )
    assert (await world.stories.leave_flag(flag, actor=StoryActor.MATTERS_PASS)).refusal is None
    world.stories.set_story_home(garage, _SHARED)
    return world, {"trip": trip, "boiler": boiler, "garage": garage}


def _episodes(shown: dict[str, Any]) -> list[str]:
    return [one["the_users_own_input"] for one in shown["episodes"]]


def _decisions(shown: dict[str, Any]) -> list[tuple[str, list[str], int]]:
    return [
        (
            one["flag"],
            one["stories_its_flag_concerns"],
            one["other_stories_its_flag_concerns"],
        )
        for one in shown["decisions"]
    ]


@_MODES
async def test_each_scheduled_run_reads_its_own_domain_alone(mode: SightMode) -> None:
    """The look-alike stories (read 1), the stories a decision concerns (read 3) and the
    episodes: where the stores withhold, the owner's run is shown nothing of the shared
    things and the shared things' run nothing of the owner's; the counting build shows
    them as before. An episode of another home is taken in by neither (§4:2)."""
    world, named = await _beside(mode)
    model = _Model(_TIDIED, key="note")

    report = await world.scheduled(model).run()

    assert report.written == 3
    trip, boiler = model.shown["trip"], model.shown["boiler"]
    withholding = mode is SightMode.WITHHOLD
    assert _episodes(trip) == ["Plan the camping trip."]
    assert _episodes(boiler) == ["The boiler service."]
    assert [one["label"] for one in trip["other_stories"]] == ([] if withholding else ["S1"])
    assert [one["label"] for one in boiler["other_stories"]] == ([] if withholding else ["S1"])
    # The garage, of the shared things since, is neither named nor counted by the owner's.
    assert _decisions(trip) == [("like_another", ["this story"], 0 if withholding else 1)]
    for key, home in (("trip", _OWNERS), ("boiler", _SHARED)):
        state = await world.stories.current_summary(named[key])
        assert state is not None
        assert state.story.home == home
        assert state.pending_episodes == (("s-1",) if key == "trip" else ("a-1",))


async def test_the_counting_build_counts_what_a_withholding_store_would_keep_back() -> None:
    """§11:1: every run's read writes its event as the run's, by its bounds."""
    world, _named = await _beside(SightMode.COUNT)

    with capture_logs() as logs:
        await world.scheduled(_Model(_TIDIED, key="note")).run()

    counted = _counted(logs)
    assert counted
    assert {one["reader"] for one in counted} == {"run"}
    assert {tuple(one["bounds"]) for one in counted} == {("domain", "person_owner")}
    # The finding of what is due (read 4): each run's read of every story's header counts
    # the stories of the other domain as another home's.
    headers = [one for one in counted if (one["store"], one["member"]) == ("stories", "stories")]
    assert {(one["given"], one["other_home"]) for one in headers} == {(3, 2), (3, 1)}
    assert sum(one["other_home"] for one in counted) > len(headers)


@_MODES
async def test_the_matters_pass_shows_its_domain_s_episodes_and_decisions_alone(
    mode: SightMode,
) -> None:
    """The episodes it shows (read 2) and the stories a decision concerns (read 3)."""
    world, named = await _beside(mode)
    await world.summarise(
        named["trip"], "A trip, again.", StoryFlag(kind=StoryFlagKind.TWO_MATTERS)
    )
    await world.summarise(named["boiler"], "A boiler.", StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    model = _Model(_LEAVE, key="story")

    report = await world.matters(model).run()

    assert report.decided == 2
    trip, boiler = model.shown["A trip, again."], model.shown["A boiler."]
    withholding = mode is SightMode.WITHHOLD
    shown = [one["the_users_own_input"] for one in trip["episodes"]]
    assert shown == (
        ["Plan the camping trip."]
        if withholding
        else ["Plan the camping trip.", "The boiler service."]
    )
    shown = [one["the_users_own_input"] for one in boiler["episodes"]]
    assert shown == (
        ["The boiler service."]
        if withholding
        else ["The boiler service.", "Plan the camping trip."]
    )
    assert _decisions(trip) == [("like_another", ["S1"], 0 if withholding else 1)]
    assert _decisions(boiler) == []


@_MODES
async def test_no_run_decides_a_flag_one_of_whose_stories_is_of_another_domain(
    mode: SightMode,
) -> None:
    """§5:3: where the stores withhold, the other story is absent to the run; where they
    count, it is of another domain. Either way no completion and nothing written."""
    world = _World(mode)
    await world.hold(episode("a-1"), _of(_SHARED, episode("s-1")))
    trip = await world.story(_OWNERS, "a-1")
    other = await world.story(_OWNERS, "s-1")
    await world.summarise(trip, "A trip.", StoryFlag(kind=StoryFlagKind.LIKE_ANOTHER, story=other))
    world.stories.set_story_home(other, _SHARED)
    model = _Model(_LEAVE, key="story")

    report = await world.matters(model).run()

    assert (report.flags, report.decided, report.left_by_rule) == (0, 0, 0)
    assert model.messages == []


# --- the reconsideration ------------------------------------------------------------------


class _Seen(FakeNotificationStore):
    """Keeps the home of every record a read of the due set gave back."""

    seen: list[RecordHome]

    async def due(self, *, limit: int = 50, offset: int = 0) -> list[HeldNotification]:
        page = await super().due(limit=limit, offset=offset)
        self.seen.extend(record.home for record in page)
        return page


@_MODES
async def test_the_reconsideration_pages_through_the_owners_records_alone(
    mode: SightMode,
) -> None:
    """§3:4 and read 4: where the stores withhold, its finding of what is due gives back
    no notification of another domain, so it pages past none; counting, it reads them as
    before and leaves them as they are."""
    store = _Seen(now=lambda: ENGINE_AT, sight_mode=mode)
    store.seen = []
    policy = FakeNotificationPolicy()
    for key, home in (("k1", _SHARED), ("k2", _SHARED), ("k3", _OWNERS), ("k4", _OWNERS)):
        await store.admit(_notification(key), home=home, policy=policy)
    engine = _engine(Harness(), store, people=None, factory=None)
    await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),)
        )
    )

    with capture_logs() as logs:
        ruled = await engine.reconsider_notifications(page=1)
    read = list(store.seen)

    assert ruled == 2
    assert [record.home for record in await store.due()] == [_SHARED, _SHARED]
    if mode is SightMode.WITHHOLD:
        assert set(read) == {_OWNERS}
    else:
        assert _SHARED in read
        counted = [one for one in _counted(logs) if one["store"] == "notifications"]
        assert {one["reader"] for one in counted} == {"run"}
        assert sum(one["other_home"] for one in counted if one["member"] == "due") >= 2


async def test_the_reconsideration_reads_the_owners_zone_through_its_run_s_sight() -> None:
    """ADR-0338 §3:6 through the holder: the zone read is counted as the run's."""
    store = FakeNotificationStore(now=lambda: ENGINE_AT)
    await store.admit(_notification("k1"), home=_OWNERS, policy=FakeNotificationPolicy())
    factory = _Factory()
    engine = _engine(Harness(), store, people=await _people(_TOKYO), factory=factory)
    await engine.set_notification_preferences(
        NotificationPreferences(
            reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.INTERRUPT),)
        )
    )

    with capture_logs() as logs:
        await engine.reconsider_notifications()

    assert factory.zones == [_TOKYO]
    reads = [one for one in _counted(logs) if one["store"] == "person_model"]
    assert reads
    assert {(one["member"], one["reader"]) for one in reads} == {("read", "run")}


# --- a tidy-up a work asks for (ADR-0384 §6) ---------------------------------------------


def _tidy_call(story_id: str) -> ToolCall:
    """A tidy-up call as acting hands it the runner, the hub's episode filled."""
    request = ActionRequest(
        tool=TIDY_STORY,
        parameters={STORY_ARGUMENT: story_id, EPISODE_ARGUMENT: address(WORK_ACTIVATION)},
    )
    ruling = PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed")
    return ToolCall(
        request=request,
        decision=PermissionDecision.from_request(request, ruling, id="d-1", decided_at=AT),
    )


async def _asked(mode: SightMode) -> tuple[_World, str, _Model, StoryCalls]:
    world = _World(mode)
    await world.hold(
        episode("a-1", text="Plan the camping trip."), episode(WORK_ACTIVATION, open_=True)
    )
    trip = await world.story(_OWNERS, "a-1", note="trip")
    model = _Model(_TIDIED, key="note")
    return world, trip, model, StoryCalls(stores=world.stores, tidy_up=world.tidy_up(model))


@_MODES
async def test_an_owners_work_tidies_its_story_as_today(mode: SightMode) -> None:
    world, trip, model, calls = await _asked(mode)

    with work_of(_OWNER), capture_logs() as logs:
        result = await calls.run(_tidy_call(trip))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert _episodes(model.shown["trip"]) == ["Plan the camping trip."]
    state = await world.stories.current_summary(trip)
    assert state is not None
    assert state.summary is not None
    if mode is SightMode.COUNT:
        counted = _counted(logs)
        assert counted
        assert {one["reader"] for one in counted} == {"work"}
        assert {tuple(one["bounds"]) for one in counted} == {("domain", "person_owner")} | {
            ("person_owner",)
        }


async def test_an_unidentified_senders_work_is_told_the_story_is_not_there() -> None:
    """§6:1: it reads as every read of its work does, and its work sees nothing of the
    owner's, so the story named is one never written, and nothing is tidied."""
    world, trip, model, calls = await _asked(SightMode.WITHHOLD)

    with work_of(_UNIDENTIFIED):
        result = await calls.run(_tidy_call(trip))
        never = await calls.run(_tidy_call("story:never"))

    assert result.outcome is ToolOutcome.FAILED
    assert result.failure is not None
    assert never.failure is not None
    assert (result.failure.kind, result.failure.message) == (
        never.failure.kind,
        never.failure.message,
    )
    assert (result.failure.kind, result.failure.message) == (
        ToolFailureKind.INVALID_REQUEST,
        "the story named is not there",
    )
    assert model.messages == []
    state = await world.stories.current_summary(trip)
    assert state is not None
    assert state.summary is None


async def test_the_asking_work_s_sight_is_carried_into_the_task_the_tidy_up_runs_in() -> None:
    """ADR-0307 §7:2: the task inherits no work's state; the sight carried is read alone."""
    world, trip, model, calls = await _asked(SightMode.WITHHOLD)
    with work_of(_OWNER) as work:
        sight = work.sight

    async def tidy(carried: Sight | None) -> ToolResult:
        with tidy_up_asked_by(carried):
            return await calls.run(_tidy_call(trip))

    loop = asyncio.get_running_loop()
    unasked = await loop.create_task(tidy(None), context=contextvars.Context())
    asked = await loop.create_task(tidy(sight), context=contextvars.Context())

    assert unasked.outcome is ToolOutcome.FAILED
    assert unasked.failure is not None
    assert unasked.failure.kind is ToolFailureKind.INTERNAL
    assert asked.outcome is ToolOutcome.SUCCEEDED
    assert list(model.shown) == ["trip"]
    state = await world.stories.current_summary(trip)
    assert state is not None
    assert state.summary is not None


async def test_a_work_s_tidy_up_of_a_story_of_the_shared_things_is_not_done() -> None:
    """§6:2: an owner's work may see the shared things, but its records land in the
    owner's domain, so it tidies none of theirs."""
    world = _World(SightMode.WITHHOLD)
    await world.hold(_of(_SHARED, episode("s-1")), episode(WORK_ACTIVATION, open_=True))
    boiler = await world.story(_SHARED, "s-1", note="boiler")
    model = _Model(_TIDIED, key="note")
    calls = StoryCalls(stores=world.stores, tidy_up=world.tidy_up(model))

    with work_of(_OWNER):
        result = await calls.run(_tidy_call(boiler))

    assert result.failure is not None
    assert (result.failure.kind, result.failure.message) == (
        ToolFailureKind.REFUSED,
        "the tidy-up wrote nothing: no_story",
    )
    assert model.messages == []


# --- the matters pass's episodes: from the members the bound store gives back -------------


@_MODES
async def test_withheld_members_take_no_episode_slot_and_are_not_counted(mode: SightMode) -> None:
    """ADR-0384 §5:2 (round 2's regression): one owner episode, then six of the shared
    things linked in error, with six slots. Where the stores withhold, the owner's episode
    is shown and nothing of the six is shown or counted; the counting build shows the six
    as before, the oldest link left over and counted."""
    world = _World(mode)
    shared = [f"s-{index}" for index in range(1, 7)]
    await world.hold(
        episode("a-1", text="Plan the camping trip."),
        *(_of(_SHARED, episode(one, text=f"Shared {one}.")) for one in shared),
    )
    trip = await world.story(_OWNERS, "a-1", *shared)
    await world.summarise(trip, "A trip.", StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    model = _Model(_LEAVE, key="story")

    await world.matters(model).run()

    (story,) = model.shown["A trip."]["stories"]
    shown = [one["the_users_own_input"] for one in model.shown["A trip."]["episodes"]]
    if mode is SightMode.WITHHOLD:
        assert shown == ["Plan the camping trip."]
        assert (len(story["episodes"]), story["episodes_not_shown"]) == (1, 0)
    else:
        assert shown == [f"Shared {one}." for one in shared]
        assert (len(story["episodes"]), story["episodes_not_shown"]) == (6, 1)


async def test_forgotten_members_take_no_slot_and_are_not_counted() -> None:
    """Where every record is the owner's: a story whose latest links name episodes the
    memory store no longer holds shows its older held episodes in their place, and counts
    nothing of the forgotten ones (ADR-0384 §5's paragraph under §5:3, ADR-0383 §8:2)."""
    world = _World(SightMode.WITHHOLD)
    held = [f"a-{index}" for index in range(1, 4)]
    forgotten = [f"gone-{index}" for index in range(1, 7)]
    await world.hold(*(episode(one, text=f"Held {one}.") for one in held))
    trip = await world.story(_OWNERS, *held, *forgotten)
    await world.summarise(trip, "A trip.", StoryFlag(kind=StoryFlagKind.TWO_MATTERS))
    model = _Model(_LEAVE, key="story")

    await world.matters(model).run()

    (story,) = model.shown["A trip."]["stories"]
    shown = [one["the_users_own_input"] for one in model.shown["A trip."]["episodes"]]
    assert shown == [f"Held {one}." for one in held]
    assert (len(story["episodes"]), story["episodes_not_shown"]) == (3, 0)


# --- the scheduled tidy-up's finding of what is due: from what the store gives back -----


@_MODES
async def test_a_withheld_pending_episode_does_not_reach_the_threshold(mode: SightMode) -> None:
    """Round 3's regression (ADR-0384 §5:2): a note and an episode of the owner's are two
    pending, under a threshold of three; a shared episode linked in error is a third only
    where the stores count, as before."""
    world = _World(mode)
    await world.hold(episode("a-1"), _of(_SHARED, episode("s-1")))
    await world.story(_OWNERS, "a-1", "s-1", note="trip")
    model = _Model(_TIDIED, key="note")

    report = await world.scheduled(model, threshold=3).run()

    assert report.due == (0 if mode is SightMode.WITHHOLD else 1)
    assert list(model.shown) == ([] if mode is SightMode.WITHHOLD else ["trip"])


@_MODES
async def test_a_withheld_pending_episode_does_not_keep_a_story_from_going_quiet(
    mode: SightMode,
) -> None:
    """The quiet period counts from the newest of what is pending that the store gives
    back: a shared episode linked in error an hour ago delays the story only where the
    stores count, as before."""
    world = _World(mode)
    await world.hold(episode("a-1"), _of(_SHARED, episode("s-1")))
    trip = await world.story(_OWNERS, "a-1", note="trip")
    later = AT + _QUIET
    world.at = later
    assert (
        await world.stories.link(trip, [activation("s-1")], actor=StoryActor.UNDERSTANDING)
    ).refusal is None
    model = _Model(_TIDIED, key="note")

    report = await world.scheduled(model, threshold=10, now=later + timedelta(hours=1)).run()

    assert report.due == (1 if mode is SightMode.WITHHOLD else 0)


async def test_a_story_pending_only_an_episode_no_longer_held_is_not_due() -> None:
    """Where every record is the owner's: a member the memory store no longer holds is
    not taken in, so it makes nothing due (ADR-0384 §5's paragraph under §5:3)."""
    world = _World(SightMode.COUNT)
    await world.story(_OWNERS, "gone")
    model = _Model(_TIDIED, key="note")

    report = await world.scheduled(model, threshold=1).run()

    assert (report.due, report.passed_over) == (0, 0)
    assert model.messages == []
