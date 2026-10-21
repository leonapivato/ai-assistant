"""The person block through the engine and the phases (ADR-0338 §7:1, §7:3, §11:2).

An engine with the phases wired, over the canonical fakes: where no person-model store is
wired, as on every hub until lane 2, nothing of the person model reaches understanding or
planning, and neither instruction speaks of it. Wired, an activation that is the owner's
is given its block, assembled once before understanding, and the same block reaches its
planning round, first in the request.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
from phases_support import chat_turn, event, phases_harness
from test_engine import AT as HARNESS_AT
from understanding_support import STATED_PROPOSAL, understanding_stage

from ai_assistant.core.types import OWNER_PERSON_ID, PersonActHow, PersonModelAct, ProfileField
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.testing import (
    FakeMemoryStore,
    FakeModelProvider,
    FakePersonModelStore,
    FakeToolCallingCompleter,
)
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from ai_assistant.core.protocols import PersonModelStore
    from ai_assistant.core.types import PersonModel

pytestmark = pytest.mark.anyio

AT: Final = datetime(2026, 1, 1, 12, tzinfo=UTC)
PANEL: Final = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))


class _Counting:
    """The person-model store, counting its reads: the block is assembled once."""

    def __init__(self, store: FakePersonModelStore) -> None:
        self.store = store
        self.reads = 0

    async def read(self, person_id: str) -> PersonModel | None:
        self.reads += 1
        return await self.store.read(person_id)


async def _wired() -> tuple[FakeMemoryStore, _Counting, PersonBlocks]:
    # The harness's own clock, which its episodes are captured at.
    memory_store = FakeMemoryStore(now=lambda: HARNESS_AT)
    await memory_store.add(DIET)
    people = FakePersonModelStore()
    await people.set_field(OWNER_PERSON_ID, ProfileField.ADDRESS, "Robin", act=PANEL)
    await people.add_pin(OWNER_PERSON_ID, DIET.id, act=PANEL)
    counting = _Counting(people)
    blocks = PersonBlocks(store=cast("PersonModelStore", counting), memory=memory_store)
    return memory_store, counting, blocks


def _understood(model: FakeModelProvider) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(model.calls[0].messages[1].content)
    return loaded


def _planned(completer: FakeToolCallingCompleter) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(completer.last_call.messages[1].content)
    return loaded


async def test_with_no_store_wired_nothing_of_the_person_model_reaches_a_model() -> None:
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter()
    harness = phases_harness(completer, understanding=understanding_stage(model=model))

    await chat_turn(harness, "What should I cook tonight?")

    assert "person" not in _understood(model)
    assert "person section" not in model.calls[0].messages[0].content
    assert "person" not in _planned(completer)
    assert "never recite it" not in completer.last_call.messages[0].content


async def test_an_owners_turn_is_given_its_block_in_understanding_and_planning() -> None:
    memory_store, counting, blocks = await _wired()
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    completer = FakeToolCallingCompleter()
    harness = phases_harness(
        completer,
        memory=memory_store,
        understanding=understanding_stage(model=model),
        person_blocks=blocks,
    )

    await chat_turn(harness, "What should I cook tonight?")

    understood = _understood(model)
    assert next(iter(understood)) == "person"
    assert understood["person"]["profile"]["address"]["value"] == "Robin"
    assert [one["fact"] for one in understood["person"]["kept_in_mind"]] == ["Eats no meat."]
    planned = _planned(completer)
    assert next(iter(planned)) == "person"
    assert [one["fact"] for one in planned["person"]["kept_in_mind"]] == ["Eats no meat."]
    assert "never recite it" in completer.last_call.messages[0].content
    assert counting.reads == 1


async def test_a_connected_sources_event_is_the_owners_too() -> None:
    memory_store, counting, blocks = await _wired()
    model = FakeModelProvider(reply=STATED_PROPOSAL)
    harness = phases_harness(
        memory=memory_store, understanding=understanding_stage(model=model), person_blocks=blocks
    )

    await event(harness)

    assert _understood(model)["person"]["profile"]["address"]["value"] == "Robin"
    assert counting.reads == 1
