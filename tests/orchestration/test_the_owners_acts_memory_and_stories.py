"""The owner's acts on memory and stories read through the owner's sight (ADR-0385 §3 to §5).

Milestone 22's B10b. Every member of ``AssistantEngine`` that reads or writes the memory
store or the story store, and the plan store where such an act reads it, does so through
the stores :class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the
owner's sight from none, made for each call (§3:1, §3:3, §4:1, §5:2). Over the production
SQLite stores, built to count and built to withhold:

- where every record is the owner's or the shared things', each act gives back and writes
  exactly what it gives back and writes over the same stores unbound, as before the sight;
- records of another home, and rows with no home, beside them change no act's answer:
  none gives one back, counts it, pages past it or names it, and an act naming one is
  answered as for one never written, writing nothing (§4:2, §5:3, ADR-0383 §8:2);
- no owner's act writes a ``sight_counted`` event in either build (§3:5), while a work's
  read of the very same store still writes its count (ADR-0383 §11:1).

A record of another home cannot be written through a store in this milestone (ADR-0383
§2:3), so each is written as the owner's and then altered in place, as a row altered
outside the store is; the store's home columns govern it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from pending_candidates_contract import PENDING_AT, PendingCandidatesSubject, _hold, hold_episode
from phases_support import phases_harness
from sight_support import sight_of
from story_support import activation, episode, story
from structlog.testing import capture_logs
from task_support import seams as task_seams

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationEffect,
    ActivationStop,
    ApprovalRequest,
    BeliefBand,
    ConfirmationPart,
    MemoryKind,
    MemorySupport,
    MemoryWriterName,
    PlanningRound,
    ProposedCall,
    ReadingCertainty,
    RecordHome,
    RequestedCall,
    SightMode,
    StoryActor,
    StoryNoteAuthor,
    SupportDirection,
    SupportOrigin,
    ToolOutcome,
)
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.story_store import SqliteStoryStore
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.remembering import REMEMBER_CANDIDATE
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import FakeTraceSink
from ai_assistant.testing.memories import memory, remembered_support, said_support

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from test_engine import Harness

    from ai_assistant.core.protocols import MemoryStore, PlanStore, StoryStore
    from ai_assistant.core.types import FrozenJson, Sight
    from ai_assistant.orchestration.engine import Engine

#: The instant every store and the engine are clocked at.
NOW: Final = PENDING_AT

_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda one: one.value)

#: Activations of the owner's, one ended and one still open, and one of the shared things.
_OWN: Final = "a-own"
_OPEN: Final = "a-open"
_SHARED: Final = "a-shared"
#: An activation whose episode is altered to another person's domain, and one whose home
#: columns are cleared.
_SAM: Final = "a-sam"
_NO_HOME: Final = "a-no-home"
#: An activation, a memory and a story never written.
_NEVER: Final = "a-never"
_NEVER_MEMORY: Final = "m-never"
_NEVER_STORY: Final = "story:never"


def _address(activation_id: str) -> str:
    return f"activation:{activation_id}"


class _AsToday(BoundStores):
    """The holder as the engine read through it before the owner's sight: unbound.

    Handed to an engine over stores seeded alike, it gives every act the stores as they
    are, whatever sight it is asked for, which is how each act read before ADR-0385.
    """

    def memory(self, sight: Sight) -> MemoryStore:
        del sight
        return self._memory

    def stories(self, sight: Sight) -> StoryStore:
        del sight
        assert self._stories is not None
        return self._stories

    def plans(self, sight: Sight) -> PlanStore:
        del sight
        assert self._plans is not None
        return self._plans


@dataclass
class _World:
    """The three SQLite stores, built in one mode, and an engine over them."""

    memory: SqliteMemoryStore
    stories: SqliteStoryStore
    plans: SqlitePlanStore
    harness: Harness
    #: The story ids the seed made, by name.
    named: dict[str, str] = field(default_factory=dict)

    @property
    def engine(self) -> Engine:
        return self.harness.engine

    def rows(self) -> dict[str, list[tuple[object, ...]]]:
        """Every row the homed tables hold, read beside the stores: what an act wrote."""
        return {
            "records": _dump(self.memory._conn, "records"),
            "stories": _dump(self.stories._conn, "stories"),
            "members": _dump(self.stories._conn, "members"),
            "effects": _dump(self.plans._conn, "activation_effects"),
            "stopped": _dump(self.plans._conn, "stopped_activations"),
        }

    def alter(self, store: str, table: str, key: str, ids: Sequence[str], home: Any) -> None:
        """Set the home columns of ``ids``' rows, outside the store (ADR-0383 §5:3)."""
        conn: sqlite3.Connection = getattr(self, store)._conn
        kind, home_id = home
        marks = ", ".join("?" for _ in ids)
        conn.execute(
            f"UPDATE {table} SET home_kind = ?, home_id = ? WHERE {key} IN ({marks})",  # noqa: S608 — the case's own names
            (kind, home_id, *ids),
        )
        conn.commit()


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    return sorted(tuple(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall())  # noqa: S608 — the case's own names


#: Another person's domain, and no home at all, as the columns hold them.
_SAMS: Final = ("person", "person:sam")
_NOBODYS: Final = (None, None)


def _world(mode: SightMode, *, as_today: bool = False) -> _World:
    ids = count(1)
    memory_store = SqliteMemoryStore(
        path=":memory:",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=FakeTraceSink(),
        now=lambda: NOW,
        sight_mode=mode,
    )
    stories = SqliteStoryStore(
        path=":memory:", now=lambda: NOW, new_id=lambda: f"{next(ids):04d}", sight_mode=mode
    )
    plans = SqlitePlanStore(path=":memory:", now=lambda: NOW, sight_mode=mode)
    knobs: dict[str, Any] = {
        "memory": memory_store,
        "stories": stories,
        "plans": plans,
        "now": lambda: NOW,
        # Wired, beside the phases it needs, so the owner's stop of one not running asks
        # whether it was pushed (ADR-0350 §9:10) before it reads the episode.
        "task_scheduler": task_seams(),
    }
    harness = phases_harness(**knobs)
    if as_today:
        harness.engine._stores = _AsToday(memory=memory_store, stories=stories, plans=plans)
    return _World(memory_store, stories, plans, harness)


async def _opened(mode: SightMode, *, others: bool = False, as_today: bool = False) -> _World:
    """A world seeded with the owner's and the shared things' records, and with records of
    another home and rows with no home beside them where ``others``."""
    world = _world(mode, as_today=as_today)
    await _seed_the_owners(world)
    if others:
        await _seed_the_others(world)
    return world


@pytest.fixture
async def worlds() -> AsyncIterator[list[_World]]:
    """Every world a case opens, closed after it."""
    opened: list[_World] = []
    yield opened
    for one in opened:
        for store in (one.memory, one.stories, one.plans):
            store.close()


async def _effect(plans: PlanStore, activation_id: str, home: RecordHome) -> None:
    """A finished call of ``activation_id``'s, so where its story stands lists it done."""
    effect = ActivationEffect(
        home=home,
        id=f"effect:{activation_id}",
        activation_id=activation_id,
        round=f"round:{activation_id}",
        capability="book_table",
        values_digest="0" * 64,
        decision_id=f"decision:{activation_id}",
        claimed_at=NOW - timedelta(minutes=5),
    )
    await plans.claim_activation_effect(effect, match=None)
    await plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)


async def _candidate(world: _World, activation_id: str, fact: str) -> str:
    """An episode whose remember call its effect record shows done (ADR-0329 §3:3)."""
    subject = PendingCandidatesSubject(
        engine=world.engine, memory=cast("Any", world.memory), plans=cast("Any", world.plans)
    )
    return await hold_episode(subject, activation_id, fact)


async def _seed_the_owners(world: _World) -> None:
    """The owner's episodes, memories, stories, effect records and pending candidate, and
    the shared things'; nothing of another home."""
    shared = RecordHome.shared()
    await world.memory.add(episode(_OWN))
    await world.memory.add(episode(_SHARED).model_copy(update={"home": shared}))
    await world.memory.add(episode(_OPEN, open_=True))
    await world.memory.add(
        memory("m-own", "they like the window seat", said_support(_address(_OWN)))
    )
    await world.memory.add(
        memory(
            "m-shared", "the hall light is on a timer", said_support(_address(_SHARED)), home=shared
        )
    )
    await world.memory.add(memory("m-placed", "they are vegetarian", said_support(_address(_OWN))))
    await _candidate(world, "a-candidate", "prefers aisle seats")
    await _effect(world.plans, _OWN, RecordHome.owners())
    await _effect(world.plans, _SHARED, shared)
    trip = await world.stories.create(
        [activation(_OWN), activation(_OPEN)], home=RecordHome.owners(), actor=StoryActor.OWNER
    )
    hall = await world.stories.create([activation(_SHARED)], home=shared, actor=StoryActor.OWNER)
    assert trip.story_id is not None
    assert hall.story_id is not None
    await world.stories.append_note(trip.story_id, "Bring the tent.", author=StoryNoteAuthor.OWNER)
    around = await world.stories.create(
        [story(trip.story_id)], home=RecordHome.owners(), actor=StoryActor.OWNER
    )
    assert around.story_id is not None
    world.named.update(trip=trip.story_id, hall=hall.story_id, around=around.story_id)


async def _seed_the_others(world: _World) -> None:
    """Records of another person's domain and rows with no home, after the owner's, so
    they are the newest of every listing and a page must pass over them.

    Each is written as the owner's and then altered: an episode, a memory resting on it,
    a pending candidate, an effect record, and a story holding the episode, each once of
    Sam's domain and once of no home.
    """
    for one, home in ((_SAM, _SAMS), (_NO_HOME, _NOBODYS)):
        name = one.removeprefix("a-")
        await world.memory.add(episode(one))
        await world.memory.add(memory(f"m-{name}", f"about {name}", said_support(_address(one))))
        candidate = await _candidate(world, f"a-{name}-candidate", f"prefers {name} seats")
        await _effect(world.plans, one, RecordHome.owners())
        made = await world.stories.create(
            [activation(one), activation(_OWN)], home=RecordHome.owners(), actor=StoryActor.OWNER
        )
        assert made.story_id is not None
        await world.stories.append_note(
            made.story_id, f"A note of {name}'s.", author=StoryNoteAuthor.OWNER
        )
        world.named[name] = made.story_id
        world.alter("memory", "records", "id", [_address(one), f"m-{name}", candidate], home)
        world.alter(
            "plans",
            "activation_effects",
            "activation_id",
            [one, f"a-{name}-candidate"],
            home,
        )
        world.alter("stories", "stories", "id", [made.story_id], home)


async def _walk[P](read: Callable[[Any], Awaitable[P]], next_of: Callable[[P], Any]) -> list[P]:
    """Every page of a listing read one item at a time, until it says there is no more."""
    pages: list[P] = []
    cursor: Any = None
    while True:
        page = await read(cursor)
        pages.append(page)
        cursor = next_of(page)
        if cursor is None or len(pages) > 50:
            return pages


async def _reads(world: _World) -> dict[str, object]:
    """What each seeing act of this lane gives back over the owner's records (§4:1)."""
    engine = world.engine
    trip, hall, around = (world.named[name] for name in ("trip", "hall", "around"))
    return {
        "episodes": await engine.episodes(),
        "episodes, a page at a time": await _walk(
            lambda cursor: engine.episodes(cursor=cursor, limit=1),
            lambda page: page.next_cursor,
        ),
        "episode": await engine.episode_chunk(_address(_OWN)),
        "shared episode": await engine.episode_chunk(_address(_SHARED)),
        "beliefs": await engine.beliefs(),
        "beliefs and episodes": await engine.beliefs(
            kinds=[MemoryKind.MEMORY, MemoryKind.EPISODIC]
        ),
        "beliefs, one at a time": [await engine.beliefs(limit=1, offset=n) for n in range(5)],
        "asserted": await engine.beliefs(bands=[BeliefBand.ASSERTED]),
        "belief": await engine.belief("m-own"),
        "shared belief": await engine.belief("m-shared"),
        "episode as a belief": await engine.belief(_address(_OWN)),
        "stories": await engine.stories(),
        "stories, a page at a time": await _walk(
            lambda cursor: engine.stories(cursor=cursor, limit=1),
            lambda page: page.next_cursor,
        ),
        "story": await engine.story(trip),
        "around": await engine.story(around),
        "hall": await engine.story(hall),
        "story log": await engine.story_log(trip),
        "story summary": await engine.story_summary(trip),
        "story standing": await engine.story_standing(trip),
        "around standing": await engine.story_standing(around),
        "hall standing": await engine.story_standing(hall),
        "activation's stories": await engine.activation_stories(_OWN),
        "open activation's stories": await engine.activation_stories(_OPEN),
        "pending candidates": await engine.pending_candidates(),
    }


def _counted(logs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [one for one in logs if one["event"] == "sight_counted"]


# --- seeing gives back what it gives back today (§4:1) ---------------------------------


@_MODES
async def test_every_seeing_act_gives_back_what_it_gave_back_over_the_stores_unbound(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§3:5's last sentence: with one person, the owner's sight from none withholds only a
    record with no home, so seeing gives back what it gives back today."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    with capture_logs() as logs:
        seen = await _reads(bound)

    assert seen == await _reads(today)
    assert _counted(logs) == [], "the owner's sight writes no count, in either build"
    # The seed is seen whole: nothing of the owner's or the shared things' is withheld.
    beliefs = seen["beliefs"]
    assert isinstance(beliefs, tuple)
    assert {one.id for one in beliefs} == {"m-own", "m-shared", "m-placed"}
    assert seen["pending candidates"] != ()


@_MODES
async def test_records_of_another_home_and_rows_with_no_home_change_no_seeing_act(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:1, §4:2: none is given back, counted, paged past or named; every act answers as
    over the stores holding the owner's and the shared things' alone."""
    clean = await _opened(mode)
    crowded = await _opened(mode, others=True)
    worlds.extend((clean, crowded))

    with capture_logs() as logs:
        seen = await _reads(crowded)

    assert seen == await _reads(clean)
    assert _counted(logs) == []


@_MODES
async def test_an_act_naming_a_record_of_another_home_is_answered_as_for_one_never_written(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:2, ADR-0383 §8:2: by id, each is none, as an id never written is."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    engine = world.engine

    with capture_logs() as logs:
        for one in (_SAM, _NO_HOME, _NEVER):
            name = one.removeprefix("a-")
            named = world.named.get(name, _NEVER_STORY)
            assert await engine.episode_chunk(_address(one)) is None
            assert await engine.belief(_address(one)) is None
            assert await engine.belief(f"m-{name}") is None
            assert await engine.story(named) is None
            assert await engine.story_log(named) is None
            assert await engine.story_summary(named) is None
            assert await engine.story_standing(named) is None
            assert await engine.activation_stories(one) == ()

    assert _counted(logs) == []


#: The activation whose remember call a memory rests on, and the request a memory's
#: confirmation names: each read from the plan store when the memory is shown.
_REMEMBERED: Final = "a-remember"
_REQUEST: Final = "q-confirmed"


async def _seed_the_supports(world: _World, *, asked_for: str) -> None:
    """A memory resting on a remember call its effect record holds, and one resting on a
    confirmation of a request written for ``asked_for``; their episodes are the owner's."""
    # A round whose remember call states the memory; its effect record names the round.
    subject = PendingCandidatesSubject(
        engine=world.engine, memory=cast("Any", world.memory), plans=cast("Any", world.plans)
    )
    call = ProposedCall(
        call_id="c1", name="remember_fact", arguments={"statement": "prefers the quiet car"}
    )
    at = NOW - timedelta(hours=2)
    await _hold(
        subject,
        _REMEMBERED,
        at,
        PlanningRound(id=f"round:{_REMEMBERED}", recorded_at=at, calls=(call,)),
    )
    remembered = ActivationEffect(
        home=RecordHome.owners(),
        id=f"effect:{_REMEMBERED}:1",
        activation_id=_REMEMBERED,
        round=f"round:{_REMEMBERED}",
        capability="remember_fact",
        values_digest="1" * 64,
        decision_id=f"decision:{_REMEMBERED}",
        claimed_at=at,
    )
    await world.plans.claim_activation_effect(remembered, match=None)
    await world.plans.finish_activation_effect(remembered.id, ToolOutcome.SUCCEEDED)
    await world.memory.add(
        memory(
            "m-remembered",
            "prefers the quiet car",
            remembered_support(_address(_REMEMBERED), effect=f"effect:{_REMEMBERED}:1"),
        )
    )
    values: dict[str, FrozenJson] = {
        "fact": "likes jazz",
        "why": "they said so",
        "rests_on_this_stimulus": True,
        "episode": _address(_OWN),
        "rests_on_outside_content": False,
    }
    request = ApprovalRequest(
        id=_REQUEST,
        person=asked_for,
        activation_id="a-ask",
        round="round:a-ask",
        call=RequestedCall(tool=REMEMBER_CANDIDATE, values=values),
        why="You told me you like jazz.",
        written_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=1),
    )
    asked = ActivationEffect(
        home=RecordHome.owners(),
        id=f"effect:{_REQUEST}",
        activation_id="a-ask",
        round="round:a-ask",
        capability="request_approval",
        values_digest="0" * 64,
        decision_id=f"decision:{_REQUEST}",
        claimed_at=NOW - timedelta(hours=1),
        request=_REQUEST,
    )
    await world.plans.write_approval_request(request, asked, match=None)
    confirmed = MemorySupport(
        points_at=ConfirmationPart(
            episode=_address(_OWN), asking_activation="a-ask", request=_REQUEST, ran_in="a-ask"
        ),
        origin=SupportOrigin.CONFIRMATION,
        direction=SupportDirection.FOR,
        backs_as_worded=True,
        how_sure=ReadingCertainty.SURE,
        when=NOW,
        added_at=NOW,
        added_by=MemoryWriterName.REMEMBER,
    )
    await world.memory.add(memory("m-confirmed", "likes jazz", confirmed))


async def _beside_the_episodes(world: _World) -> dict[str, object]:
    """What the acts that read the plan store beside an episode show of it."""
    engine = world.engine
    remembered = await engine.belief("m-remembered")
    confirmed = await engine.belief("m-confirmed")
    standing = await engine.story_standing(world.named["trip"])
    assert remembered is not None
    assert confirmed is not None
    assert standing is not None
    return {
        "remembered": [one.content for one in remembered.supports],
        "remembered gone": remembered.supports_gone,
        "confirmed": [one.content for one in confirmed.supports],
        "done": [one.activation_id for one in standing.done],
        "shown": [one.activation_id for one in standing.recent],
        "pending": [one.fact for one in await engine.pending_candidates()],
        "episode held": await engine.belief(_address(_REMEMBERED)) is not None,
    }


@_MODES
@pytest.mark.parametrize("home", [_SAMS, _NOBODYS], ids=["another person's", "no home"])
async def test_a_plan_record_the_sight_does_not_see_is_not_shown_beside_an_episode_it_sees(
    mode: SightMode, home: tuple[str | None, str | None], worlds: list[_World]
) -> None:
    """§3:1, §4:2: the effect records and the request an act reads beside an episode are
    read through the plan store bound to the owner's sight, apart from the episode. With
    the episodes the owner's, an effect record or a request the sight does not see is
    not there: a support resting on it is gone, where the matter stands lists nothing
    done for it, and the candidate it showed done is no longer pending."""
    clean = await _opened(mode)
    await _seed_the_supports(clean, asked_for=OWNER_PERSON_ID)
    crowded = await _opened(mode)
    await _seed_the_supports(crowded, asked_for="person:sam" if home == _SAMS else OWNER_PERSON_ID)
    crowded.alter(
        "plans",
        "activation_effects",
        "id",
        [f"effect:{_OWN}", f"effect:{_REMEMBERED}:1", "effect:a-candidate:1"],
        home,
    )
    if home == _NOBODYS:
        crowded.alter("plans", "activation_effects", "id", [f"effect:{_REQUEST}"], home)
    worlds.extend((clean, crowded))

    shown = await _beside_the_episodes(clean)
    with capture_logs() as logs:
        hidden = await _beside_the_episodes(crowded)

    assert {key: shown[key] for key in ("remembered", "confirmed", "done", "pending")} == {
        "remembered": ["prefers the quiet car"],
        "confirmed": ["likes jazz"],
        "done": [_OWN],
        "pending": ["prefers aisle seats"],
    }
    assert shown["remembered gone"] is False
    assert shown["episode held"] is True
    # The episodes stay in sight, so no memory reads as resting on none that resolves
    # (ADR-0328 §15:7); what rests on the unseen plan records alone reads as gone.
    assert hidden == shown | {
        "remembered": [None],
        "confirmed": [None] if home == _SAMS else ["likes jazz"],
        "done": [],
        "pending": [],
    }
    assert _counted(logs) == []


# --- writing writes what it writes today (§3:1, §5) ------------------------------------


async def _writes(world: _World) -> list[object]:
    """Every write act of this lane over the owner's records, in one order, each answer."""
    engine = world.engine
    trip, hall, around = (world.named[name] for name in ("trip", "hall", "around"))
    answers: list[object] = [
        await engine.create_story([activation(_OWN)]),
        await engine.create_story([activation(_NEVER)]),
        await engine.create_story([activation(_SHARED)]),
        await engine.link_story(trip, [activation("a-candidate")]),
        await engine.link_story(hall, [activation(_OWN)]),
        await engine.unlink_story(trip, [activation("a-candidate")]),
        await engine.add_story_note(trip, "Pack the stove."),
        await engine.split_story(trip, [activation(_OPEN)]),
        await engine.move_story_members(trip, around, [activation(_OWN)]),
        await engine.merge_stories(around, trip),
        await engine.guard("m-own"),
        await engine.unguard("m-shared"),
        await engine.guard("m-own"),
        await engine.forget("m-placed"),
        await engine.forget(_NEVER_MEMORY),
        await engine.stop_activation(_OWN),
        await engine.stop_activation(_OPEN),
        await engine.stop_activation(_NEVER),
    ]
    return answers


@_MODES
async def test_every_write_act_writes_what_it_wrote_over_the_stores_unbound(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:2: each delete and each story write acts on the owner's records as before, and
    leaves the store files as they were left before the sight."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    with capture_logs() as logs:
        answers = await _writes(bound)

    assert answers == await _writes(today)
    assert bound.rows() == today.rows()
    assert await _reads(bound) == await _reads(today)
    assert _counted(logs) == []
    assert answers[13] is True, "the owner's memory is forgotten"
    assert answers[15] is ActivationStop.ALREADY_ENDED


def _as_never(value: object, *named: str) -> str:
    """``value`` printed with each of ``named`` written as the id never written."""
    text = repr(value)
    for one in named:
        text = text.replace(one, "<never>")
    return text


@_MODES
async def test_a_write_naming_a_record_of_another_home_changes_nothing_and_answers_as_never(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:3, ADR-0383 §7:5, §8:2: a delete, a placement, a story write and a stop naming a
    record the owner's sight does not see each answer exactly as naming one never written
    does, and no row of any store changes."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    engine = world.engine
    trip = world.named["trip"]
    before = world.rows()

    with capture_logs() as logs:
        for one in (_SAM, _NO_HOME):
            name = one.removeprefix("a-")
            unseen = world.named[name]
            assert await engine.forget(f"m-{name}") is False
            assert await engine.forget(_address(one)) is False
            assert await engine.guard(f"m-{name}") is None
            assert await engine.unguard(_address(one)) is None
            assert await engine.stop_activation(one) is ActivationStop.NO_SUCH_ACTIVATION
            for act in (
                lambda story_id: engine.link_story(story_id, [activation(_OPEN)]),
                lambda story_id: engine.unlink_story(story_id, [activation(_OWN)]),
                lambda story_id: engine.add_story_note(story_id, "Pack the stove."),
                lambda story_id: engine.split_story(story_id, [activation(_OWN)]),
                lambda story_id: engine.move_story_members(story_id, trip, [activation(_OWN)]),
                lambda story_id: engine.move_story_members(trip, story_id, [activation(_OWN)]),
                lambda story_id: engine.merge_stories(story_id, trip),
                lambda story_id: engine.merge_stories(trip, story_id),
            ):
                assert _as_never(await act(unseen), unseen) == _as_never(
                    await act(_NEVER_STORY), _NEVER_STORY
                )
            for members in ([activation(one)], [activation(_OWN), activation(one)]):
                created = await engine.create_story(members)
                linked = await engine.link_story(trip, members)
                never = [activation(_NEVER) if m == activation(one) else m for m in members]
                assert _as_never(created, one) == _as_never(
                    await engine.create_story(never), _NEVER
                )
                assert _as_never(linked, one) == _as_never(
                    await engine.link_story(trip, never), _NEVER
                )

    assert world.rows() == before
    assert _counted(logs) == []


# --- a work's reads still count (ADR-0383 §11:1) ---------------------------------------


async def test_a_works_read_of_the_store_the_owners_acts_read_still_counts(
    worlds: list[_World],
) -> None:
    """§3:5 reaches the owner's sight alone: the counting store the owner's acts read
    through withholding still answers a work's sight as unbound, writing its count."""
    world = await _opened(SightMode.COUNT)
    worlds.append(world)
    await _reads(world)
    await _writes(world)

    work = sight_of(at=NOW)
    with capture_logs() as logs:
        held = await world.memory.bound(work).get(_address(_OWN))
        listed = await world.stories.bound(work).stories()

    assert held is not None, "counting answers a work as the unbound store does"
    assert world.named["trip"] in {one.story_id for one in listed.stories}
    assert {(one["store"], one["member"], one["reader"]) for one in _counted(logs)} == {
        ("memory", "get", "work"),
        ("stories", "stories", "work"),
    }
