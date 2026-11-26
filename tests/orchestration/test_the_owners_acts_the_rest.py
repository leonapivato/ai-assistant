"""The owner's acts on the profile, notifications, approvals and tasks read by the owner's sight.

Milestone 22's B10f (ADR-0385 §3 to §5). Every member of ``AssistantEngine`` that reads or
writes the person-model store, the notification store or the plan store's approval
requests, and the memory store where such an act reads it, does so through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the owner's sight
from none, made for each call (§3:1, §3:3, §4:1, §5:2); and the Task Manager's operations
from outside read and write through the stores bound to the sight they are handed. Over
the production SQLite stores, built to count and built to withhold:

- where every record is the owner's or the shared things', each act gives back and writes
  exactly what it gives back and writes over the same stores unbound, as before the sight;
- another person's records, and rows with no home, beside them change no act's answer:
  none gives one back, counts it, pages past it or names it, and an act naming one is
  answered as for one never written, writing nothing (§4:2, §5:3, ADR-0383 §8:2);
- no owner's act writes a ``sight_counted`` event in either build (§3:5), while a work's
  read of the very same store still writes its count (ADR-0383 §11:1).

A record of another home cannot be written through a store in this milestone (ADR-0383
§2:3), so each is written as the owner's and then altered in place, as a row altered
outside the store is; another person in the person-model store is a row added beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, cast
from zoneinfo import ZoneInfo

import pytest
from approvals_panel_contract import APPROVALS_AT, hold_asking_episode, hold_request
from sight_support import holder, sight_of
from structlog.testing import capture_logs
from task_support import (
    CHAT,
    LIMITS,
    LINE,
    OWNERS_SIGHT,
    activation,
    message,
    schedule_episode,
    write_task,
)
from test_engine import (
    RETENTION,
    TRACE_RETENTION,
    _connection_operations,
    _grant_operations,
)

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ApprovalChoice,
    ClassReach,
    DataTier,
    DueAt,
    NotificationCandidate,
    NotificationPreferences,
    NotificationReach,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    ProposedSuggestion,
    RecordHome,
    SightMode,
    SuggestionKind,
    ToolOutcome,
)
from ai_assistant.memory.notification_store import SqliteNotificationStore
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.orchestration.engine import Engine
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.task_manager import TaskManager, TaskManagerLimits
from ai_assistant.orchestration.task_rules import PersonZones
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeConversationStore,
    FakeMemoryStore,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeSourceReadTrail,
    FakeTraceRetention,
    FakeTraceSink,
)
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator, Mapping, Sequence

    from ai_assistant.core.protocols import (
        MemoryStore,
        NotificationStore,
        PersonModelStore,
        PlanStore,
    )
    from ai_assistant.core.types import Sight

#: The instant every store and the engine are clocked at.
NOW: Final = APPROVALS_AT

_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda one: one.value)

#: Another person, and the two homes a crowded store's altered rows carry.
_SAM: Final = "person:sam"
_SAMS: Final = ("person", _SAM)
_NOBODYS: Final = (None, None)

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)


class _AsToday(BoundStores):
    """The holder as the owner's acts read through it before the owner's sight: unbound.

    Handed to an engine and to its person blocks over stores seeded alike, it gives every
    act the stores as they are, whatever sight it is asked for, which is how each act read
    before ADR-0385.
    """

    def memory(self, sight: Sight) -> MemoryStore:
        del sight
        return self._memory

    def people(self, sight: Sight) -> PersonModelStore:
        del sight
        assert self._people is not None
        return self._people

    def plans(self, sight: Sight) -> PlanStore:
        del sight
        assert self._plans is not None
        return self._plans

    def notifications(self, sight: Sight) -> NotificationStore:
        del sight
        assert self._notifications is not None
        return self._notifications


@dataclass
class _World:
    """The four SQLite stores, built in one mode, an outbox, and an engine over them."""

    memory: SqliteMemoryStore
    plans: SqlitePlanStore
    notifications: SqliteNotificationStore
    people: SqlitePersonModelStore
    outbox: FakeNotificationOutbox
    engine: Engine
    #: The notification ids the seed made, by name.
    named: dict[str, str]

    def rows(self) -> dict[str, list[tuple[object, ...]]]:
        """Every row the stores' record tables hold, read beside the stores."""
        return {
            "records": _dump(self.memory._conn, "records"),
            "notifications": _dump(self.notifications._conn, "notifications"),
            "preferences": _dump(self.notifications._conn, "notification_preferences"),
            "requests": _dump(self.plans._conn, "approval_requests"),
            "tasks": _dump(self.plans._conn, "scheduled_tasks"),
            **{
                table: _dump(self.people._conn, table)
                for table in ("persons", "fields", "changes", "pins", "marks", "suggestions")
            },
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

    def close(self) -> None:
        for store in (self.memory, self.plans, self.notifications, self.people):
            store.close()


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    return sorted(
        (tuple(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()),  # noqa: S608 — the case's own names
        key=repr,
    )


def _world(mode: SightMode, *, as_today: bool = False) -> _World:
    ids = count(1)
    memory_store = SqliteMemoryStore(
        path=":memory:",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=FakeTraceSink(),
        now=lambda: NOW,
        sight_mode=mode,
    )
    plans = SqlitePlanStore(path=":memory:", now=lambda: NOW, sight_mode=mode)
    notifications = SqliteNotificationStore(
        path=":memory:",
        traces_sink=FakeTraceSink(),
        now=lambda: NOW,
        new_id=lambda: f"note-{next(ids):03d}",
        sight_mode=mode,
    )
    people = SqlitePersonModelStore(
        path=":memory:",
        field_chars=200,
        now=lambda: NOW,
        new_id=lambda kind: f"{kind}-{next(ids):03d}",
        sight_mode=mode,
    )
    kind = _AsToday if as_today else BoundStores
    stores = kind(memory=memory_store, plans=plans, people=people, notifications=notifications)
    blocks = PersonBlocks(store=people, memory=memory_store, stores=stores)
    outbox = FakeNotificationOutbox(records=notifications, now=lambda: NOW)
    trail = FakeAuditTrail()
    engine = Engine(
        chat_reader=False,
        grant_operations=_grant_operations(),
        connection_operations=_connection_operations(),
        plans=plans,
        trail=trail,
        spend=trail,
        reads=FakeSourceReadTrail(),
        memory=memory_store,
        traces=FakeTraceRetention(),
        trace_sink=FakeTraceSink(),
        trace_retention=TRACE_RETENTION,
        conversations=ConversationLifecycle(
            conversations=FakeConversationStore(now=lambda: NOW),
            memory=memory_store,
            retention=RETENTION,
            now=lambda: NOW,
        ),
        notifications=notifications,
        notification_policy=FakeNotificationPolicy(),
        notification_outbox=outbox,
        person_blocks=blocks,
        stores=stores,
        now=lambda: NOW,
    )
    return _World(memory_store, plans, notifications, people, outbox, engine, {})


def _candidate(key: str) -> NotificationCandidate:
    return NotificationCandidate(
        candidate_key=key,
        producer="a-producer",
        notification_class="calendar",
        summary=f"something about {key}",
        noticed_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=2),
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


async def _held(world: _World, key: str, home: RecordHome) -> str:
    """A held notification of ``home``'s, offered to the outbox, by its id."""
    ruled = await world.notifications.admit(
        _candidate(key), home=home, policy=FakeNotificationPolicy()
    )
    assert ruled.notification_id is not None
    await world.outbox.offer(_candidate(key))
    world.named[key] = ruled.notification_id
    return ruled.notification_id


async def _seed_the_owners(world: _World) -> None:
    """The owner's profile, pins, mark and suggestions over the owner's and the shared
    things' memories; their held notifications; and the owner's approval requests."""
    shared = RecordHome.shared()
    await hold_asking_episode(cast("Any", world.memory), "act-ask")
    staged = FakeMemoryStore(now=lambda: NOW)
    await hold_asking_episode(staged, "act-shared")
    episode = await staged.get("activation:act-shared")
    assert episode is not None
    await world.memory.add(episode.model_copy(update={"home": shared}))
    for one, words, home in (
        ("m-own", "they like the window seat", RecordHome.owners()),
        ("m-pinned", "they are vegetarian", RecordHome.owners()),
        ("m-shared", "the hall light is on a timer", shared),
        ("m-suggested", "they cycle to work", RecordHome.owners()),
    ):
        rests_on = "activation:act-shared" if home == shared else "activation:act-ask"
        await world.memory.add(memory(one, words, said_support(rests_on), home=home))
    people = world.people
    await people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Leo", act=_PANEL)
    await people.add_pin(OWNER_PERSON_ID, "m-pinned", act=_PANEL)
    await people.add_style_mark(OWNER_PERSON_ID, "m-own")
    await people.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(
            kind=SuggestionKind.PIN, memory_id="m-suggested", episode_id="activation:act-ask"
        ),
    )
    await _held(world, "k-own", RecordHome.owners())
    await _held(world, "k-shared", shared)
    await hold_request(cast("Any", world.plans), "approval:own", activation="act-ask")
    await hold_request(
        cast("Any", world.plans), "approval:old", activation="act-ask", ago=timedelta(hours=30)
    )


async def _seed_the_others(world: _World) -> None:
    """Another person's records, and rows with no home, after the owner's, so they are the
    newest of every listing and a page must pass over them.

    Sam, in the person-model store, with a field set; a memory of Sam's and one of no
    home, each pinned and marked by the owner before it was altered; a held notification
    of each, offered to the outbox; and an approval request of Sam's, whose asking episode
    is Sam's.
    """
    conn = world.people._conn
    conn.execute("INSERT INTO persons(id, role, created_at) VALUES (?, 'owner', 0)", (_SAM,))
    conn.commit()
    await world.people.set_field(_SAM, ProfileField.NAME, "Sam", act=_PANEL)
    for one, home in (("m-sam", _SAMS), ("m-nobody", _NOBODYS)):
        await world.memory.add(memory(one, f"about {one}", said_support("activation:act-ask")))
        await world.people.add_pin(OWNER_PERSON_ID, one, act=_PANEL)
        await world.people.add_style_mark(OWNER_PERSON_ID, one)
        world.alter("memory", "records", "id", [one], home)
    for key, home in (("k-sam", _SAMS), ("k-nobody", _NOBODYS)):
        held = await _held(world, key, RecordHome.owners())
        world.alter("notifications", "notifications", "id", [held], home)
    await hold_asking_episode(cast("Any", world.memory), "act-sam")
    world.alter("memory", "records", "id", ["activation:act-sam"], _SAMS)
    await hold_request(
        cast("Any", world.plans),
        "approval:sam",
        activation="act-sam",
        person=_SAM,
        ago=timedelta(minutes=10),
    )


async def _opened(mode: SightMode, *, others: bool = False, as_today: bool = False) -> _World:
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
        one.close()


async def _reads(world: _World) -> dict[str, object]:
    """What each seeing act of this lane gives back over the owner's records (§4:1)."""
    engine = world.engine
    return {
        "person model": await engine.person_model(OWNER_PERSON_ID),
        "person model, a page at a time": [
            await engine.person_model(OWNER_PERSON_ID, limit=1, offset=n) for n in range(4)
        ],
        "profile changes": await engine.profile_changes(OWNER_PERSON_ID),
        "notifications": await engine.notifications(),
        "notifications, one at a time": [
            await engine.notifications(limit=1, offset=n) for n in range(4)
        ],
        "preferences": await engine.notification_preferences(),
        "approvals": await engine.approvals(),
        "approvals, one each": await engine.approvals(limit=1),
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
    view = seen["person model"]
    assert view is not None
    assert [one.memory_id for one in view.kept] == ["m-pinned", "m-own"]  # type: ignore[attr-defined]
    assert len(seen["notifications"]) == 2  # type: ignore[arg-type]
    assert seen["approvals"].pending_total == 1  # type: ignore[attr-defined]


@_MODES
async def test_records_of_another_home_and_rows_with_no_home_change_no_seeing_act(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:1, §4:2: none is given back, counted, paged past or named; a pin or a mark on a
    memory the sight does not see is shown nowhere, as one on a memory not held."""
    clean = await _opened(mode)
    crowded = await _opened(mode, others=True)
    worlds.extend((clean, crowded))

    with capture_logs() as logs:
        seen = await _reads(crowded)

    assert seen == await _reads(clean)
    assert _counted(logs) == []


@_MODES
async def test_an_act_naming_another_persons_model_answers_as_for_one_never_written(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:2, ADR-0383 §8:2: Sam's model, held beside the owner's, reads as no person."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    engine = world.engine

    with capture_logs() as logs:
        for person in (_SAM, "person:never"):
            assert await engine.person_model(person) is None
            assert await engine.profile_changes(person) == ()

    assert _counted(logs) == []


# --- writing writes what it writes today (§3:1, §5) ------------------------------------


async def _writes(world: _World) -> list[object]:
    """Every write act of this lane over the owner's records, in one order, each answer."""
    engine = world.engine
    view = await engine.person_model(OWNER_PERSON_ID)
    assert view is not None
    (mark,) = view.style_marks
    (suggestion,) = view.suggestions
    return [
        await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.LANGUAGE, value="en"),
        await engine.set_profile_field(OWNER_PERSON_ID, field=ProfileField.NAME),
        await engine.pin_memory(OWNER_PERSON_ID, memory_id="m-shared"),
        await engine.pin_memory(OWNER_PERSON_ID, memory_id="m-own"),
        await engine.unpin_memory(OWNER_PERSON_ID, memory_id="m-pinned"),
        await engine.remove_style_mark(OWNER_PERSON_ID, mark_id=mark.mark.id),
        await engine.accept_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=suggestion.suggestion.id
        ),
        await engine.dismiss_person_suggestion(
            OWNER_PERSON_ID, suggestion_id=suggestion.suggestion.id
        ),
        await engine.dismiss_notification(world.named["k-own"]),
        await engine.forget_notification(world.named["k-shared"]),
        await engine.forget_notification("note-never"),
        await engine.set_notification_preferences(
            NotificationPreferences(
                reaches=(ClassReach(notification_class="calendar", reach=NotificationReach.OFF),)
            )
        ),
        await engine.tap_approval("approval:own", choice=ApprovalChoice.APPROVE),
        await engine.tap_approval("approval:never", choice=ApprovalChoice.APPROVE),
    ]


@_MODES
async def test_every_write_act_writes_what_it_wrote_over_the_stores_unbound(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:2: each write acts on the owner's records as before, and leaves the store files
    and the outbox as they were left before the sight."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    with capture_logs() as logs:
        answers = await _writes(bound)

    assert answers == await _writes(today)
    assert bound.rows() == today.rows()
    assert await _reads(bound) == await _reads(today)
    assert _counted(logs) == []
    assert answers[8] is True, "the owner's notification is dismissed"
    assert answers[9] is True, "the shared things' notification is destroyed"
    assert await bound.engine.next_notification(budget=timedelta(0)) is None


@_MODES
async def test_a_write_naming_a_record_of_another_home_changes_nothing_and_answers_as_never(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:3, ADR-0383 §7:5, §8:2: a field, a pin, an unpin, a dismissal, a deletion and a
    tap naming a person, a memory, a notification or a request the owner's sight does not
    see each answer exactly as naming one never written, and no row changes. The outbox
    entry of an unseen notification is neither withdrawn nor dismissed."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    engine = world.engine
    before = world.rows()
    entries = dict(world.outbox._entries)

    with capture_logs() as logs:
        for person in (_SAM,):
            assert await engine.set_profile_field(
                person, field=ProfileField.NAME, value="Sammy"
            ) == await engine.set_profile_field(
                "person:never", field=ProfileField.NAME, value="Sammy"
            )
            assert await engine.pin_memory(person, memory_id="m-own") == await engine.pin_memory(
                "person:never", memory_id="m-own"
            )
        for unseen in ("m-sam", "m-nobody"):
            assert await engine.pin_memory(
                OWNER_PERSON_ID, memory_id=unseen
            ) == await engine.pin_memory(OWNER_PERSON_ID, memory_id="m-never")
        for key in ("k-sam", "k-nobody"):
            assert await engine.dismiss_notification(world.named[key]) is False
            assert await engine.forget_notification(world.named[key]) is False
        unseen_tap = await engine.tap_approval("approval:sam", choice=ApprovalChoice.APPROVE)
        never_tap = await engine.tap_approval("approval:never", choice=ApprovalChoice.APPROVE)

    assert unseen_tap == never_tap
    assert world.rows() == before
    assert world.outbox._entries == entries
    assert _counted(logs) == []


@_MODES
async def test_unpinning_a_memory_the_sight_does_not_see_removes_the_owners_pin_as_if_forgotten(
    mode: SightMode, worlds: list[_World]
) -> None:
    """ADR-0338 §4:7, §4:10: the owner's pin is the owner's own record, naming a memory id.
    A memory the sight does not see is one the store does not hold, so its pin is shown
    nowhere and is removed by the id it names, as a pin on a forgotten memory is; the
    memory's row is not read into the answer and does not change."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    forgotten = await _opened(mode)
    worlds.append(forgotten)
    await forgotten.people.add_pin(OWNER_PERSON_ID, "m-own", act=_PANEL)
    await forgotten.memory.delete("m-own")
    records = world.rows()["records"]

    with capture_logs() as logs:
        unseen = await world.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m-sam")
        gone = await forgotten.engine.unpin_memory(OWNER_PERSON_ID, memory_id="m-own")

    assert unseen == gone
    assert world.rows()["records"] == records
    view = await world.engine.person_model(OWNER_PERSON_ID)
    assert view is not None
    assert "m-sam" not in {one.memory_id for one in view.kept}
    assert _counted(logs) == []


# --- the Task Manager's operations from outside (ADR-0350 §10, ADR-0385 §3:1) ----------


@dataclass
class _Tasks:
    manager: TaskManager
    plans: SqlitePlanStore
    memory: SqliteMemoryStore
    people: SqlitePersonModelStore

    def rows(self) -> list[tuple[object, ...]]:
        return _dump(self.plans._conn, "scheduled_tasks")

    def alter(self, store: str, table: str, ids: Sequence[str], home: Any) -> None:
        """Set the home columns of ``ids``' rows, outside the store (ADR-0383 §5:3)."""
        conn: sqlite3.Connection = getattr(self, store)._conn
        kind, home_id = home
        marks = ", ".join("?" for _ in ids)
        conn.execute(
            f"UPDATE {table} SET home_kind = ?, home_id = ? WHERE id IN ({marks})",  # noqa: S608 — the case's own names
            (kind, home_id, *ids),
        )
        conn.commit()

    def close(self) -> None:
        for store in (self.plans, self.memory, self.people):
            store.close()


#: A listing bound of two, so an unseen episode that took a slot would push one out.
_TWO: Final = TaskManagerLimits(chain_limit=10, pending_limit=50, listing_bound=2)


def _tasks(mode: SightMode, *, limits: TaskManagerLimits = LIMITS) -> _Tasks:
    plans = SqlitePlanStore(path=":memory:", now=lambda: NOW, sight_mode=mode)
    memory_store = SqliteMemoryStore(
        path=":memory:",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=FakeTraceSink(),
        now=lambda: NOW,
        sight_mode=mode,
    )
    people = SqlitePersonModelStore(
        path=":memory:", field_chars=200, now=lambda: NOW, sight_mode=mode
    )
    stores = holder(plans=plans, memory=memory_store, people=people)
    manager = TaskManager(
        stores=stores,
        plans=plans,
        running=lambda: (),
        is_running=lambda _one: False,
        starting=lambda _one: False,
        wake=lambda: None,
        limits=limits,
        zones=PersonZones(default=ZoneInfo("UTC"), people=people, stores=stores),
        now=lambda: NOW,
    )
    return _Tasks(manager, plans, memory_store, people)


@pytest.fixture
async def task_worlds() -> AsyncIterator[list[_Tasks]]:
    """Every Task Manager world a case opens, closed after it."""
    opened: list[_Tasks] = []
    yield opened
    for one in opened:
        one.close()


@_MODES
async def test_the_operations_from_outside_read_and_write_by_the_sight_they_are_handed(
    mode: SightMode, task_worlds: list[_Tasks]
) -> None:
    """§3:1, §8:2: the owner's task is listed, replaced and cancelled; a task of another
    person's is listed nowhere, and replacing or cancelling it is answered as for one
    never written, with nothing changed; no count is written."""
    world = _tasks(mode)
    task_worlds.append(world)
    own = await write_task(world.plans, activation(), at=NOW)
    sams = await write_task(world.plans, activation(), at=NOW)
    world.plans._conn.execute("UPDATE scheduled_tasks SET person = ? WHERE id = ?", (_SAM, sams.id))
    world.plans._conn.commit()
    manager = world.manager
    when = DueAt(at=NOW + timedelta(hours=2))

    with capture_logs() as logs:
        listed = await manager.scheduled_outside_a_work(OWNER_PERSON_ID, sight=OWNERS_SIGHT)
        sams_listed = await manager.scheduled_outside_a_work(_SAM, sight=OWNERS_SIGHT)
        before = world.rows()
        unseen = await manager.cancel_outside_a_work(sams.id, sight=OWNERS_SIGHT)
        never = await manager.cancel_outside_a_work("task:never", sight=OWNERS_SIGHT)
        for task_id in (sams.id, "task:never"):
            with pytest.raises(PlanningError, match="holds no task"):
                await manager.replace(task_id, sight=OWNERS_SIGHT, instruction="x", when=when)
        unchanged = world.rows()
        replaced = await manager.replace(
            own.id, sight=OWNERS_SIGHT, instruction="the bins", when=when
        )
        assert replaced.task is not None
        cancelled = await manager.cancel_outside_a_work(replaced.task.id, sight=OWNERS_SIGHT)

    assert [one.task_id for one in listed] == [own.id]
    assert sams_listed == ()
    assert (unseen.task, unseen.reason) == (never.task, never.reason)
    assert unchanged == before
    assert cancelled.task is not None
    assert _counted(logs) == []


async def _ran_lately(world: _Tasks, *, others: bool) -> None:
    """Two of the owner's finished schedule episodes, the first with a message done into
    the chat; where ``others``, newer episodes of Sam's and of no home, each with a message
    done, and messages of Sam's and of no home beside the owner's first episode."""
    for one in ("a-ran-1", "a-ran-2"):
        await world.memory.add(schedule_episode(one))
    await message(world.plans, "a-ran-1", CHAT, outcome=ToolOutcome.SUCCEEDED)
    if not others:
        return
    # Each altered once every row is written: the helper reads its activation's effects
    # back unbound, which an altered row beside them would fail as corrupt.
    altered: list[tuple[str, str, str, Any]] = []
    for home in (_SAMS, _NOBODYS):
        beside = await message(world.plans, "a-ran-1", LINE, outcome=ToolOutcome.SUCCEEDED)
        altered.append(("plans", "activation_effects", beside.id, home))
    for one, home in (("a-ran-sam", _SAMS), ("a-ran-nobody", _NOBODYS)):
        await world.memory.add(schedule_episode(one))
        done = await message(world.plans, one, LINE, outcome=ToolOutcome.SUCCEEDED)
        altered.append(("memory", "records", f"activation:{one}", home))
        altered.append(("plans", "activation_effects", done.id, home))
    for store, table, record_id, home in altered:
        world.alter(store, table, [record_id], home)


@_MODES
async def test_what_ran_lately_shows_no_episode_or_message_the_sight_does_not_see(
    mode: SightMode, task_worlds: list[_Tasks]
) -> None:
    """§3:1, §4:2, ADR-0383 §8:1: the owner's finished schedule episodes are listed, each
    with where its messages went; a newer episode of another home takes no slot under the
    listing bound, and a message of another home beside the owner's episode is not said to
    have gone anywhere."""
    clean = _tasks(mode, limits=_TWO)
    crowded = _tasks(mode, limits=_TWO)
    task_worlds.extend((clean, crowded))
    await _ran_lately(clean, others=False)
    await _ran_lately(crowded, others=True)

    with capture_logs() as logs:
        shown = await crowded.manager.recent_outside_a_work(
            OWNER_PERSON_ID, sight=OWNERS_SIGHT, supply=None
        )

    assert shown == await clean.manager.recent_outside_a_work(
        OWNER_PERSON_ID, sight=OWNERS_SIGHT, supply=None
    )
    assert {one.activation_id: one.wrote_into for one in shown} == {
        "a-ran-1": (f"{CHAT.channel_type}:{CHAT.instance_id}",),
        "a-ran-2": (),
    }
    assert _counted(logs) == []


# --- a work's reads still count (ADR-0383 §11:1) ---------------------------------------


async def test_a_works_read_of_the_stores_the_owners_acts_read_still_counts(
    worlds: list[_World],
) -> None:
    """§3:5 reaches the owner's sight alone: the counting stores the owner's acts read
    through withholding still answer a work's sight as unbound, writing their counts."""
    world = await _opened(SightMode.COUNT)
    worlds.append(world)
    await _reads(world)

    work = sight_of(at=NOW)
    with capture_logs() as logs:
        held = await world.notifications.bound(work).held(limit=10)
        person = await world.people.bound(work).read(OWNER_PERSON_ID)

    assert len(held) == 2, "counting answers a work as the unbound store does"
    assert person is not None
    assert {(one["store"], one["member"], one["reader"]) for one in _counted(logs)} == {
        ("notifications", "held", "work"),
        ("person_model", "read", "work"),
    }
