"""The owner's acts on conversations read through the owner's sight (ADR-0385 §3 to §5).

Milestone 22's B10e. Every member of ``AssistantEngine`` that reads or writes the
conversation store, and the memory store where such an act reads the episodes on a
conversation's place, does so through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the owner's sight,
made for each call: from none (§3:1, §4:1, §5:2), and from the owner's domain for
``forget_conversation`` (§5:4). "My devices" and a conversation's devices, and ADR-0298
§5's device checks, read as today (§3:2). Over the production SQLite stores, built to
count and built to withhold:

- where every record is the owner's or the shared things', each act gives back and writes
  exactly what it gives back and writes over the same stores unbound;
- conversations, messages and episodes of another person's domain, and rows with no home,
  beside them change no act's answer: none is given back, counted, paged past or named,
  and an act naming one is answered as for one never written, writing nothing (§4:2,
  §5:3, ADR-0383 §8:2);
- no owner's act writes a ``sight_counted`` event in either build (§3:5), while a work's
  read of the very same store still writes its count (ADR-0383 §11:1).

**Not here**: a device's listing (``recent_conversations`` from a device other than the
hub's own machine), ``chat_changes`` and the change stream's pages, which are not yet read
through a bound store (``ConversationLifecycle``'s docstring says why). The change stream
is pinned for what it reads bound: the states it opens with.

A record of another home cannot be written through a store in this milestone (ADR-0383
§2:3), so each is written as the owner's and then altered in place, as a row altered
outside the store is; the store's home columns govern it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import pytest
from channel_episodes import conversation_episode
from sight_support import sight_of
from structlog.testing import capture_logs
from test_engine import AT, Harness

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.errors import UnknownConversationError
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    ChatDevice,
    ChatStreamChunk,
    DeviceAccess,
    RecordHome,
    RequestingDevice,
    SightMode,
    UserMessage,
)
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.sqlite_store import SqliteMemoryStore
from ai_assistant.models.embeddings import HashingEmbedder
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.testing import FakeTraceSink

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import CurrentState, Sight
    from ai_assistant.orchestration.engine import Engine

_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda one: one.value)

#: The owner's devices: the phone reads and writes every conversation started on them.
_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH: Final = ChatDevice(device_id="watch", access=DeviceAccess.READ)
PHONE: Final = RequestingDevice(device_id="phone")

#: The conversations, by the id the store mints for each. Those of another home sort
#: first, so a listing ordered by activity, then id, must pass over them.
_SAM: Final = "c-0-sam"
_NO_HOME: Final = "c-1-no-home"
_OWN: Final = "c-2-own"
_SHARED: Final = "c-3-shared"
_LATER: Final = "c-4-later"
_NEVER: Final = "c-9-never"

#: Another person's domain, and no home at all, as the columns hold them.
_SAMS: Final = ("person", "person:sam")
_NOBODYS: Final = (None, None)

#: The tables an act may write, in each store.
_CHAT_TABLES: Final = (
    "conversations",
    "messages",
    "chat_changes",
    "chat_devices",
    "conversation_devices",
    "taken_in",
)


class _AsToday(BoundStores):
    """The holder as the engine read through it before the owner's sight: unbound."""

    def memory(self, sight: Sight) -> MemoryStore:
        del sight
        return self._memory

    def conversations(self, sight: Sight) -> ConversationStore:
        del sight
        assert self._conversations is not None
        return self._conversations


@dataclass
class _World:
    """The SQLite memory and conversation stores, built in one mode, and an engine."""

    memory: SqliteMemoryStore
    chat: SqliteConversationStore
    harness: Harness
    #: The ids the conversation store mints next, in order.
    ids: list[str] = field(default_factory=list)

    @property
    def engine(self) -> Engine:
        return self.harness.engine

    def rows(self) -> dict[str, list[tuple[object, ...]]]:
        """Every row the stores hold, read beside them: what an act wrote."""
        held = {one: _dump(self.chat._conn, one) for one in _CHAT_TABLES}
        held["records"] = _dump(self.memory._conn, "records")
        return held

    def alter(self, table: str, where: str, args: Sequence[object], home: Any) -> None:
        """Set the home columns of the rows ``where`` names, outside the store (§5:3)."""
        conn: sqlite3.Connection = self.memory._conn if table == "records" else self.chat._conn
        kind, home_id = home
        conn.execute(
            f"UPDATE {table} SET home_kind = ?, home_id = ? WHERE {where}",  # noqa: S608 — the case's own names
            (kind, home_id, *args),
        )
        conn.commit()


def _dump(conn: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608 — the case's own names
    return sorted((tuple(row) for row in rows), key=repr)


def _world(mode: SightMode, *, as_today: bool = False) -> _World:
    ids: list[str] = []
    memory = SqliteMemoryStore(
        path=":memory:",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=FakeTraceSink(),
        now=lambda: AT,
        sight_mode=mode,
    )
    chat = SqliteConversationStore(
        path=":memory:", now=lambda: AT, new_id=lambda: ids.pop(0), sight_mode=mode
    )
    harness = Harness(memory=memory, conversation_store=chat, chat_reader=False, now=lambda: AT)  # type: ignore[arg-type]
    if as_today:
        harness.engine._stores = _AsToday(memory=memory, conversations=chat)
    return _World(memory, chat, harness, ids)


def _said(message_id: str, text: str, *, replies_to: int | None = None) -> UserMessage:
    return UserMessage(device_id="phone", message_id=message_id, text=text, replies_to=replies_to)


def _episode(conversation_id: str, name: str, *, completed: bool = True) -> Any:
    return conversation_episode(conversation_id, f"activation:{name}", completed=completed)


async def _seed_the_owners(world: _World) -> None:
    """The owner's conversation, with messages and ended episodes on its place, and one
    of the shared things'; nothing of another home."""
    engine = world.engine
    await engine.set_my_devices([_PHONE])
    world.ids.append(_OWN)
    assert (await engine.start_conversation()).id == _OWN
    world.ids.append(_SHARED)
    await world.chat.start(home=RecordHome.shared())
    await engine.write_message(_OWN, message=_said("m-1", "hello"))
    await engine.write_message(_OWN, message=_said("m-2", "are you there?", replies_to=1))
    await world.chat.append_message(
        _SHARED,
        _said("m-3", "the hall light").as_new_message(
            home=RecordHome.shared(), came_through="phone"
        ),
    )
    await world.memory.add(_episode(_OWN, "e-1"))
    await world.memory.add(_episode(_OWN, "e-2"))


async def _seed_the_others(
    world: _World, homes: Sequence[tuple[str, Any]] = ((_SAM, _SAMS), (_NO_HOME, _NOBODYS))
) -> None:
    """Records of another person's domain and rows with no home, after the owner's: two
    conversations, each with a message and an episode on its place; in the owner's
    conversation, a message and a failed episode of each, the newest of their listings.

    A failed episode on the owner's place would show the conversation as one that could
    not finish, were it read; and its count would be one more.
    """
    for one, home in homes:
        world.ids.append(one)
        await world.chat.start(home=RecordHome.owners())
        await world.chat.append_message(
            one,
            _said(f"m-{one}", "theirs").as_new_message(
                home=RecordHome.owners(), came_through="phone"
            ),
        )
        await world.memory.add(_episode(one, f"e-{one}"))
        await world.engine.write_message(_OWN, message=_said(f"m-own-{one}", "aside"))
        await world.memory.add(_episode(_OWN, f"e-own-{one}", completed=False))
        world.alter("conversations", "id = ?", [one], home)
        world.alter("messages", "conversation_id = ?", [one], home)
        world.alter("messages", "message_id = ?", [f"m-own-{one}"], home)
        world.alter(
            "records", "id IN (?, ?)", [f"activation:e-{one}", f"activation:e-own-{one}"], home
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
        await one.engine.aclose()
        one.memory.close()
        one.chat.close()


async def _opening_states(engine: Engine) -> list[CurrentState]:
    """The states the hub's own machine's stream opens with, before its first change."""
    states: list[CurrentState] = []
    async with closing_stream(engine.follow_chat(after=0)) as chunks, asyncio.timeout(5):
        async for chunk in chunks:
            assert isinstance(chunk, ChatStreamChunk)
            if chunk.change is not None:
                return states
            assert chunk.state is not None
            states.append(chunk.state)
    msg = "the stream ended before its first change"
    raise AssertionError(msg)


async def _as_phone[T](call: Callable[[], Awaitable[T]]) -> T:
    with serving_device(PHONE):
        return await call()


async def _reads(world: _World, *, stream: bool = True) -> dict[str, object]:
    """What each seeing act of this lane gives back over the owner's records (§4:1).

    ``stream`` reads the states the change stream opens with; its first page, which is
    not yet read through a bound store, raises on a row with no home, as it did before.
    """
    engine = world.engine
    seen: dict[str, object] = {
        "recent": await engine.recent_conversations(),
        "recent, one at a time": [
            await engine.recent_conversations(limit=1, offset=n) for n in range(3)
        ],
        "conversation": await engine.conversation(_OWN),
        "shared conversation": await engine.conversation(_SHARED),
        "transcript": await engine.transcript(_OWN),
        "transcript's newest": await engine.transcript(_OWN, limit=1),
        "transcript before": await engine.transcript(_OWN, before=2),
        "shared transcript": await engine.transcript(_SHARED),
        "the phone's conversation": await _as_phone(lambda: engine.conversation(_OWN)),
        "the phone's transcript": await _as_phone(lambda: engine.transcript(_OWN)),
        "my devices": await engine.my_devices(),
    }
    if stream:
        seen["the stream's opening states"] = await _opening_states(engine)
    return seen


def _without_head(value: object) -> object:
    """``value`` with each transcript page's ``as_of`` left out.

    ``as_of`` is the change stream's head, a store-wide figure that counts writes and
    answers alike bound or not (ADR-0383 §8:5), so it moves with every write a crowded
    store took and is no record of one.
    """
    if isinstance(value, dict):
        return {key: _without_head(one) for key, one in value.items()}
    if isinstance(value, list):
        return [_without_head(one) for one in value]
    as_of = getattr(value, "as_of", None)
    if as_of is not None:
        return value.model_copy(update={"as_of": 0})  # type: ignore[attr-defined]
    return value


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
    assert [one.id for one in seen["recent"]] == [_OWN, _SHARED]  # type: ignore[attr-defined]
    digest = seen["conversation"]
    assert digest is not None
    assert digest.recorded_turns == 2  # type: ignore[attr-defined]
    assert digest.devices == (_PHONE,)  # type: ignore[attr-defined]
    assert [one.conversation_id for one in seen["the stream's opening states"]] == [  # type: ignore[attr-defined]
        _OWN,
        _SHARED,
    ]


@_MODES
async def test_records_of_another_home_and_rows_with_no_home_change_no_seeing_act(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:1, §4:2: no conversation, message or episode of another home is given back,
    counted, paged past or named; every act answers as over the owner's records alone."""
    clean = await _opened(mode)
    crowded = await _opened(mode, others=True)
    worlds.extend((clean, crowded))

    with capture_logs() as logs:
        seen = await _reads(crowded, stream=False)

    assert _without_head(seen) == _without_head(await _reads(clean, stream=False))
    assert _counted(logs) == []


@_MODES
async def test_the_change_stream_opens_with_the_states_of_what_the_owners_sight_sees(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:1: the hub's own machine's listing and each state the stream opens with are read
    through the stores bound to the owner's sight, so a conversation of another person's
    domain is sent no state, and an episode of theirs on the owner's place ends nothing
    shown. Its pages, not yet converted, are not pinned here."""
    clean = await _opened(mode)
    crowded = await _opened(mode)
    await _seed_the_others(crowded, ((_SAM, _SAMS),))
    worlds.extend((clean, crowded))

    with capture_logs() as logs:
        states = await _opening_states(crowded.engine)

    assert states == await _opening_states(clean.engine)
    assert [one.conversation_id for one in states] == [_OWN, _SHARED]
    assert _counted(logs) == []


@_MODES
async def test_an_act_naming_a_conversation_of_another_home_answers_as_for_one_never_written(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§4:2, §5:3, ADR-0383 §8:2: each read and write naming one answers as naming one
    never started, and nothing of any store changes."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    engine = world.engine
    before = world.rows()

    async def answers(conversation_id: str) -> list[object]:
        given: list[object] = [
            await engine.conversation(conversation_id),
            await engine.transcript(conversation_id),
            await engine.delete_conversation(conversation_id),
            await engine.forget_conversation(conversation_id),
        ]
        for act in (
            lambda: engine.delete_message(conversation_id, position=1),
            lambda: engine.write_message(conversation_id, message=_said("m-new", "hi")),
            lambda: engine.set_conversation_devices(conversation_id, devices=[_PHONE, _WATCH]),
        ):
            with pytest.raises(UnknownConversationError) as raised:
                await act()
            given.append(str(raised.value).replace(conversation_id, "<named>"))
        return given

    with capture_logs() as logs:
        for unseen in (_SAM, _NO_HOME):
            assert await answers(unseen) == await answers(_NEVER)
            # In the owner's conversation, the message the sight does not see.
            position = 3 if unseen == _SAM else 4
            assert await engine.delete_message(_OWN, position=position) is False
            assert await engine.delete_message(_OWN, position=99) is False
            replied = await engine.write_message(
                _OWN, message=_said(f"m-reply-{unseen}", "re", replies_to=position)
            )
            never = await engine.write_message(
                _OWN, message=_said(f"m-reply-never-{unseen}", "re", replies_to=99)
            )
            assert replied.outcome is never.outcome
            assert replied.position is None

    assert world.rows() == before
    assert _counted(logs) == []


# --- writing writes what it writes today (§3:1, §5) ------------------------------------


async def _writes(world: _World) -> list[object]:
    """Every write act of this lane over the owner's records, in one order, each answer."""
    engine = world.engine
    world.ids.append(_LATER)
    # The signal reads the conversation's devices alone and writes nothing (ADR-0332 §5:8).
    await engine.composing(_OWN)
    return [
        await engine.start_conversation(),
        await engine.write_message(_LATER, message=_said("m-later", "later")),
        await engine.write_message(_OWN, message=_said("m-1", "hello again")),
        await engine.write_message(_OWN, message=_said("m-4", "a reply", replies_to=2)),
        await engine.set_conversation_devices(_OWN, devices=[_PHONE, _WATCH]),
        await engine.set_my_devices([_PHONE, _WATCH]),
        await engine.delete_message(_OWN, position=1),
        await engine.delete_message(_OWN, position=1),
        await engine.forget_conversation(_OWN),
        await engine.forget_conversation(_OWN),
        await engine.delete_conversation(_SHARED),
        await engine.delete_conversation(_SHARED),
        await engine.delete_conversation(_NEVER),
    ]


@_MODES
async def test_every_write_act_writes_what_it_wrote_over_the_stores_unbound(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:2, §5:4: each act writes and deletes the owner's records as before, and leaves
    the store files as they were left before the sight."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    with capture_logs() as logs:
        answers = await _writes(bound)

    assert answers == await _writes(today)
    assert bound.rows() == today.rows()
    assert await _reads(bound) == await _reads(today)
    assert _counted(logs) == []
    assert answers[8] is True, "the episodes on the owner's conversation are forgotten"
    assert answers[10] is True, "the shared things' conversation is deleted"


@_MODES
async def test_forgetting_a_conversation_forgets_the_owners_episodes_on_its_place_alone(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5:4: read and forgotten by the owner's sight from the owner's domain, so the
    episodes of another person's domain, of no home and of the shared things on the place
    are neither found nor destroyed."""
    world = await _opened(mode, others=True)
    worlds.append(world)
    await world.memory.add(
        _episode(_OWN, "e-shared").model_copy(update={"home": RecordHome.shared()})
    )

    with capture_logs() as logs:
        assert await world.engine.forget_conversation(_OWN) is True
        assert await world.engine.forget_conversation(_OWN) is False

    left = {row[0] for row in world.memory._conn.execute("SELECT id FROM records")}
    assert {"activation:e-1", "activation:e-2"}.isdisjoint(left)
    assert {
        f"activation:e-own-{_SAM}",
        f"activation:e-own-{_NO_HOME}",
        "activation:e-shared",
    } <= left
    assert _counted(logs) == []


# --- a work's reads still count (ADR-0383 §11:1) ---------------------------------------


async def test_a_works_read_of_the_store_the_owners_acts_read_still_counts(
    worlds: list[_World],
) -> None:
    """§3:5 reaches the owner's sight alone: the counting store the owner's acts read
    through withholding still answers a work's sight as unbound, writing its count."""
    world = await _opened(SightMode.COUNT, others=True)
    worlds.append(world)
    await _reads(world, stream=False)

    work = sight_of(at=AT)
    with capture_logs() as logs:
        held = await world.chat.bound(work).get(_SAM)
        episodes = await world.memory.bound(work).get(f"activation:e-{_SAM}")

    assert held is not None, "counting answers a work as the unbound store does"
    assert episodes is not None
    assert {(one["store"], one["member"], one["reader"]) for one in _counted(logs)} == {
        ("conversations", "get", "work"),
        ("memory", "get", "work"),
    }
