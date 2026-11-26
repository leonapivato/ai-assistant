"""A work's side of what the stores need before they withhold (ADR-0388 §3, §5, §6).

Milestone 22's B11b. Three things a work does that a withholding store would otherwise
leave undecided:

- **A story a work starts is one write** (§3:1, §3:2): one create through the work's bound
  story store, carrying its first notes, after which nothing of the story is read back.
  An unidentified sender's work starts it whole, in the owner's home, and sees nothing of
  it afterwards. A refused first note refuses the start, writing nothing.
- **A work with no recorded facts has a work's sight** (§5:1, §5:3): an anyone bound
  alone and its activation, so it holds its own records and nothing else, and its reads
  are counted as a work's.
- **A limited write is made only where the writer's sight sees the record's home**
  (§6:1, §6:2): the chain limit, the pending limit and the request already waiting each
  count every record of the home the writer's sight sees, and a writer whose sight does
  not see it is not made the write and is answered as where the call is not offered. The
  effect claim's backstop, for a work that does not see its own home, is judged among its
  own effects (§6:3).

Every case runs over stores built to withhold, and where the owner's work is concerned
in the counting build too, which answers as today.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final, Self
from zoneinfo import ZoneInfo

import pytest
from sight_support import UNIDENTIFIED, holder, in_a_work
from story_support import AT, WORK_ACTIVATION, address, episode, owners_work, work_of
from structlog.testing import capture_logs
from task_support import CHAT, LIMITS, activation, pushed, spawn_effect, write_task
from test_acting_authorizing_tasks_sight import (
    _BOOK,
    _acting,
    _ask,
    _booked,
    _not_offered,
    _owner,
    _stranger,
)
from test_stories_through_the_sight import _call as story_call

import ai_assistant.orchestration.work_facts as work_facts_module
from ai_assistant.core.errors import UnresolvedEvidenceError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    STORY_NOTE_MAX_CHARS,
    ActionRequest,
    ApprovalRequestState,
    ChannelIdentity,
    ChannelInput,
    JoinedInput,
    MemoryWrite,
    MemoryWriteMode,
    NewConversation,
    OccurrenceState,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    RecordedInputMessage,
    RecordHome,
    SightBound,
    SightMode,
    SightReader,
    StoryActor,
    StoryFirstNote,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    TextChannelPayload,
    ToolCall,
    ToolOutcome,
    ToolResult,
    WholeTextReply,
)
from ai_assistant.orchestration.acting import (
    ActedOutcome,
    AuthorizedCall,
    AuthorizedRound,
    Unwritten,
)
from ai_assistant.orchestration.activation_state import admit_channel
from ai_assistant.orchestration.held_results import HeldResults
from ai_assistant.orchestration.story_calls import (
    INSIDE_ARGUMENT,
    NOTE_ARGUMENT,
    NOTE_STORY,
    NOTES_ARGUMENT,
    START_STORY,
    STORY_ARGUMENT,
    StartUnfinishedError,
    StoryCalls,
)
from ai_assistant.orchestration.task_manager import (
    ScheduledTaskCalls,
    TaskManager,
    TaskManagerLimits,
)
from ai_assistant.orchestration.task_rules import PersonZones
from ai_assistant.orchestration.task_scheduler import SPAWN, Spawner, spawning
from ai_assistant.testing import FakeMemoryStore, FakePlanStore, FakeStoryStore

if TYPE_CHECKING:
    from ai_assistant.core.protocols import StoryStore
    from ai_assistant.core.types import EpisodicMemory, FrozenJson, Sight
    from ai_assistant.orchestration.activation_state import ActivationState

_MODES: Final = pytest.mark.parametrize(
    "mode", [SightMode.COUNT, SightMode.WITHHOLD], ids=["count", "withhold"]
)


# --- a story a work starts: one write (§3) ---------------------------------------------------


class _Seen:
    """The canonical fake story store, noting each member a call reaches on it.

    The fake is final, so it is wrapped: every member is handed to it, and ``bound``
    gives a wrapper of the bound fake sharing the one log.
    """

    def __init__(self, inner: Any, log: list[tuple[str, dict[str, Any]]]) -> None:
        self.inner = inner
        self.log = log

    def bound(self, sight: Sight) -> Self:
        return type(self)(self.inner.bound(sight), self.log)

    def __getattr__(self, name: str) -> Any:
        member = getattr(self.inner, name)
        if not callable(member):
            return member

        async def noted(*args: Any, **kwargs: Any) -> Any:
            self.log.append((name, kwargs))
            return await member(*args, **kwargs)

        return noted


class _Start:
    """A story runner over the fakes, built to ``mode``, its story store noted.

    The owner's earlier story holds an earlier episode of theirs, and the running work's
    own episode is open.
    """

    def __init__(self, mode: SightMode) -> None:
        ids = iter(range(1, 100))
        self.stories = FakeStoryStore(
            now=lambda: AT, new_id=lambda: f"{next(ids)}", sight_mode=mode
        )
        self.memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
        self.log: list[tuple[str, dict[str, Any]]] = []
        seen = _Seen(self.stories, self.log)
        self.calls = StoryCalls(stores=holder(memory=self.memory, stories=cast_stories(seen)))
        self.larger = ""

    async def seed(self) -> Self:
        await self.memory.write_atomic(
            [
                MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT)
                for one in (episode("a-earlier"), episode(WORK_ACTIVATION, open_=True))
            ]
        )
        made = await self.stories.create(
            [StoryMember(kind=StoryMemberKind.ACTIVATION, id="a-earlier")],
            home=RecordHome.owners(),
            actor=StoryActor.OWNER,
        )
        assert made.story_id is not None
        self.larger = made.story_id
        return self

    def after_the_create(self) -> list[str]:
        """Each member reached on the story store after the start's create, in order."""
        names = [name for name, _ in self.log]
        assert names.count("create") == 1, names
        return names[names.index("create") + 1 :]

    def created_with(self) -> dict[str, Any]:
        (kwargs,) = [kwargs for name, kwargs in self.log if name == "create"]
        return kwargs

    async def started(self) -> Any:
        """The one story the start made, read unbound."""
        page = await self.stories.stories()
        (started,) = [one for one in page.stories if one.story_id != self.larger]
        return started


def cast_stories(seen: _Seen) -> StoryStore:
    """The noted store, as the holder takes it."""
    return seen  # type: ignore[return-value]  # structurally a StoryStore, every member handed on


def _start(**arguments: FrozenJson) -> ToolCall:
    return story_call(
        START_STORY, {NOTES_ARGUMENT: ["A trip.", "Waiting on Sam."], **arguments}, decision="d"
    )


@_MODES
async def test_the_owners_start_is_one_create_carrying_its_notes(mode: SightMode) -> None:
    """§3:1, §3:3: one create carries the notes, each planning's, written during this
    activation with the hub's mark; nothing of the story is read back after it; the
    story holds its notes, in the owner's home, as when they were two writes."""
    world = await _Start(mode).seed()
    with owners_work():
        result = await world.calls.run(_start())

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert world.after_the_create() == []
    assert world.created_with()["notes"] == tuple(
        StoryFirstNote(
            text=text,
            author=StoryNoteAuthor.PLANNING,
            written_during=WORK_ACTIVATION,
            outside=False,
        )
        for text in ("A trip.", "Waiting on Sam.")
    )
    started = await world.started()
    assert started.home == RecordHome.owners()
    notes = await world.stories.notes(started.story_id)
    assert notes is not None
    assert [(one.text, one.written_during) for one in notes.notes] == [
        ("A trip.", WORK_ACTIVATION),
        ("Waiting on Sam.", WORK_ACTIVATION),
    ]


async def test_the_owners_start_inside_a_larger_story_then_writes_its_place_alone() -> None:
    """§3:1 with ADR-0300 §10:3: the larger story is read first; after the create, the
    only member reached is the link placing the story inside it."""
    world = await _Start(SightMode.WITHHOLD).seed()
    with owners_work():
        result = await world.calls.run(_start(**{INSIDE_ARGUMENT: world.larger}))

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert world.after_the_create() == ["link"]
    started = await world.started()
    assert StoryMember(kind=StoryMemberKind.STORY, id=started.story_id) in {
        entry.member
        for entry in (await world.stories.view(world.larger)).entries  # type: ignore[union-attr]
    }


async def test_an_unidentified_senders_start_lands_whole_in_the_owners_home() -> None:
    """§3:1, §3:2: under a withholding store its start is one write, done whole, in the
    owner's home (ADR-0383 §4:4); the work reads nothing of the story back, and a later
    note naming it is answered as one naming a story never written (§8:2)."""
    world = await _Start(SightMode.WITHHOLD).seed()
    with work_of(UNIDENTIFIED):
        result = await world.calls.run(_start())
        after = world.after_the_create()
        started = await world.started()
        later = await world.calls.run(
            story_call(
                NOTE_STORY,
                {STORY_ARGUMENT: started.story_id, NOTE_ARGUMENT: "Later."},
                decision="e",
            )
        )
        never = await world.calls.run(
            story_call(
                NOTE_STORY, {STORY_ARGUMENT: "story:never", NOTE_ARGUMENT: "Later."}, decision="e"
            )
        )

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert after == []
    assert started.home == RecordHome.owners()
    notes = await world.stories.notes(started.story_id)
    assert notes is not None
    assert [one.text for one in notes.notes] == ["A trip.", "Waiting on Sam."]
    assert later == never
    assert later.outcome is ToolOutcome.FAILED


@pytest.mark.parametrize("sender", [None, UNIDENTIFIED], ids=["owners", "unidentified"])
async def test_a_refused_first_note_refuses_the_start_whole(sender: Any) -> None:
    """§3:1: a note the store would refuse (here one past the cap) refuses the
    start, and nothing is written: no story, no position moved, and no create made. The
    work is told what it was told when the note was refused after its story was made:
    the start unfinished (ADR-0306 §5:6).

    A validated call cannot carry such a note, its schema bounding each, so the call is
    built round that validation: this pins the runner's own guard.
    """
    world = await _Start(SightMode.WITHHOLD).seed()
    before = await world.stories.position()
    made = _start()
    parameters = {
        **made.request.parameters,
        NOTES_ARGUMENT: ["A trip.", "x" * (STORY_NOTE_MAX_CHARS + 1)],
    }
    call = made.model_copy(
        update={"request": made.request.model_copy(update={"parameters": parameters})}
    )
    work = owners_work() if sender is None else work_of(sender)
    with work, pytest.raises(StartUnfinishedError):
        await world.calls.run(call)

    assert [one.story_id for one in (await world.stories.stories()).stories] == [world.larger]
    assert await world.stories.position() == before
    assert [name for name, _ in world.log] == []


# --- a work with no recorded facts (§5) -------------------------------------------------------

_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="line-ref/42")


def _unrecorded(
    monkeypatch: pytest.MonkeyPatch, activation_id: str = WORK_ACTIVATION
) -> ActivationState:
    """A hub chat message admitted where deciding its facts fails (ADR-0368 §2:4)."""

    def _raises(*_: object, **__: object) -> None:
        raise RuntimeError("a defect")

    monkeypatch.setattr(work_facts_module, "started", _raises)
    state = admit_channel(
        ChannelInput(target=NewConversation(), payload=TextChannelPayload(text="hello")),
        WholeTextReply(),
        clock=lambda: AT,
        id_factory=lambda: activation_id,
    )
    assert state.work_facts is None
    return state


def _sight(state: ActivationState) -> Sight:
    sight = state.sight
    assert sight is not None
    return sight


def test_a_work_with_no_facts_has_a_works_sight_of_an_anyone_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:1, §5:3: a work's sight, an anyone bound alone and its activation; the log
    still says its sight is narrower than its facts would give."""
    with capture_logs() as logs:
        state = _unrecorded(monkeypatch)

    sight = _sight(state)
    assert sight.reader is SightReader.WORK
    assert sight.bounds == (SightBound.anyone(),)
    assert sight.activation == WORK_ACTIVATION
    assert {"event": "work_sight_degraded", "at": "start", "reason": "facts"} in [
        {key: one[key] for key in ("event", "at", "reason") if key in one} for one in logs
    ]


def test_a_join_into_a_work_with_no_facts_never_widens_its_sight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:2 with ADR-0383 §6:6: an input joining records no facts for it, so its sight
    made again is the one it had, never wider, and remaking it raises nothing."""
    state = _unrecorded(monkeypatch)
    before = _sight(state)
    joined = JoinedInput(
        joined_at=AT,
        channel=_LINE,
        messages=(RecordedInputMessage(text="and Saturday", sent_at=AT),),
    )

    state.take_inputs((joined,), merged=("act-other",))

    after = _sight(state)
    assert after.reader is SightReader.WORK
    assert after.activation == before.activation
    assert set(after.bounds) == {SightBound.anyone()}


def _taken_from(opened: EpisodicMemory, taken: str) -> EpisodicMemory:
    """``opened`` with an input taken over from ``taken``'s work (ADR-0349 §7:7)."""
    record = opened.processing_record
    assert record is not None
    joined = JoinedInput(
        joined_at=AT,
        channel=_LINE,
        messages=(RecordedInputMessage(text="and Saturday", sent_at=AT),),
        taken_over_from=taken,
    )
    return opened.model_copy(
        update={"processing_record": record.model_copy(update={"joined": (joined,)})}
    )


async def test_a_work_with_no_facts_holds_only_its_own_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5:1 with ADR-0383 §7:4: under withholding stores it is given back its own
    episode, its own effects and the requests it asked, and nothing of the owner's."""
    state = _unrecorded(monkeypatch)
    sight = _sight(state)
    memory = FakeMemoryStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD)
    own = episode(WORK_ACTIVATION, open_=True).model_copy(update={"home": state.home})
    await memory.write_atomic(
        [
            MemoryWrite(record=one, mode=MemoryWriteMode.INSERT_IF_ABSENT)
            for one in (own, episode("a-owners"))
        ]
    )
    plans = FakePlanStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD)
    await write_task(plans, activation())
    mine = spawn_effect(WORK_ACTIVATION)
    await plans.bound(sight).claim_activation_effect(mine, match=None)
    owners = spawn_effect("a-owners")
    await plans.claim_activation_effect(owners, match=None)

    bound = memory.bound(sight)
    got = await bound.get(own.id)
    assert got is not None
    assert got.id == own.id
    assert await bound.get(address("a-owners")) is None
    held = await plans.bound(sight).activation_effects([WORK_ACTIVATION, "a-owners"])
    assert [one.id for one in held] == [mine.id]
    assert (
        await plans.bound(sight).person_scheduled_tasks(OWNER_PERSON_ID, tuple(OccurrenceState))
        == ()
    )


async def test_a_work_with_no_facts_writes_its_own_episodes_takeover_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0388 §2:5 through §5:1: its capture's write of its own episode, naming as an
    input's source an activation whose episode was deleted, lands; the same name on an
    episode that is not its own is refused as unresolved (§2:1)."""
    state = _unrecorded(monkeypatch)
    sight = _sight(state)
    memory = FakeMemoryStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD)
    own = episode(WORK_ACTIVATION, open_=True).model_copy(update={"home": state.home})
    other = episode("a-other", open_=True).model_copy(update={"home": state.home})
    await memory.add(episode("a-gone"))
    assert await memory.delete(address("a-gone")) is True
    await memory.add(own)
    bound = memory.bound(sight)

    await bound.add(_taken_from(own, "a-gone"))

    got = await memory.get(own.id)
    assert got is not None
    assert got.processing_record is not None  # type: ignore[union-attr]
    assert [one.taken_over_from for one in got.processing_record.joined] == ["a-gone"]  # type: ignore[union-attr]
    # Another name, since its own episode now carries the first (§2:2).
    with pytest.raises(UnresolvedEvidenceError):
        await bound.add(_taken_from(other, "a-gone-too"))


@_MODES
async def test_a_work_with_no_facts_is_counted_as_a_work(
    monkeypatch: pytest.MonkeyPatch, mode: SightMode
) -> None:
    """§5:1 with ADR-0383 §11:1: its reads' count events carry the reader ``work``."""
    state = _unrecorded(monkeypatch)
    memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
    with capture_logs() as logs:
        await memory.bound(_sight(state)).get(address(WORK_ACTIVATION))
    counted = [one for one in logs if one["event"] == "sight_counted"]
    if mode is SightMode.COUNT:
        assert [one["reader"] for one in counted] == ["work"]
    else:
        assert counted == []


# --- a limited write: only where the writer's sight sees the home (§6) -----------------------


def _manager(plans: FakePlanStore, limits: TaskManagerLimits) -> ScheduledTaskCalls:
    manager = TaskManager(
        stores=holder(plans=plans, memory=FakeMemoryStore(now=lambda: AT)),
        plans=plans,
        running=lambda: (),
        is_running=lambda _one: False,
        starting=lambda _one: False,
        wake=lambda: None,
        limits=limits,
        zones=PersonZones(default=ZoneInfo("UTC")),
        now=lambda: AT,
    )
    return ScheduledTaskCalls(manager=manager, now=lambda: AT)


def _spawner(parent: str) -> Spawner:
    return Spawner(
        activation_id=parent,
        person=OWNER_PERSON_ID,
        authority=OWNER_PERSON_ID,
        set_in=CHAT,
        places=(f"conversation:{CHAT.instance_id}",),
    )


def _spawn_call() -> ToolCall:
    request = ActionRequest(tool=SPAWN, parameters={"instruction": "check back"})
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id=f"decision:{uuid.uuid4().hex}",
        decided_at=AT,
    )
    return ToolCall(request=request, decision=decision)


async def _spawn(
    calls: ScheduledTaskCalls, parent: str, *senders: Any, offered: bool = True
) -> object:
    """A spawn by ``parent`` in a work from ``senders``, or with spawn not offered."""
    with in_a_work(*senders, at=AT, activation_id=parent):
        if not offered:
            return await calls.run_claiming(
                _spawn_call(), spawn_effect(parent), match=None, deliberate_repeat=False
            )
        with spawning(_spawner(parent)):
            return await calls.run_claiming(
                _spawn_call(), spawn_effect(parent), match=None, deliberate_repeat=False
            )


async def _not_written(plans: FakePlanStore, parent: str) -> None:
    """Nothing of ``parent``'s spawn was written: no effect record, no task it set."""
    assert await plans.activation_effects([parent]) == ()
    assert await plans.spawned_tasks([parent]) == ()


@_MODES
async def test_the_pending_limit_counts_every_task_of_the_home_the_writer_sees(
    mode: SightMode,
) -> None:
    """§6:1, §6:2 with ADR-0350 §9:8: the owner's tasks other works spawned fill the
    limit, so the owner's work is refused as today; a writer that does not see the
    owner's domain is not made the write, and is answered as where spawn is not offered."""
    plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
    calls = _manager(plans, TaskManagerLimits(chain_limit=10, pending_limit=2, listing_bound=20))
    for _ in range(2):
        await write_task(plans, activation())

    owners = await _spawn(calls, activation())
    stranger = activation()
    strangers = await _spawn(calls, stranger, UNIDENTIFIED)
    not_offered = await _spawn(calls, activation(), offered=False)

    assert isinstance(owners, Unwritten)
    assert "pending limit" in owners.reason
    assert strangers == not_offered
    assert isinstance(strangers, Unwritten)
    await _not_written(plans, stranger)


@_MODES
async def test_the_chain_limit_counts_the_task_of_the_home_the_writer_sees(
    mode: SightMode,
) -> None:
    """§6:1, §6:2 with ADR-0350 §9:7: a task's work spawning past the chain limit is
    refused as today; a writer whose sight does not see the owner's domain is answered
    as where spawn is not offered, and nothing is written."""
    plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
    calls = _manager(plans, TaskManagerLimits(chain_limit=1, pending_limit=50, listing_bound=20))
    chained = await pushed(plans, await write_task(plans, activation()))
    again = await pushed(plans, await write_task(plans, activation()))

    owners = await _spawn(calls, chained)
    strangers = await _spawn(calls, again, UNIDENTIFIED)
    not_offered = await _spawn(calls, activation(), offered=False)

    assert isinstance(owners, Unwritten)
    assert "chain limit" in owners.reason
    assert strangers == not_offered
    await _not_written(plans, again)


async def test_a_spawn_the_writer_sees_the_home_of_is_written_in_either_build() -> None:
    """§6:2 refuses no write code makes today: the owner's work's spawn is written."""
    for mode in (SightMode.COUNT, SightMode.WITHHOLD):
        plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
        written = await _spawn(_manager(plans, LIMITS), activation())
        assert isinstance(written, ToolResult), written
        assert written.outcome is ToolOutcome.SUCCEEDED


@_MODES
async def test_a_request_already_waiting_is_found_among_the_home_the_writer_sees(
    mode: SightMode,
) -> None:
    """§6:1, §6:2 with ADR-0361 §2:8: the owner's work finds the owner's request another
    work asked already waiting, as today; a writer that does not see the owner's domain
    is answered as where the call is not offered, and nothing is written."""
    plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
    first = activation()
    assert isinstance(await _ask(plans, activation_id=first), ToolResult)

    again = await _ask(plans, activation_id=activation())
    stranger = activation()
    strangers = await _ask(plans, UNIDENTIFIED, activation_id=stranger)
    not_offered = await _not_offered(FakePlanStore(now=lambda: AT, sight_mode=mode))

    assert isinstance(again, Unwritten)
    assert "already waits" in again.reason
    assert strangers == not_offered
    held = await plans.person_approval_requests(OWNER_PERSON_ID, tuple(ApprovalRequestState))
    assert [one.activation_id for one in held] == [first]
    assert await plans.activation_effects([stranger]) == ()


# --- the effect claim's backstop, for a work that does not see its own home (§6:3) ----------


async def _again(
    plans: FakePlanStore, sight: Sight, activation_id: str, matter: str, *, decision: str
) -> Any:
    """The booking, claimed in ``activation_id``'s round ``decision`` under its own record,
    matched against its own effects and ``matter``'s, the other activation in its story."""
    request = ActionRequest(tool=_BOOK, parameters={"date": "2026-11-01"})
    made = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="allowed"),
        id=f"decision:{activation_id}:{decision}",
        decided_at=AT,
        effect=f"effect:{activation_id}:{decision}",
    )
    acted = await _acting(plans).act(
        AuthorizedRound(
            activation_id=activation_id,
            round_id=f"round:{activation_id}:{decision}",
            calls=(AuthorizedCall(ToolCall(request=request, decision=made)),),
            story_activations=(matter,),
        ),
        home=RecordHome.owners(),
        sight=sight,
        held=HeldResults(),
    )
    (one,) = acted.calls
    return one


async def test_a_work_not_seeing_its_own_home_has_its_repeats_caught_among_its_own_effects() -> (
    None
):
    """§6:3: an unidentified sender's work, its home the owner's, repeating its own done
    call is refused as already done; the same call the owner's work made, in the same
    matter, is not among what it holds, so does not stop it (ADR-0383 §8:1)."""
    plans = FakePlanStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD)
    stranger, owners = activation(), activation()
    assert (await _booked(plans, _owner(owners), owners)).outcome is ActedOutcome.DONE

    first = await _again(plans, _stranger(stranger), stranger, owners, decision="1")
    repeat = await _again(plans, _stranger(stranger), stranger, owners, decision="2")

    assert first.outcome is ActedOutcome.DONE, first.reason
    assert repeat.outcome is ActedOutcome.NOT_DONE
    assert repeat.reason is not None
    assert repeat.reason.startswith("already done")


async def test_a_work_with_no_facts_has_its_repeats_caught_among_its_own_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6:3 with §5:1: a work with no facts holds its own effects alone, so its own
    repeat is caught and the owner's identical call is not seen."""
    plans = FakePlanStore(now=lambda: AT, sight_mode=SightMode.WITHHOLD)
    owners = activation()
    work = str(uuid.uuid4())
    assert (await _booked(plans, _owner(owners), owners)).outcome is ActedOutcome.DONE
    sight = _sight(_unrecorded(monkeypatch, work))

    first = await _again(plans, sight, work, owners, decision="1")
    repeat = await _again(plans, sight, work, owners, decision="2")

    assert first.outcome is ActedOutcome.DONE, first.reason
    assert repeat.outcome is ActedOutcome.NOT_DONE
    assert repeat.reason is not None
    assert repeat.reason.startswith("already done")
