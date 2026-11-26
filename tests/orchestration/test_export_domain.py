"""``export_domain`` over the production stores, bound for real, in both builds (ADR-0385 §6).

Milestone 22's B10d. The engine exports one domain by reading each store's own export
through the store bound to the owner's sight from that domain (§6:3). Over the SQLite
memory, story, conversation, plan, person-model and notification stores, each built to
count and built to withhold:

- an export of the owner's domain holds every part of the owner's records and none of the
  shared things'; of the shared things, the reverse (§6:4);
- neither holds a record of another person's domain, a row with no home or a stop record,
  and each is exactly what it is over the same stores holding none of them (§6:5);
- a domain the stores hold nothing of is ``exported`` with every part empty (§6:7);
- another person's domain and a group's are refused ``not_offered``, and a malformed value
  with ``ValueError``, without asking the holder for any store (§2:2, §6:9);
- an export past the contract limit is ``OversizedValueError`` (§6:7);
- no export writes a ``sight_counted`` event, in either build (§3:5).

A record of another home cannot be written through a store in this milestone (ADR-0383
§2:3), so each is written as the owner's and then altered in place, as a row altered
outside the store is; another person in the person-model store is a row added beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from approvals_panel_contract import hold_request
from story_surface_contract import act, episode
from structlog.testing import capture_logs
from task_support import CHAT
from test_engine import (
    RETENTION,
    TRACE_RETENTION,
    _connection_operations,
    _grant_operations,
)

from ai_assistant.core.errors import OversizedValueError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationEffect,
    ChatDevice,
    DataTier,
    DeviceAccess,
    DomainExport,
    DomainExportResult,
    DueNow,
    NotificationCandidate,
    ObservationRecord,
    ObservationState,
    PersonActHow,
    PersonModelAct,
    ProfileField,
    RecordHome,
    RecordHomeKind,
    ScheduledTaskAuthor,
    SendOutcome,
    SightMode,
    StoryActor,
    Sureness,
    TaskSpawn,
    TaskWriteAnswer,
    ToolOutcome,
    UserMessage,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.notification_store import SqliteNotificationStore
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.memory.story_store import SqliteStoryStore
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.conversations import ConversationLifecycle
from ai_assistant.orchestration.engine import Engine
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.task_scheduler import SPAWN_CAPABILITY
from ai_assistant.planning.sqlite_store import SqlitePlanStore
from ai_assistant.testing import (
    FakeAuditTrail,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeSourceReadTrail,
    FakeTraceRetention,
    FakeTraceSink,
)
from ai_assistant.testing.memories import memory

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator, Sequence

    from ai_assistant.core.types import Sight

#: The instant every store and the engine are clocked at.
NOW: Final = datetime(2026, 11, 26, 12, tzinfo=UTC)

_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda one: one.value)

_OWNERS: Final = RecordHome.owners()
_SHARED: Final = RecordHome.shared()

#: Another person, and the two homes a crowded store's altered rows carry.
_SAM: Final = "person:sam"
_SAMS: Final = ("person", _SAM)
_NOBODYS: Final = (None, None)

_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)


class _Asked(BoundStores):
    """The holder, noting each store it is asked for, so a case proves none was read."""

    def __init__(self, **stores: Any) -> None:
        super().__init__(**stores)
        self.asked: list[str] = []

    def memory(self, sight: Sight) -> Any:
        self.asked.append("memory")
        return super().memory(sight)

    def stories(self, sight: Sight) -> Any:
        self.asked.append("stories")
        return super().stories(sight)

    def conversations(self, sight: Sight) -> Any:
        self.asked.append("conversations")
        return super().conversations(sight)

    def plans(self, sight: Sight) -> Any:
        self.asked.append("plans")
        return super().plans(sight)

    def people(self, sight: Sight) -> Any:
        self.asked.append("people")
        return super().people(sight)

    def notifications(self, sight: Sight) -> Any:
        self.asked.append("notifications")
        return super().notifications(sight)


@dataclass
class _World:
    """The six SQLite stores, built in one mode, and an engine over them."""

    memory: SqliteMemoryStore
    stories: SqliteStoryStore
    chat: SqliteConversationStore
    plans: SqlitePlanStore
    people: SqlitePersonModelStore
    notifications: SqliteNotificationStore
    holder: _Asked
    engine: Engine
    #: The conversation ids the store mints next, in order.
    ids: list[str]

    def alter(self, store: str, table: str, where: str, args: Sequence[object], home: Any) -> None:
        """Set the home columns of the rows ``where`` names, outside the store (§5:3)."""
        conn: sqlite3.Connection = getattr(self, store)._conn
        kind, home_id = home
        conn.execute(
            f"UPDATE {table} SET home_kind = ?, home_id = ? WHERE {where}",  # noqa: S608 — the case's own names
            (kind, home_id, *args),
        )
        conn.commit()

    def close(self) -> None:
        for store in (
            self.memory,
            self.stories,
            self.chat,
            self.plans,
            self.people,
            self.notifications,
        ):
            store.close()


def _world(mode: SightMode, *, limit: int | None = None) -> _World:
    ids = count(1)
    conversation_ids: list[str] = []
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
    chat = SqliteConversationStore(
        path=":memory:", now=lambda: NOW, new_id=lambda: conversation_ids.pop(0), sight_mode=mode
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
    holder = _Asked(
        memory=memory_store,
        stories=stories,
        conversations=chat,
        plans=plans,
        people=people,
        notifications=notifications,
    )
    trail = FakeAuditTrail()
    knobs: dict[str, Any] = {} if limit is None else {"max_payload_bytes": limit}
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
            conversations=chat, memory=memory_store, retention=RETENTION, now=lambda: NOW
        ),
        stories=stories,
        notifications=notifications,
        notification_policy=FakeNotificationPolicy(),
        notification_outbox=FakeNotificationOutbox(records=notifications, now=lambda: NOW),
        person_blocks=PersonBlocks(store=people, memory=memory_store, stores=holder),
        stores=holder,
        now=lambda: NOW,
        **knobs,
    )
    return _World(
        memory_store, stories, chat, plans, people, notifications, holder, engine, conversation_ids
    )


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


def _effect(name: str, home: RecordHome) -> ActivationEffect:
    return ActivationEffect(
        home=home,
        id=f"effect:{name}",
        activation_id=f"act-{name}",
        round=f"round:{name}",
        capability="book_table",
        values_digest="0" * 64,
        decision_id=f"decision:{name}",
        claimed_at=NOW - timedelta(minutes=5),
    )


async def _seed(world: _World, name: str, home: RecordHome) -> dict[str, str]:
    """One record of ``home`` in each part a home of its kind may hold, named by ``name``.

    A memory, a story, a conversation with one message, an effect record and an
    observation record, and a held notification. The ids each store minted, by part.
    """
    await world.memory.add(memory(f"m-{name}", f"about {name}", home=home))
    story = await world.stories.create([act(f"a-{name}")], home=home, actor=StoryActor.OWNER)
    assert story.story_id is not None
    world.ids.append(f"c-{name}")
    # A conversation started while the phone is among "my devices" has it as an end.
    await world.chat.set_my_devices([_PHONE])
    conversation = await world.chat.start(home=home)
    said = UserMessage(device_id="phone", message_id=f"u-{name}", text=f"hello from {name}")
    receipt = await world.chat.append_message(conversation.id, said.as_new_message(home=home))
    assert receipt.outcome is SendOutcome.RECORDED, receipt
    effect = _effect(name, home)
    await world.plans.claim_activation_effect(effect, match=None)
    await world.plans.finish_activation_effect(effect.id, ToolOutcome.SUCCEEDED)
    await world.plans.write_observation(
        ObservationRecord(
            home=home, episode=f"activation:act-{name}", state=ObservationState.PROCESSED
        ),
        expected_revision=0,
    )
    ruled = await world.notifications.admit(
        _candidate(f"k-{name}"), home=home, policy=FakeNotificationPolicy()
    )
    assert ruled.notification_id is not None
    return {
        "story": story.story_id,
        "conversation": conversation.id,
        "notification": ruled.notification_id,
    }


async def _seed_the_owners(world: _World) -> None:
    """The owner's records and the shared things', a task and a request of the owner's,
    the owner's profile, and a stop record, which no export holds."""
    await world.memory.add(episode("a-own"))
    await _seed(world, "own", _OWNERS)
    await _seed(world, "shared", _SHARED)
    written = await world.plans.write_scheduled_task(
        TaskSpawn(
            id="task:own",
            person=OWNER_PERSON_ID,
            author=ScheduledTaskAuthor.PERSON,
            author_person=OWNER_PERSON_ID,
            setting_level=Sureness.NORMAL,
            setting_connection=None,
            when=DueNow(),
            places=(),
            instruction="check the listings",
            set_in=CHAT,
            set_at=NOW,
        ),
        _effect("spawn", _OWNERS).model_copy(update={"capability": SPAWN_CAPABILITY}),
        match=None,
        replace_any=True,
        chain_limit=10,
        pending_limit=50,
    )
    assert written.answer is TaskWriteAnswer.WRITTEN, written
    await hold_request(cast("Any", world.plans), "approval:own", activation="act-own")
    await world.people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Leo", act=_PANEL)
    await world.plans.record_stop("act-stopped")


async def _seed_the_others(world: _World) -> None:
    """Records of Sam's domain and rows with no home, after the owner's.

    In each store with home columns, a record of each, altered in place; Sam in the
    person-model store, with a field set; and an approval request of Sam's.
    """
    for name, home in (("sam", _SAMS), ("nobody", _NOBODYS)):
        made = await _seed(world, name, _OWNERS)
        world.alter("memory", "records", "id = ?", [f"m-{name}"], home)
        world.alter("stories", "stories", "id = ?", [made["story"]], home)
        world.alter("chat", "conversations", "id = ?", [made["conversation"]], home)
        world.alter("chat", "messages", "conversation_id = ?", [made["conversation"]], home)
        world.alter("plans", "activation_effects", "id = ?", [f"effect:{name}"], home)
        world.alter("plans", "observations", "episode_id = ?", [f"activation:act-{name}"], home)
        world.alter("notifications", "notifications", "id = ?", [made["notification"]], home)
    conn = world.people._conn
    conn.execute("INSERT INTO persons(id, role, created_at) VALUES (?, 'owner', 0)", (_SAM,))
    conn.commit()
    await world.people.set_field(_SAM, ProfileField.NAME, "Sam", act=_PANEL)
    await hold_request(cast("Any", world.plans), "approval:sam", activation="act-sam", person=_SAM)
    # The helper writes the request's effect record in the owner's home; Sam's here.
    world.alter("plans", "activation_effects", "id = ?", ["effect:approval:sam"], _SAMS)


@pytest.fixture
async def worlds() -> AsyncIterator[list[_World]]:
    """Every world a case opens, closed after it."""
    opened: list[_World] = []
    yield opened
    for one in opened:
        one.close()


async def _opened(worlds: list[_World], mode: SightMode, *, others: bool = False) -> _World:
    world = _world(mode)
    worlds.append(world)
    await _seed_the_owners(world)
    if others:
        await _seed_the_others(world)
    return world


def _export(result: DomainExportResult, domain: RecordHome) -> DomainExport:
    assert result.export is not None, result
    assert result.export.domain == domain
    return result.export


def _held(export: DomainExport) -> dict[str, object]:
    """What each part holds, by the records' own ids and homes."""
    return {
        "memory": sorted(one.id for one in export.memory),
        "stories": [one.story.home for one in export.stories.stories],
        "story members": [
            entry.member.id for one in export.stories.stories for entry in one.members
        ],
        "conversations": [one.id for one in export.conversations.conversations],
        "messages": [one.text for one in export.conversations.messages],
        "stops": export.plans.stopped_activations,
        "effects": [one.id for one in export.plans.activation_effects],
        "observations": [one.episode for one in export.plans.observations],
        "tasks": [one.person for one in export.plans.scheduled_tasks],
        "requests": [one.id for one in export.plans.approval_requests],
        "persons": [one.id for one in export.person_model.persons],
        "profiles": [person for person, _ in export.person_model.profiles],
        "notifications": [one.candidate.candidate_key for one in export.notifications],
    }


def _counted(logs: Sequence[Any]) -> list[Any]:
    return [one for one in logs if one["event"] == "sight_counted"]


@_MODES
async def test_the_owners_domain_holds_every_part_of_the_owners_records_and_nothing_else(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§6:4, §6:5: the owner's records in every part; nothing of the shared things', of
    Sam's domain or of no home; no stop record; and no count event (§3:5)."""
    world = await _opened(worlds, mode, others=True)

    with capture_logs() as logs:
        export = _export(await world.engine.export_domain(_OWNERS), _OWNERS)

    assert _held(export) == {
        "memory": ["activation:a-own", "m-own"],
        "stories": [_OWNERS],
        "story members": ["a-own"],
        "conversations": ["c-own"],
        "messages": ["hello from own"],
        "stops": (),
        "effects": ["effect:own", "effect:spawn", "effect:approval:own"],
        "observations": ["activation:act-own"],
        "tasks": [OWNER_PERSON_ID],
        "requests": ["approval:own"],
        "persons": [OWNER_PERSON_ID],
        "profiles": [OWNER_PERSON_ID],
        "notifications": ["k-own"],
    }
    assert _counted(logs) == [], "the owner's sight writes no count, in either build"


@_MODES
async def test_the_shared_things_hold_theirs_and_nothing_of_the_owners(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§6:4, the reverse: no task, request or person, which are a person's domain's."""
    world = await _opened(worlds, mode, others=True)

    with capture_logs() as logs:
        export = _export(await world.engine.export_domain(_SHARED), _SHARED)

    assert _held(export) == {
        "memory": ["m-shared"],
        "stories": [_SHARED],
        "story members": ["a-shared"],
        "conversations": ["c-shared"],
        "messages": ["hello from shared"],
        "stops": (),
        "effects": ["effect:shared"],
        "observations": ["activation:act-shared"],
        "tasks": [],
        "requests": [],
        "persons": [],
        "profiles": [],
        "notifications": ["k-shared"],
    }
    assert _counted(logs) == []


@_MODES
@pytest.mark.parametrize("domain", [_OWNERS, _SHARED], ids=["owners", "shared"])
async def test_records_of_another_home_and_rows_with_no_home_change_no_export(
    mode: SightMode, domain: RecordHome, worlds: list[_World]
) -> None:
    """§6:5, ADR-0383 §5:3: the export over stores holding Sam's rows and rows with no
    home is exactly the export over the same stores holding none of them."""
    clean = await _opened(worlds, mode)
    crowded = await _opened(worlds, mode, others=True)

    assert await crowded.engine.export_domain(domain) == await clean.engine.export_domain(domain)


@_MODES
async def test_a_domain_the_stores_hold_nothing_of_is_exported_with_every_part_empty(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§6:7's last sentence, over the six stores freshly opened."""
    world = _world(mode)
    worlds.append(world)

    export = _export(await world.engine.export_domain(_SHARED), _SHARED)

    assert all(not held for held in _held(export).values())
    assert export.exported_at == NOW


@_MODES
@pytest.mark.parametrize(
    "domain",
    [RecordHome.person(_SAM), RecordHome.group("group:house"), RecordHome.group(OWNER_PERSON_ID)],
    ids=["sams", "a-group", "a-group-named-like-the-owner"],
)
async def test_another_persons_domain_and_a_groups_are_refused_with_no_store_read(
    mode: SightMode, domain: RecordHome, worlds: list[_World]
) -> None:
    """§2:2, §6:2: ``not_offered`` from the value alone; the holder is asked for nothing."""
    world = await _opened(worlds, mode, others=True)
    world.holder.asked.clear()

    result = await world.engine.export_domain(domain)

    assert result == DomainExportResult.not_offered()
    assert world.holder.asked == []


@pytest.mark.parametrize(
    "domain",
    [
        "shared",
        RecordHome.model_construct(kind="shared"),
        RecordHome.model_construct(kind=RecordHomeKind.SHARED, id="x"),
        RecordHome.model_construct(kind=RecordHomeKind.PERSON),
    ],
    ids=["text", "kind-as-text", "shared-with-an-id", "a-person-with-no-id"],
)
async def test_a_malformed_domain_is_refused_with_value_error_before_any_read(
    domain: object, worlds: list[_World]
) -> None:
    """§6:9: ``ValueError``, and the holder is asked for nothing."""
    world = await _opened(worlds, SightMode.COUNT)
    world.holder.asked.clear()

    with pytest.raises(ValueError, match="a domain is a record home"):
        await world.engine.export_domain(domain)  # type: ignore[arg-type]

    assert world.holder.asked == []


@_MODES
async def test_an_exported_domain_reads_each_store_once_through_the_holder(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§6:3: each part through the store bound by the holder, one after another."""
    world = await _opened(worlds, mode)
    world.holder.asked.clear()

    await world.engine.export_domain(_OWNERS)

    assert world.holder.asked == [
        "memory",
        "stories",
        "conversations",
        "plans",
        "people",
        "notifications",
    ]


@_MODES
async def test_an_export_past_the_frame_limit_is_refused_whole(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§6:7: ``OversizedValueError``, never a part; the other domain still fits."""
    world = _world(mode, limit=16 * 1024)
    worlds.append(world)
    await _seed_the_owners(world)
    assert (await world.engine.export_domain(_OWNERS)).export is not None
    for index in range(40):
        await world.memory.add(
            memory(f"m-{index:03d}", f"a fact about the window seat, number {index}")
        )

    with pytest.raises(OversizedValueError):
        await world.engine.export_domain(_OWNERS)

    assert (await world.engine.export_domain(_SHARED)).export is not None


@_MODES
async def test_a_small_seeded_domain_measures_well_inside_the_default_frame(
    mode: SightMode, worlds: list[_World]
) -> None:
    """The size of a small seeded export, recorded against the default frame limit."""
    world = await _opened(worlds, mode)

    result = await world.engine.export_domain(_OWNERS)

    size = len(result.model_dump_json().encode())
    assert size < 64 * 1024 < 16 * 1024 * 1024
