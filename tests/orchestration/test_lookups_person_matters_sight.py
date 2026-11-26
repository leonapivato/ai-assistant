"""A work's look-ups, its person block and its matters calls read through its sight.

Milestone 22's B8e (ADR-0383 §7:5, §7:7, §9:1): the memory search and a candidate's
lookup, the episode look-ups, the connections search, the person block and the person
model a work reads and writes, and the peer view and stop record of the running-work
coordinator each go through the stores
:class:`~ai_assistant.orchestration.bound_stores.BoundStores` binds to the sight the work
carries. With stores built to withhold, an unidentified sender's work finds nothing of
the owner's, and the owner's work reads as today at every level (§6's table, §6:9); in
the counting build every read answers as today and writes its count with the reader
"work" (§11:1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import pytest
from story_support import AT, address, episode
from structlog.testing import capture_logs
from test_lookups import _call
from test_pass_sight import _OWNER, _OWNER_WEAK, _UNIDENTIFIED, _admitted

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ActivationStop,
    MessageAuthor,
    NewMessage,
    PersonActHow,
    PersonModelAct,
    PersonModelRefusal,
    PersonModelWriteKind,
    ProfileField,
    RecordHome,
    SightMode,
)
from ai_assistant.orchestration.bound_stores import BoundStores
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.episode_lookups import EpisodeLookUpReads, OlderSource
from ai_assistant.orchestration.lookups import (
    READ_EPISODE,
    READ_OLDER_HISTORY,
    SEARCH_CONNECTIONS,
    SEARCH_EPISODES,
    SEARCH_MEMORY,
    ConnectionSearch,
    LookUps,
    searched_ids,
)
from ai_assistant.orchestration.matters import Matters
from ai_assistant.orchestration.person_block import PersonBlocks, Pinned, PinRefusal
from ai_assistant.orchestration.phase_path import place_name
from ai_assistant.orchestration.planning import (
    ConnectionsFound,
    EpisodeRead,
    EpisodesFound,
    OlderHistory,
)
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakePersonModelStore,
    FakePlanStore,
    FakeStoryStore,
)
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from collections.abc import Iterator, MutableMapping, Sequence

    from ai_assistant.core.types import InputSender, Sight
    from ai_assistant.orchestration.activation_state import ActivationState

_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())
_PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)

#: The words every record a look-up should find holds, so the fake scores it 1.0.
_QUERY: Final = "camping trip Riverside"
_TEXT: Final = "Plan the camping trip to Riverside."
#: The owner's remembered fact, an earlier work's episode, both in the owner's domain.
_FACT: Final = memory("fact-trip", _TEXT, said_support(when=AT, added_at=AT))
_EARLIER: Final = "5d0c6a37-3c1e-4b8e-9e43-6f7a1c2b9d10"
#: Another work of the owner's, which a merge or a take stops.
_OTHER: Final = "0b9f2c4e-7a51-4d3f-8c62-1e5d4a3b2c19"


async def _no_stop(activation_id: str) -> ActivationStop:
    del activation_id
    return ActivationStop.STOPPED


class _World:
    """Every store a converted holder reads, each built to ``mode``, behind one holder,
    as the composition root wires them, with the owner's records in each."""

    def __init__(self, mode: SightMode) -> None:
        self.memory = FakeMemoryStore(now=lambda: AT, sight_mode=mode)
        self.stories = FakeStoryStore(now=lambda: AT, sight_mode=mode)
        self.chat = FakeConversationStore(sight_mode=mode)
        self.plans = FakePlanStore(now=lambda: AT, sight_mode=mode)
        self.people = FakePersonModelStore(now=lambda: AT, sight_mode=mode)
        self.stores = BoundStores(
            memory=self.memory,
            stories=self.stories,
            people=self.people,
            conversations=self.chat,
            plans=self.plans,
        )
        self.look_ups = LookUps(
            stores=self.stores,
            views=None,
            search_limit=5,
            episodes=EpisodeLookUpReads(
                stores=self.stores,
                threshold=0.5,
                limit=6,
                search_page=3,
                history_page=10,
                full_page=20,
                excerpt_chars=500,
            ),
            connections=ConnectionSearch(stores=self.stores, scan=10, page_size=5),
        )
        self.blocks = PersonBlocks(store=self.people, memory=self.memory, stores=self.stores)
        self.matters = Matters(
            running=list,
            stores=self.stores,
            stop=_no_stop,
            held_input_limit=4,
            in_progress_limit=5,
        )
        self.older: OlderSource | None = None

    async def seed(self) -> None:
        await self.memory.add(_FACT)
        await self.memory.add(episode(_EARLIER, text=_TEXT))
        await self.people.set_field(OWNER_PERSON_ID, ProfileField.NAME, "Leo", act=_PANEL)
        await self.people.add_pin(OWNER_PERSON_ID, _FACT.id, act=_PANEL)
        chat = await self.chat.start(home=RecordHome.owners())
        earlier = await self.chat.append_message(
            chat.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text=_TEXT, home=RecordHome.owners()),
        )
        latest = await self.chat.append_message(
            chat.id,
            NewMessage(author=MessageAuthor.ASSISTANT, text="Booked.", home=RecordHome.owners()),
        )
        assert earlier.position is not None
        assert latest.position is not None
        self.older = OlderSource(conversation_id=chat.id, before=latest.position)

    async def looked_up(self, sight: Sight) -> dict[str, Any]:
        """Every look-up a work runs, under one round's scope read by ``sight``."""
        with LookUps.scope(
            audience=_BOUNDED, owner_records=True, sight=lambda: sight, older=self.older
        ) as scope:
            searched = await self.look_ups.run(_call(SEARCH_MEMORY, decision="m", query=_QUERY))
            similar = await self.look_ups.similar(_TEXT, limit=5)
            await self.look_ups.run(_call(SEARCH_EPISODES, decision="e", query=_QUERY))
            await self.look_ups.run(_call(READ_EPISODE, decision="r", episode=address(_EARLIER)))
            await self.look_ups.run(_call(READ_OLDER_HISTORY, decision="o"))
            await self.look_ups.run(_call(SEARCH_CONNECTIONS, decision="c", query="Riverside"))
        found = scope.found
        episodes, read = found["e"], found["r"]
        older, connections = found["o"], found["c"]
        assert isinstance(episodes, EpisodesFound)
        assert isinstance(read, EpisodeRead)
        assert isinstance(older, OlderHistory)
        assert isinstance(connections, ConnectionsFound)
        assert similar is not None
        return {
            "memories": list(searched_ids(getattr(searched, "output", None))),
            "similar": [one.id for one in similar],
            "episodes": [one.record.id for one in episodes.episodes],
            "read": read.record is not None,
            "older": [one.text for one in older.items],
            "connections": len(connections.connections),
        }


async def _seeded(mode: SightMode) -> _World:
    world = _World(mode)
    await world.seed()
    return world


def _sight(state: ActivationState) -> Sight:
    sight = state.sight
    assert sight is not None
    return sight


#: What the owner's work finds today, and what every work finds in the counting build.
_AS_TODAY: Final = {
    "memories": [_FACT.id],
    "similar": [_FACT.id],
    "episodes": [address(_EARLIER)],
    "read": True,
    "older": [_TEXT],
    "connections": 1,
}

_NOTHING: Final = {
    "memories": [],
    "similar": [],
    "episodes": [],
    "read": False,
    "older": [],
    "connections": 0,
}


# --- the look-ups (ADR-0383 §7:7; ADR-0387 §4:3, §5:1) -----------------------------------


@pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])
async def test_the_owners_work_looks_up_as_today(sender: InputSender) -> None:
    world = await _seeded(SightMode.WITHHOLD)
    assert await world.looked_up(_sight(_admitted(sender))) == _AS_TODAY


async def test_an_unidentified_senders_work_looks_up_nothing_of_the_owners() -> None:
    """§6's second row: its chat's older messages, the owner's memories, episodes and
    conversations are each one the store does not hold (§7:9, §8:2)."""
    world = await _seeded(SightMode.WITHHOLD)
    assert await world.looked_up(_sight(_admitted(_UNIDENTIFIED))) == _NOTHING


async def test_a_join_that_narrows_the_sight_narrows_the_next_look_up() -> None:
    """§6:6: the scope reads the sight at each read, so a join mid-round narrows it."""
    world = await _seeded(SightMode.WITHHOLD)
    state = _admitted(_OWNER)
    with LookUps.scope(audience=_BOUNDED, owner_records=True, sight=lambda: _sight(state)):
        before = await world.look_ups.similar(_TEXT, limit=5)
        state.take_inputs((_joining(),), merged=("act-other",))
        after = await world.look_ups.similar(_TEXT, limit=5)
    assert before is not None
    assert [one.id for one in before] == [_FACT.id]
    assert after == ()


def _joining() -> Any:
    from test_pass_sight import _joining as joining  # noqa: PLC0415 — one helper

    return joining(_UNIDENTIFIED)


# --- the person block and the person model (§7:5, §7:7) ----------------------------------


@pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])
async def test_the_owners_work_is_given_its_block_and_writes_as_today(
    sender: InputSender,
) -> None:
    world = await _seeded(SightMode.WITHHOLD)
    sight = _sight(_admitted(sender))
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=_BOUNDED, sight=sight)
    assert block is not None
    assert block.profile.value(ProfileField.NAME) == "Leo"
    assert [one.id for one in block.pinned] == [_FACT.id]
    assert await world.blocks.still_held(block, sight=sight) == block
    written = await world.blocks.people(sight).set_field(
        OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=_PANEL
    )
    assert written.kind is PersonModelWriteKind.WRITTEN
    unpinned = await world.blocks.unpin(OWNER_PERSON_ID, _FACT.id, sight=sight)
    assert (unpinned.showing, unpinned.removed) == (1, 1)
    pinned = await world.blocks.pin(OWNER_PERSON_ID, _FACT.id, act=_PANEL, sight=sight)
    assert pinned.write is not None
    assert pinned.write.kind is PersonModelWriteKind.WRITTEN


async def _nothing_written() -> _World:
    """A hub holding no person record and no memory: what a sight that sees none is."""
    world = _World(SightMode.WITHHOLD)
    await world.people.clear()
    return world


async def test_an_unidentified_senders_person_block_is_a_hub_with_no_person_records() -> None:
    """Its work is no person's (ADR-0368 §9:5), so none is assembled; asked for the
    owner's under its sight, the assembly gives what a hub with no person record gives,
    and so does the name of whose place it is (ADR-0375 §6:3)."""
    world = await _seeded(SightMode.WITHHOLD)
    state = _admitted(_UNIDENTIFIED)
    sight = _sight(state)
    empty = await _nothing_written()
    owners = _sight(_admitted(_OWNER))
    assert await world.blocks.assemble(OWNER_PERSON_ID, supply=_BOUNDED, sight=sight) is None
    assert await empty.blocks.assemble(OWNER_PERSON_ID, supply=_BOUNDED, sight=owners) is None
    named = await place_name(world.blocks, state.work_facts, sight=sight, stage="planning")
    unnamed = await place_name(empty.blocks, state.work_facts, sight=owners, stage="planning")
    assert named is None
    assert named == unnamed
    # The owner's own work, at the same place, is told the name as today.
    assert await place_name(world.blocks, state.work_facts, sight=owners, stage="planning") == "Leo"


async def test_an_unidentified_senders_person_model_calls_answer_as_for_none_written() -> None:
    """§7:5, §8:2: each write names a person, or a memory, the bound store does not hold,
    and is answered exactly as in a hub where none was ever written."""
    world = await _seeded(SightMode.WITHHOLD)
    sight = _sight(_admitted(_UNIDENTIFIED))
    empty = await _nothing_written()
    owners = _sight(_admitted(_OWNER))

    async def calls(blocks: PersonBlocks, at: Sight) -> tuple[object, ...]:
        written = await blocks.people(at).set_field(
            OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=_PANEL
        )
        pinned = await blocks.pin(OWNER_PERSON_ID, _FACT.id, act=_PANEL, sight=at)
        unpinned = await blocks.unpin(OWNER_PERSON_ID, _FACT.id, sight=at)
        ends = await blocks.current_ends([_FACT.id], sight=at)
        return written.kind, written.refusal, pinned, unpinned, ends

    told = await calls(world.blocks, sight)
    assert told == await calls(empty.blocks, owners)
    assert told[:3] == (
        PersonModelWriteKind.REFUSED,
        PersonModelRefusal.UNKNOWN_PERSON,
        Pinned(refused=PinRefusal.NOT_CURRENT),
    )
    # Nothing of the owner's changed: their name, and their pin, stand.
    model = await world.people.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.value(ProfileField.ADDRESS) is None
    assert [one.memory_id for one in model.standing_pins] == [_FACT.id]


async def test_the_owners_panel_still_reads_unbound() -> None:
    """A call naming no sight is the owner's own act (milestone 22's B10), as today."""
    world = await _seeded(SightMode.WITHHOLD)
    ends = await world.blocks.current_ends([_FACT.id])
    assert [one.id for one in ends.values()] == [_FACT.id]


# --- the peer view and the stop record (§3:3, §7:7, §7:11) -------------------------------


@pytest.mark.parametrize("sender", [_OWNER, _OWNER_WEAK], ids=["normal", "weak"])
async def test_the_owners_work_is_shown_the_owners_other_work(sender: InputSender) -> None:
    world = await _seeded(SightMode.WITHHOLD)
    sight = _sight(_admitted(sender))
    assert await world.matters.peer(_EARLIER, owner_records=True, sight=sight) is not None


async def test_an_unidentified_senders_peer_view_shows_nothing_of_the_owners_work() -> None:
    """An episode its sight does not see is one with no episode: no view (§8:2)."""
    world = await _seeded(SightMode.WITHHOLD)
    sight = _sight(_admitted(_UNIDENTIFIED))
    assert await world.matters.peer(_EARLIER, owner_records=True, sight=sight) is None


@pytest.mark.parametrize("sender", [_OWNER, _UNIDENTIFIED], ids=["owner", "unidentified"])
async def test_a_stop_a_work_records_is_written_whatever_its_sight_sees(
    sender: InputSender,
) -> None:
    """A stop record carries no home and no sight holds one (§3:3): the bound store writes
    it as the unbound store does, whichever work it names, and no bound read gives it
    back, while the unbound store and a write's own check still read it (§7:11)."""
    world = await _seeded(SightMode.WITHHOLD)
    sight = _sight(_admitted(sender))
    await world.matters.record_stop(_OTHER, deadline=None, stage="takeover", sight=sight)
    assert await world.plans.stopped_activations([_OTHER]) == (_OTHER,)
    assert await world.plans.bound(sight).stopped_activations([_OTHER]) == ()


# --- the counting build: as today, each read counted as a work's (§11:1) ------------------


def _counted(
    logs: Sequence[MutableMapping[str, Any]],
) -> Iterator[tuple[object, object, object]]:
    for one in logs:
        if one["event"] == "sight_counted":
            yield one["store"], one["member"], one["reader"]


async def test_in_the_counting_build_every_read_answers_as_today_and_is_counted() -> None:
    world = await _seeded(SightMode.COUNT)
    state = _admitted(_UNIDENTIFIED)
    sight = _sight(state)
    with capture_logs() as logs:
        looked = await world.looked_up(sight)
        block = await world.blocks.assemble(OWNER_PERSON_ID, supply=_BOUNDED, sight=sight)
        named = await place_name(world.blocks, state.work_facts, sight=sight, stage="planning")
        peer = await world.matters.peer(_EARLIER, owner_records=True, sight=sight)
    # An unidentified sender's work reads what every work reads today.
    assert looked == _AS_TODAY
    assert block is not None
    assert [one.id for one in block.pinned] == [_FACT.id]
    assert named == "Leo"
    assert peer is not None
    counted = set(_counted(logs))
    assert {reader for _, _, reader in counted} == {"work"}
    assert {
        ("memory", "search"),
        ("memory", "get_many"),
        ("memory", "get"),
        ("stories", "stories_of"),
        ("conversations", "recent"),
        ("conversations", "transcript"),
        ("conversations", "taken_in"),
        ("person_model", "read"),
        ("plans", "activation_effects"),
    } <= {(store, member) for store, member, _ in counted}


async def test_the_engines_pass_assembles_the_block_by_its_admitted_works_sight() -> None:
    """On a chat turn from the owner's linked device, the block's reads, and the check
    before each round, are counted as a work's reads bound to the owner."""
    from phases_support import chat_turn, phases_harness  # noqa: PLC0415 — one harness
    from test_engine import AT as HARNESS_AT  # noqa: PLC0415

    memory_store = FakeMemoryStore(now=lambda: HARNESS_AT)
    await memory_store.add(_FACT)
    people = FakePersonModelStore()
    await people.add_pin(OWNER_PERSON_ID, _FACT.id, act=_PANEL)
    blocks = PersonBlocks(store=people, memory=memory_store)
    harness = phases_harness(memory=memory_store, person_blocks=blocks)
    with capture_logs() as logs:
        await chat_turn(harness, "What should I cook tonight?")
    counts = [one for one in logs if one["event"] == "sight_counted"]
    members = {(one["store"], one["member"]) for one in counts}
    assert {("person_model", "read"), ("memory", "get_many"), ("memory", "get_history")} <= members
    assert all(one["reader"] == "work" for one in counts)
    assert all(one["bounds"] == ["person_owner"] for one in counts)
