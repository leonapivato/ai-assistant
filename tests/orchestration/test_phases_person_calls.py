"""The person model's calls end to end, through the engine and the phases (ADR-0338 §8:4-§8:8).

The yes-path hub of :mod:`test_phases_yes_path`, with a person-model store wired: a
``pin`` planning proposes needs the person's yes, and so does a ``set_profile``. No part
of a response names the calls a message asks about (ADR-0356 §7:5), so a question is the
round's prose alone and records no asked call. Until the authority run a yes approves
nothing (ADR-0353 §11:3), so neither runs on one: each goes back to planning as needing
the person. With no store wired, none of the three is offered, and nothing changes
(§11:2). A ``pin`` or ``unpin`` whose memory the asking
round's live read does not return current, finds resting on outside content, or cannot
read is not asked about (§8:6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from exchange_support import says
from test_engine import AT
from test_phases_yes_path import (
    _DONE,
    _ask,
    _call,
    _Hub,
)

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ProfileField,
    ProposedSuggestion,
    RoundResponse,
    SuggestionKind,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CAPABILITIES
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.testing import FakePersonModelStore
from ai_assistant.testing.memories import memory, remembered_support, said_support

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.core.types import Memory
    from ai_assistant.testing import FakeMemoryStore

pytestmark = pytest.mark.anyio

DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))
# Remembered, and resting on no outside content, so planning is shown it under a label.
REMEMBERED_DIET: Final = memory(
    "m:remembered-diet", "Eats no meat.", remembered_support(when=AT, added_at=AT)
)
# The same memory, still current, once it also rests on a remember call made over
# outside content (ADR-0328 §7:6).
OUTSIDE_DIET: Final = memory(
    REMEMBERED_DIET.id,
    REMEMBERED_DIET.content,
    *REMEMBERED_DIET.supports,
    remembered_support(effect="effect-2", outside=True, when=AT, added_at=AT),
)
_ASKING_PIN: Final = "Shall I keep that in mind in every conversation?"
_ASKING_ZONE: Final = "Shall I set your time zone?"


class _People:
    """A person-model store wired beside the hub's memory store, with a pin suggestion."""

    def __init__(self) -> None:
        self.store = FakePersonModelStore(now=lambda: AT)

    def __call__(self, memory_store: FakeMemoryStore) -> PersonBlocks:
        return PersonBlocks(store=self.store, memory=memory_store)


async def _hub(held: Memory = DIET) -> tuple[_Hub, _People]:
    people = _People()
    hub = _Hub(person=people)
    await hub.memory.add(held)
    # The observer's pin suggestion, which shows the memory to planning under M1 (§7:9).
    await people.store.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(kind=SuggestionKind.PIN, memory_id=held.id, episode_id="activation:a0"),
    )
    return hub, people


async def test_with_no_store_wired_none_of_the_three_is_offered() -> None:
    """§11:2: the calls are offered only where a person-model store is wired."""
    hub = _Hub()
    hub.reader.nothing()
    hub.planner.then(_DONE)

    await hub.turn("Hello.")

    assert hub.planner.offered(0).isdisjoint(PERSON_MODEL_CAPABILITIES)


@pytest.mark.parametrize("on", [True, False], ids=["switch-on", "switch-off"])
async def test_the_composition_roots_switch_decides_whether_the_three_are_offered(
    tmp_path: Path, *, on: bool
) -> None:
    """§11:2 as deployed: ``Settings.person_model`` wires the store, and so the calls.

    Nothing here opens a socket: the engine is built over a hashing embedder and closed.
    """
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, person_model=on), data_dir=tmp_path
    )
    try:
        phases = engine._phases
        assert isinstance(phases, PhasePath)
        offered = {str(tool.capability) for tool in await phases._offered()}
    finally:
        await engine.aclose()

    assert (offered >= PERSON_MODEL_CAPABILITIES) is on
    assert offered.isdisjoint(PERSON_MODEL_CAPABILITIES) is not on


async def test_wired_the_three_are_offered_and_refused_without_a_block() -> None:
    """ADR-0356 §4:3-§4:5: offered on every round, and refused, saying why, in an activation
    that is no person's, as the condition that once decided the offer."""
    hub, _ = await _hub()
    hub.reader.nothing()
    hub.planner.then(_DONE)

    await hub.turn("Hello.")

    assert hub.planner.offered(0) >= PERSON_MODEL_CAPABILITIES
    phases = hub.harness.engine._phases
    assert isinstance(phases, PhasePath)
    offered = await phases._offered()
    assert {str(tool.capability) for tool in offered} >= PERSON_MODEL_CAPABILITIES
    refused = phases._not_here(
        offered,
        person=False,
        scheduling=True,
        running=frozenset(),
        standing=True,
        waiting=False,
    )
    assert set(refused) >= PERSON_MODEL_CAPABILITIES
    assert all("no person's" in refused[name] for name in PERSON_MODEL_CAPABILITIES)


async def test_a_pin_needing_a_yes_is_asked_and_a_yes_pins_nothing() -> None:
    """§8:5: needs you by rule, and is spoken of in prose; ADR-0361 §4:10: a typed yes
    approves nothing, so nothing is pinned."""
    hub, people = await _hub()
    hub.reader.nothing()
    hub.planner.then(RoundResponse(calls=(_call("c1", "pin", memory="M1"),)), _ask(_ASKING_PIN))
    conversation, _ = await hub.turn("I don't eat meat, keep that in mind.")

    (question,) = await hub.said(conversation)
    assert question.text == _ASKING_PIN
    assert "needs a yes, and it cannot be asked about" in hub.planner.shown(1)
    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.pins == ()

    hub.reader.yes()
    hub.planner.then(says("I'm waiting on your answer above.", call_id="m1"))
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.standing_pins == ()
    assert "<ticket " not in hub.planner.shown(2)


async def test_a_set_profile_is_asked_and_a_yes_sets_nothing() -> None:
    """§8:5: needs you, and is spoken of in prose; ADR-0361 §4:10: a typed yes approves
    nothing, so the field and the clock stay as they were."""
    hub, people = await _hub()
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "set_profile", field="time_zone", value="Asia/Kolkata"),)),
        _ask(_ASKING_ZONE),
    )
    conversation, _ = await hub.turn("I've moved to Bangalore.")

    (question,) = await hub.said(conversation)
    assert question.text == _ASKING_ZONE
    assert "needs a yes, and it cannot be asked about" in hub.planner.shown(1)
    # The situation's clock line names the zone it tells time in (ADR-0356 §3:1).
    assert "in the hub's time zone (UTC)" in hub.planner.shown(0)

    hub.reader.yes()
    hub.planner.then(says("I'm waiting on your answer above.", call_id="m2"))
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.value(ProfileField.TIME_ZONE) is None
    assert model.changes == ()

    hub.reader.nothing()
    hub.planner.then(_DONE)
    await hub.turn("What time is it?", conversation=conversation, message_id="m-3")

    assert "in the hub's time zone (UTC)" in hub.planner.shown(3)
