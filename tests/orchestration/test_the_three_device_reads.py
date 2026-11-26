"""The three reads that join device rows to records of a home, through the owner's sight.

Milestone 22's B10g (ADR-0389 §5, §7). A device's ``recent_conversations``,
``chat_changes`` from the hub's own machine and from a device, and ``follow_chat``'s
pages and a device's listing each read through the conversation store bound to the
owner's sight from none, made for that read (§5:1). Over the production SQLite stores,
built to count and built to withhold:

- where every record is the owner's or the shared things', each gives back exactly what
  it gives back over the same stores unbound: every page, cursor and snapshot, a dropped
  conversation's deletion among them (§3, §5), and a device added to a conversation is
  sent the change that adds it with its snapshot, as today;
- a conversation, a message or a dropped conversation's deletion stored with no home, or
  of another person's domain, beside them is given back by none of the three, and no
  page is cut short or read past for it (ADR-0383 §5:3, §7:2);
- none writes a ``sight_counted`` event in either build (ADR-0385 §3:5).

A record of another home cannot be written through a store in this milestone (ADR-0383
§2:3), so each is written as the owner's and then altered in place, as a row altered
outside the store is; the store's home columns govern it. Both worlds a comparison reads
take the same writes in the same order, so their sequence numbers, and so their cursors,
are one.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, NamedTuple

import pytest
from structlog.testing import capture_logs
from test_engine import AT, Harness

from ai_assistant.core.device_context import serving_device
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    CHAT_SNAPSHOT_ENTRIES,
    HUB_REQUESTING_DEVICE,
    ChatChanges,
    ChatDevice,
    ChatStreamChunk,
    ConversationDeletedChange,
    DeletedMessage,
    DeviceAccess,
    DeviceRole,
    DevicesChangedChange,
    MessageAddedChange,
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
    from collections.abc import AsyncIterator, Mapping, Sequence

    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import ChatChange, ConversationSummary, DeviceChange, Sight
    from ai_assistant.orchestration.engine import Engine

_MODES: Final = pytest.mark.parametrize("mode", list(SightMode), ids=lambda one: one.value)

_PHONE: Final = ChatDevice(device_id="phone", access=DeviceAccess.READ_WRITE)
_WATCH: Final = ChatDevice(device_id="watch", access=DeviceAccess.READ)
_TABLET: Final = ChatDevice(device_id="tablet", access=DeviceAccess.READ)
_PEN: Final = ChatDevice(device_id="pen", access=DeviceAccess.WRITE)

PHONE: Final = RequestingDevice(device_id="phone")
WATCH: Final = RequestingDevice(device_id="watch")
#: In no "my devices": an end of the owner's conversation alone, added late, so its
#: first change there is the one that adds it, with its snapshot (ADR-0298 §7:6).
TABLET: Final = RequestingDevice(device_id="tablet")
#: The tablet holding the command role, so its role is settled with no read (ADR-0298
#: §5). ADR-0298 §5's checks read device rows unbound, as today (ADR-0389 §4:4); a device
#: in no "my devices" is found an end by listing its conversations unbound, and an unbound
#: read of a row with no home raises as corrupt, as today. Where the cases alter rows to
#: no home, the tablet holds a role, so what is pinned is the three reads, not the check.
TABLET_HOLDING_A_ROLE: Final = RequestingDevice(
    device_id="tablet", roles=frozenset({DeviceRole.COMMANDS})
)
HUB: Final = HUB_REQUESTING_DEVICE

#: The conversations, by the id the store mints for each, in the order each is started.
_OWN: Final = "c-1-own"
_SHARED: Final = "c-2-shared"
_GONE: Final = "c-3-gone"
_NO_HOME: Final = "c-4-no-home"
_SAM: Final = "c-5-sam"

#: More messages in the owner's conversation than one snapshot holds, so the snapshot
#: the tablet is sent is cut to its newest.
_OWN_MESSAGES: Final = CHAT_SNAPSHOT_ENTRIES + 3

#: The owner's message altered to no home, among the newest a snapshot holds.
_ALTERED: Final = _OWN_MESSAGES - 1

#: The last change every follower is sent: a message in the owner's conversation.
_LAST_WORD: Final = "the last word"

#: How long a deleted conversation's row outlives its deletion.
_GRACE: Final = timedelta(hours=1)

_SAMS: Final = ("person", "person:sam")
_NOBODYS: Final = (None, None)


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
    ids: list[str] = field(default_factory=list)
    #: The conversation store's clock, moved past the grace to drop a deleted one.
    clock: list[datetime] = field(default_factory=lambda: [AT])

    @property
    def engine(self) -> Engine:
        return self.harness.engine

    def alter(self, table: str, where: str, args: Sequence[object], home: Any) -> None:
        """Set the home columns of the rows ``where`` names, outside the store (§5:3)."""
        kind, home_id = home
        self.chat._conn.execute(
            f"UPDATE {table} SET home_kind = ?, home_id = ? WHERE {where}",  # noqa: S608 — the case's own names
            (kind, home_id, *args),
        )
        self.chat._conn.commit()


def _world(mode: SightMode, *, as_today: bool = False) -> _World:
    ids = [_OWN, _SHARED, _GONE, _NO_HOME, _SAM]
    memory = SqliteMemoryStore(
        path=":memory:",
        embedder=HashingEmbedder(dimensions=64),
        traces_sink=FakeTraceSink(),
        now=lambda: AT,
        sight_mode=mode,
    )
    clock = [AT]
    chat = SqliteConversationStore(
        path=":memory:",
        now=lambda: clock[0],
        new_id=lambda: ids.pop(0),
        tombstone_grace=_GRACE,
        sight_mode=mode,
    )
    harness = Harness(memory=memory, conversation_store=chat, chat_reader=False, now=lambda: AT)  # type: ignore[arg-type]
    if as_today:
        harness.engine._stores = _AsToday(memory=memory, conversations=chat)
    return _World(memory, chat, harness, ids, clock)


def _said(message_id: str, text: str, device: str = "phone") -> UserMessage:
    return UserMessage(device_id=device, message_id=message_id, text=text)


async def _seed(world: _World) -> None:
    """The same writes in every world, each made as the owner's or the shared things'.

    The owner's conversation, longer than a snapshot; the shared things'; one deleted
    and dropped, whose deletion alone is left; two more, later altered to no home and to
    another person's domain where the case asks; changes to "my devices" and to the
    owner's conversation's devices, the tablet added there last; and the last word.
    """
    engine = world.engine
    await engine.set_my_devices([_PHONE, _WATCH])
    assert (await engine.start_conversation()).id == _OWN
    await world.chat.start(home=RecordHome.shared())
    for n in range(1, _OWN_MESSAGES + 1):
        await engine.write_message(_OWN, message=_said(f"m-own-{n}", f"own {n}"))
    await world.chat.append_message(
        _SHARED,
        _said("m-shared", "the hall light").as_new_message(
            home=RecordHome.shared(), came_through="phone"
        ),
    )
    assert (await engine.start_conversation()).id == _GONE
    await engine.write_message(_GONE, message=_said("m-gone", "soon gone"))
    assert await engine.delete_conversation(_GONE) is True
    # Past the grace, the deleted conversation's row is dropped, and only its deletion,
    # carrying its home, is left (ADR-0389 §3).
    world.clock[0] = AT + 2 * _GRACE
    assert await world.chat.drop_if_eligible(_GONE) is True
    for other in (_NO_HOME, _SAM):
        assert (await engine.start_conversation()).id == other
        await engine.write_message(other, message=_said(f"m-{other}", "theirs"))
        await engine.set_conversation_devices(other, devices=[_PHONE, _WATCH, _TABLET])
    await engine.delete_message(_OWN, position=2)
    await engine.set_my_devices([_PHONE, _WATCH, _PEN])
    await engine.set_conversation_devices(_OWN, devices=[_PHONE, _WATCH, _TABLET])
    await engine.write_message(_OWN, message=_said("m-last", _LAST_WORD))


def _crowd(world: _World) -> None:
    """Alter, outside the store, what the owner's sight must not see (ADR-0383 §5:3).

    A conversation and its message with no home, another of another person's domain, one
    of the owner's messages with no home, and the dropped conversation's deletion with no
    home: none of their changes, listings or snapshot entries may be given back.
    """
    for conversation_id, home in ((_NO_HOME, _NOBODYS), (_SAM, _SAMS)):
        world.alter("conversations", "id = ?", [conversation_id], home)
        world.alter("messages", "conversation_id = ?", [conversation_id], home)
    world.alter("messages", "conversation_id = ? AND position = ?", [_OWN, _ALTERED], _NOBODYS)
    world.alter(
        "chat_changes",
        "kind = 'conversation_deleted' AND conversation_id = ?",
        [_GONE],
        _NOBODYS,
    )


async def _opened(mode: SightMode, *, as_today: bool = False, crowded: bool = False) -> _World:
    world = _world(mode, as_today=as_today)
    await _seed(world)
    if crowded:
        _crowd(world)
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


# --- the reads ---------------------------------------------------------------------


class _Listing(NamedTuple):
    """``recent_conversations`` as one device: whole, and one at a time to its end."""

    whole: tuple[ConversationSummary, ...]
    one_at_a_time: list[tuple[ConversationSummary, ...]]


#: The walks of ``chat_changes`` each caller makes: the page size and the conversations.
_WALKS: Final[dict[str, tuple[int, tuple[str, ...] | None]]] = {
    "whole": (500, None),
    "by one": (1, None),
    "by three": (3, None),
    "the owner's alone": (2, (_OWN,)),
    "the dropped one alone": (2, (_GONE,)),
}


@dataclass(frozen=True)
class _Seen:
    """What each of the three reads gives back, by caller."""

    listings: dict[str, _Listing]
    changes: dict[str, dict[str, list[ChatChanges]]]
    streams: dict[str, list[ChatStreamChunk]]


async def _listing(engine: Engine, device: RequestingDevice) -> _Listing:
    with serving_device(device):
        whole = await engine.recent_conversations()
        pages: list[tuple[ConversationSummary, ...]] = []
        while True:
            page = await engine.recent_conversations(limit=1, offset=len(pages))
            pages.append(page)
            if not page:
                return _Listing(whole, pages)


async def _walked(
    engine: Engine, device: RequestingDevice, *, limit: int, named: tuple[str, ...] | None
) -> list[ChatChanges]:
    """``chat_changes`` as ``device``, page after page of ``limit`` until a short one."""
    pages: list[ChatChanges] = []
    cursor = 0
    with serving_device(device):
        while True:
            page = await engine.chat_changes(after=cursor, conversation_ids=named, limit=limit)
            pages.append(page)
            if len(page.changes) < limit:
                return pages
            cursor = page.next_after


def _is_last_word(chunk: ChatStreamChunk) -> bool:
    entry = chunk.change
    return (
        entry is not None
        and isinstance(entry.change, MessageAddedChange)
        and entry.change.message.text == _LAST_WORD
    )


async def _followed(engine: Engine, device: RequestingDevice) -> list[ChatStreamChunk]:
    """``follow_chat`` from the start as ``device``, every chunk to the last word."""
    sent: list[ChatStreamChunk] = []
    with serving_device(device):
        stream = engine.follow_chat(after=0)
        async with closing_stream(stream) as chunks, asyncio.timeout(10):
            async for chunk in chunks:
                assert isinstance(chunk, ChatStreamChunk)
                sent.append(chunk)
                if _is_last_word(chunk):
                    return sent
    msg = "the stream ended before the last word"
    raise AssertionError(msg)


_DEVICE_IDS: Final = ("phone", "watch", "tablet")
_CALLER_IDS: Final = ("hub", *_DEVICE_IDS)


async def _reads(world: _World, *, tablet: RequestingDevice = TABLET) -> _Seen:
    engine = world.engine
    devices = (PHONE, WATCH, tablet)
    callers = (HUB, *devices)
    return _Seen(
        listings={one.device_id: await _listing(engine, one) for one in devices},
        changes={
            one.device_id: {
                walk: await _walked(engine, one, limit=limit, named=named)
                for walk, (limit, named) in _WALKS.items()
            }
            for one in callers
        },
        streams={one.device_id: await _followed(engine, one) for one in callers},
    )


def _counted(logs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [one for one in logs if one["event"] == "sight_counted"]


def _whole(pages: Sequence[ChatChanges]) -> list[ChatChange]:
    return [one for page in pages for one in page.changes]


def _sent_changes(stream: Sequence[ChatStreamChunk]) -> list[DeviceChange]:
    return [one.change for one in stream if one.change is not None]


def _adding_the_tablet(stream: Sequence[ChatStreamChunk]) -> DeviceChange:
    """The one change the tablet's stream is sent that adds it to the owner's."""
    (adding,) = (
        one
        for one in _sent_changes(stream)
        if isinstance(one.change, DevicesChangedChange) and one.change.conversation_id == _OWN
    )
    return adding


# --- what the owner's sight withholds, as the cases expect it ------------------------


def _withheld(change: ChatChange) -> bool:
    """Whether a change is of what :func:`_crowd` altered."""
    if change.conversation_id in {_NO_HOME, _SAM}:
        return True
    if isinstance(change, ConversationDeletedChange):
        return change.conversation_id == _GONE
    if isinstance(change, MessageAddedChange):
        return (change.message.conversation_id, change.message.position) == (_OWN, _ALTERED)
    return False


def _positions(entry: DeviceChange) -> list[int]:
    assert entry.snapshot is not None
    return [one.position for one in entry.snapshot]


# --- every record the owner's or the shared things' (ADR-0389 §5) -----------------------


@_MODES
async def test_each_read_gives_back_what_it_gave_back_over_the_stores_unbound(
    mode: SightMode, worlds: list[_World]
) -> None:
    """§5's last paragraph: every listing, page, cursor, stream chunk and snapshot is the
    unbound store's, a dropped conversation's deletion included, for the hub's own
    machine and for each device; and the owner's sight writes no count."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    with capture_logs() as logs:
        seen = await _reads(bound)

    assert seen == await _reads(today)
    assert _counted(logs) == [], "the owner's sight writes no count, in either build"

    assert {one.id for one in seen.listings["phone"].whole} == {_OWN, _SHARED, _NO_HOME, _SAM}
    assert {one.id for one in seen.listings["tablet"].whole} == {_OWN, _NO_HOME, _SAM}
    hub = _whole(seen.changes["hub"]["whole"])
    assert _whole(seen.changes["hub"]["by one"]) == hub
    assert _whole(seen.changes["hub"]["by three"]) == hub
    (deletion,) = (one for one in hub if isinstance(one, ConversationDeletedChange))
    assert deletion.conversation_id == _GONE
    assert await bound.chat.get(_GONE) is None, "the dropped conversation's row is gone"
    assert deletion in _whole(seen.changes["phone"]["whole"]), "it reaches a device that read it"
    assert [
        one for one in _whole(seen.changes["phone"]["the dropped one alone"]) if one.conversation_id
    ] == [deletion]
    assert deletion in [one.change for one in _sent_changes(seen.streams["watch"])]


@_MODES
async def test_a_device_added_to_a_conversation_is_sent_the_change_that_adds_it_with_its_snapshot(
    mode: SightMode, worlds: list[_World]
) -> None:
    """ADR-0298 §7:6, through the owner's sight (ADR-0389 §2:3): the tablet's stream is
    sent the change that adds it to the owner's conversation with the newest messages,
    as over the stores unbound."""
    bound = await _opened(mode)
    today = await _opened(mode, as_today=True)
    worlds.extend((bound, today))

    sent = await _followed(bound.engine, TABLET)

    assert sent == await _followed(today.engine, TABLET)
    adding = _adding_the_tablet(sent)
    assert adding.snapshot is not None
    assert len(adding.snapshot) == CHAT_SNAPSHOT_ENTRIES
    newest = adding.snapshot[-1]
    assert not isinstance(newest, DeletedMessage)
    assert newest.position == _OWN_MESSAGES


# --- a record with no home, or of another person's domain, is given back by none -------


@_MODES
async def test_no_read_gives_back_a_record_the_owners_sight_does_not_see(
    mode: SightMode, worlds: list[_World]
) -> None:
    """ADR-0383 §5:3, ADR-0389 §2, §3:4: beside the owner's records, a conversation and a
    message with no home, another person's conversation and a dropped conversation's
    deletion with no home are in no listing, page, stream or state; every other change
    is given back, and no walk ends at another cursor for them."""
    clean = await _opened(mode)
    crowded = await _opened(mode, crowded=True)
    worlds.extend((clean, crowded))

    with capture_logs() as logs:
        seen = await _reads(crowded, tablet=TABLET_HOLDING_A_ROLE)
    assert _counted(logs) == []
    expected = await _reads(clean, tablet=TABLET_HOLDING_A_ROLE)

    for name in _DEVICE_IDS:
        listed = [one.id for one in seen.listings[name].whole]
        assert listed == [
            one.id for one in expected.listings[name].whole if one.id not in {_NO_HOME, _SAM}
        ]
        assert [one.id for page in seen.listings[name].one_at_a_time for one in page] == listed

    for name in _CALLER_IDS:
        for walk, pages in seen.changes[name].items():
            assert _whole(pages) == [
                one for one in _whole(expected.changes[name][walk]) if not _withheld(one)
            ], (name, walk)
            assert pages[-1].next_after == expected.changes[name][walk][-1].next_after
        stream = seen.streams[name]
        assert [one.change for one in _sent_changes(stream)] == [
            one.change for one in _sent_changes(expected.streams[name]) if not _withheld(one.change)
        ], name
        assert {one.state.conversation_id for one in stream if one.state is not None}.isdisjoint(
            {_NO_HOME, _SAM}
        )


@_MODES
async def test_the_tablets_snapshot_holds_the_newest_messages_the_sight_sees(
    mode: SightMode, worlds: list[_World]
) -> None:
    """ADR-0389 §2:3: the change that adds the tablet carries the newest
    ``CHAT_SNAPSHOT_ENTRIES`` messages the owner's sight sees, so one with no home among
    them is passed over and an older one takes its slot."""
    clean = await _opened(mode)
    crowded = await _opened(mode, crowded=True)
    worlds.extend((clean, crowded))

    seen = _positions(_adding_the_tablet(await _followed(crowded.engine, TABLET_HOLDING_A_ROLE)))
    whole = _positions(_adding_the_tablet(await _followed(clean.engine, TABLET_HOLDING_A_ROLE)))

    assert len(seen) == len(whole) == CHAT_SNAPSHOT_ENTRIES
    assert _ALTERED in whole
    assert seen == [whole[0] - 1, *(one for one in whole if one != _ALTERED)]
