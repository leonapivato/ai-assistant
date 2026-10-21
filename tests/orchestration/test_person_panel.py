"""The person model on the panels, below the surface (ADR-0338 §6, §8:1-§8:3).

The shared suite (``person_model_contract``) holds the engine, the canonical fake and
the wire client to the seven members. What is pinned here is what no surface case can
see: that the panel's slot is the slot the person block gives the models, read from
the same stores in the same order; that a store fault reaches the caller rather than
an empty view; and that an unpin stopped part-way says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Final, cast

import pytest

from ai_assistant.core.errors import PersonModelOffError, PersonModelStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    LeftOutReason,
    MemoryOperation,
    MemoryOperationKind,
    MemoryStatus,
    MemoryWriterName,
    PersonModelEdit,
    PersonModelEditRefusal,
    PersonModelWriteKind,
    ProposedSuggestion,
    SuggestionKind,
    Validity,
)
from ai_assistant.orchestration import person_panel
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import FakeMemoryStore, FakePersonModelStore
from ai_assistant.testing.memories import memory, remembered_support, said_support

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import Memory, MemoryRecord, PersonModel, PersonModelWrite

pytestmark = pytest.mark.anyio

NOW: Final = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)
BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=frozenset())


def _fact(record_id: str, content: str) -> Memory:
    return memory(record_id, content, said_support())


def _ended(record_id: str, content: str, *, successor: str | None) -> Memory:
    support = said_support()
    at = support.added_at
    return memory(
        record_id,
        content,
        support,
        operations=(
            MemoryOperation(
                kind=MemoryOperationKind.CREATE, cites=support.points_at, at=at, by=support.added_by
            ),
            MemoryOperation(
                kind=MemoryOperationKind.END,
                cites=support.points_at,
                at=at,
                by=MemoryWriterName.OBSERVER,
                successor=successor,
            ),
        ),
        status=MemoryStatus.ENDED,
        validity=Validity(valid_until=at),
    )


class _World:
    def __init__(self, *, budget: int = 60, store: PersonModelStore | None = None) -> None:
        seconds = count()
        self.people = FakePersonModelStore(now=lambda: NOW + timedelta(seconds=next(seconds)))
        self.memory = FakeMemoryStore(now=lambda: NOW)
        self.blocks = PersonBlocks(
            store=self.people if store is None else store, memory=self.memory, budget_chars=budget
        )

    async def held(self, *records: Memory) -> None:
        for record in records:
            await self.memory.add(record)


async def _scenario(world: _World) -> None:
    """Pins and marks reaching memories in every way the slot reads one."""
    await world.held(
        _fact("m:diet", "Eats no meat."),
        _ended("m:old", "Lives in Porto.", successor="m:new"),
        _fact("m:new", "Lives in Lisbon."),
        _ended("m:stale", "Works at the bakery.", successor=None),
        memory("m:out", "The shop says it closes at six.", remembered_support(outside=True)),
        _fact("m:brief", "Short answers."),
        _fact("m:long", "y" * 30),
        _fact("m:tiny", "z"),
    )
    for one in ("m:diet", "m:old", "m:stale", "m:out", "m:new"):
        await world.people.add_pin(OWNER_PERSON_ID, one, act=person_panel.PANEL_ACT)
    for one in ("m:tiny", "m:brief", "m:long", "m:diet", "m:gone"):
        await world.people.add_style_mark(OWNER_PERSON_ID, one)


@pytest.mark.parametrize("budget", [1, 13, 29, 30, 60, 1600])
async def test_the_panels_slot_is_the_slot_the_models_are_given(budget: int) -> None:
    """§6:2, §8:2: the panel shows the block's slot, in its order, at every budget.

    And what the panel says the budget left out is the count the block left out.
    """
    world = _World(budget=budget)
    await _scenario(world)

    view = await person_panel.person_model_view(world.blocks, OWNER_PERSON_ID, limit=100, offset=0)
    block = await world.blocks.assemble(OWNER_PERSON_ID, supply=BOUNDED)

    assert view is not None
    assert block is not None
    assert [(one.memory_id, one.pinned) for one in view.kept] == [
        (one.memory.id, one.pinned) for one in block.kept
    ]
    assert [one.content for one in view.kept] == [one.memory.content for one in block.kept]
    assert sum(one.reason is LeftOutReason.BUDGET for one in view.left_out) == block.left_out
    assert view.kept_chars <= budget


async def test_the_scenario_reads_each_part_once() -> None:
    world = _World(budget=40)
    await _scenario(world)

    view = await person_panel.person_model_view(world.blocks, OWNER_PERSON_ID, limit=100, offset=0)

    assert view is not None
    assert [one.memory_id for one in view.kept] == ["m:diet", "m:new"]
    assert [(one.memory_id, one.reason) for one in view.left_out] == [
        ("m:out", LeftOutReason.OUTSIDE_CONTENT),
        ("m:long", LeftOutReason.BUDGET),
        ("m:brief", LeftOutReason.BUDGET),
        ("m:tiny", LeftOutReason.BUDGET),
    ]
    assert [(one.pin.memory_id, one.content) for one in view.no_longer_current] == [
        ("m:stale", "Works at the bakery.")
    ]
    # §4:10: the mark on a memory the store does not hold is shown nowhere.
    assert [(one.mark.memory_id, one.shows) for one in view.style_marks] == [
        ("m:tiny", "m:tiny"),
        ("m:brief", "m:brief"),
        ("m:long", "m:long"),
        ("m:diet", "m:diet"),
    ]


class _ForgettingDuringTheWalk(FakeMemoryStore):
    """The canonical store, which forgets ``m:diet`` as the walk's live read is made.

    The walk reads the memory current, and the history read made after it no longer
    holds it: a forget landing between the two reads.
    """

    async def get_many(self, record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        held = await super().get_many(record_ids)
        if "m:diet" in record_ids:
            await self.delete("m:diet")
        return held


@pytest.mark.parametrize("pinned", [True, False], ids=["pin", "mark"])
async def test_a_memory_forgotten_while_the_chains_are_walked_is_shown_nowhere(
    *, pinned: bool
) -> None:
    """§4:10: the history read is made after the walk, and what it no longer holds goes."""
    world = _World()
    world.memory = _ForgettingDuringTheWalk(now=lambda: NOW)
    world.blocks = PersonBlocks(store=world.people, memory=world.memory, budget_chars=60)
    await world.held(_fact("m:diet", "Eats no meat."), _fact("m:brief", "Short answers."))
    if pinned:
        await world.people.add_pin(OWNER_PERSON_ID, "m:diet", act=person_panel.PANEL_ACT)
    else:
        await world.people.add_style_mark(OWNER_PERSON_ID, "m:diet")
    await world.people.add_style_mark(OWNER_PERSON_ID, "m:brief")

    view = await person_panel.person_model_view(world.blocks, OWNER_PERSON_ID, limit=100, offset=0)

    assert view is not None
    assert [one.memory_id for one in view.kept] == ["m:brief"]
    assert view.left_out == ()
    assert view.no_longer_current == ()
    assert [one.mark.memory_id for one in view.style_marks] == ["m:brief"]


async def test_a_store_fault_reaches_the_caller_and_never_an_empty_view() -> None:
    """The panel's read is not the block's: a fault is the caller's to show, not "nothing"."""
    world = _World()
    world.people.fail_next()

    with pytest.raises(PersonModelStoreError):
        await person_panel.person_model_view(world.blocks, OWNER_PERSON_ID, limit=100, offset=0)


async def test_no_assembly_is_the_switch_off() -> None:
    with pytest.raises(PersonModelOffError, match="not switched on"):
        person_panel.wired(None)


class _FailingSecondRemoval:
    """The canonical store, whose second ``remove_pin`` faults: an unpin stopped part-way."""

    def __init__(self, store: FakePersonModelStore) -> None:
        self._store = store
        self.removals = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def remove_pin(self, person_id: str, pin_id: str) -> PersonModelWrite:
        self.removals += 1
        if self.removals == 2:
            msg = "the disk went away"
            raise PersonModelStoreError(msg)
        return await self._store.remove_pin(person_id, pin_id)


async def test_an_unpin_stopped_part_way_raises_rather_than_reporting_done() -> None:
    """§4:7: two pins show the memory and the second removal faults; the caller re-reads."""
    seconds = count()
    people = FakePersonModelStore(now=lambda: NOW + timedelta(seconds=next(seconds)))
    failing = _FailingSecondRemoval(people)
    world = _World(store=cast("PersonModelStore", failing))
    await world.held(
        _ended("m:old", "Lives in Porto.", successor="m:new"), _fact("m:new", "Lives in Lisbon.")
    )
    for one in ("m:old", "m:new"):
        await people.add_pin(OWNER_PERSON_ID, one, act=person_panel.PANEL_ACT)

    with pytest.raises(PersonModelStoreError, match="1 of 2"):
        await person_panel.unpin_memory(world.blocks, OWNER_PERSON_ID, "m:new")

    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert [pin.removed_at is not None for pin in held.pins] == [True, False]


class _RecordingAfterTheRead:
    """The canonical store, which records a pin suggestion just after the model is read.

    The race the accept guards: an id the caller names that was not pending when read,
    recorded before the accept is made. Its pin must still go through the checked pin.
    """

    def __init__(self, store: FakePersonModelStore) -> None:
        self._store = store
        self.landed: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    async def read(self, person_id: str) -> PersonModel | None:
        model = await self._store.read(person_id)
        if self.landed is None:
            written = await self._store.record_suggestion(
                person_id,
                ProposedSuggestion(
                    kind=SuggestionKind.PIN, memory_id="m:more", episode_id="activation:a1"
                ),
            )
            self.landed = written.record_id
        return model


async def test_a_pin_suggestion_recorded_after_the_read_is_still_checked() -> None:
    """§4:2, §6:3: a pin is made through the checked pin, whatever the read saw."""
    seconds = count()
    # Ids a caller can guess, as a conforming store may mint them.
    people = FakePersonModelStore(
        now=lambda: NOW + timedelta(seconds=next(seconds)), new_id=lambda kind: f"{kind}:next"
    )
    racing = _RecordingAfterTheRead(people)
    world = _World(budget=20, store=cast("PersonModelStore", racing))
    await world.held(_fact("m:long", "x" * 15), _fact("m:more", "y" * 10))
    await people.add_pin(OWNER_PERSON_ID, "m:long", act=person_panel.PANEL_ACT)

    edit = await person_panel.accept_suggestion(world.blocks, OWNER_PERSON_ID, "suggestion:next")

    assert racing.landed == "suggestion:next"
    assert edit == PersonModelEdit(refused=PersonModelEditRefusal.OVER_BUDGET)
    held = await people.read(OWNER_PERSON_ID)
    assert held is not None
    assert [pin.memory_id for pin in held.standing_pins] == ["m:long"]


async def test_an_unpin_where_nothing_shows_the_memory_changes_nothing() -> None:
    world = _World()

    edit = await person_panel.unpin_memory(world.blocks, OWNER_PERSON_ID, "m:none")

    assert edit.write is not None
    assert edit.write.kind is PersonModelWriteKind.UNCHANGED
