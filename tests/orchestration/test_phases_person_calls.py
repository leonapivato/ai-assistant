"""The person model's calls end to end, through the engine and the phases (ADR-0338 §8:4-§8:8).

The yes-path hub of :mod:`test_phases_yes_path`, with a person-model store wired: a
``pin`` planning proposes needs the person's yes; the question shows the memory's
wording in its exact line, and records its id; a yes pins it, as the person's act by
that yes, and the pending suggestion it answers is accepted in the same write. A
``set_profile`` runs the same way, and the next activation tells the time in the zone it
set (§3:6). With no store wired, none of the three is offered, and nothing changes
(§11:2).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest
from phases_support import processing
from test_engine import AT
from test_phases_yes_path import (
    _DONE,
    _ask,
    _asked_calls,
    _call,
    _Hooked,
    _Hub,
    _run_approved,
)

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    PersonActHow,
    ProfileField,
    ProposedSuggestion,
    RoundResponse,
    SuggestionKind,
)
from ai_assistant.orchestration.person_block import PersonBlocks
from ai_assistant.orchestration.person_calls import PERSON_MODEL_CAPABILITIES
from ai_assistant.orchestration.phase_path import PhasePath
from ai_assistant.testing import FakePersonModelStore
from ai_assistant.testing.memories import memory, said_support

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.testing import FakeMemoryStore

pytestmark = pytest.mark.anyio

DIET: Final = memory("m:diet", "Eats no meat.", said_support(when=AT, added_at=AT))
_ASKING_PIN: Final = "Shall I keep that in mind in every conversation?"
_ASKING_ZONE: Final = "Shall I set your time zone?"


class _People:
    """A person-model store wired beside the hub's memory store, with a pin suggestion."""

    def __init__(self) -> None:
        self.store = FakePersonModelStore(now=lambda: AT)

    def __call__(self, memory_store: FakeMemoryStore) -> PersonBlocks:
        return PersonBlocks(store=self.store, memory=memory_store)


async def _hub() -> tuple[_Hub, _People]:
    people = _People()
    hub = _Hub(person=people)
    await hub.memory.add(DIET)
    # The observer's pin suggestion, which shows the memory to planning under M1 (§7:9).
    await people.store.record_suggestion(
        OWNER_PERSON_ID,
        ProposedSuggestion(kind=SuggestionKind.PIN, memory_id=DIET.id, episode_id="activation:a0"),
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


async def test_wired_the_three_are_offered_and_only_to_an_activation_given_a_block() -> None:
    hub, _ = await _hub()
    hub.reader.nothing()
    hub.planner.then(_DONE)

    await hub.turn("Hello.")

    assert hub.planner.offered(0) >= PERSON_MODEL_CAPABILITIES
    phases = hub.harness.engine._phases
    assert isinstance(phases, PhasePath)
    offered = {str(tool.capability) for tool in await phases._offered(person=False)}
    assert offered.isdisjoint(PERSON_MODEL_CAPABILITIES)


async def test_a_pin_is_asked_with_the_memorys_wording_and_a_yes_pins_it() -> None:
    """§8:5-§8:6, §8:8: needs you by rule; the line shows the wording; the yes pins it."""
    hub, people = await _hub()
    hub.reader.nothing()
    hub.planner.then(RoundResponse(calls=(_call("c1", "pin", memory="M1"),)), _ask(_ASKING_PIN))
    conversation, asking = await hub.turn("I don't eat meat, keep that in mind.")

    (question,) = await hub.said(conversation)
    assert question.text == f'{_ASKING_PIN}\n\nNeeds your yes:\npin — memory: "Eats no meat."'
    (asked,) = _asked_calls(asking)[1]
    assert dict(asked.values) == {"memory": DIET.id}
    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.pins == ()

    hub.reader.yes(_ASKING_PIN)
    hub.planner.then(_run_approved(), _DONE)
    _, approving = await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    (pin,) = model.standing_pins
    assert pin.memory_id == DIET.id
    assert pin.act.how is PersonActHow.APPROVAL
    assert pin.act.approval is not None
    assert pin.act.approval.part == asked.part
    assert pin.act.episode_id == f"activation:{processing(approving).activation_id}"
    # §8:8: the suggestion it answers is accepted in the same write.
    assert model.suggestions == ()
    # The round after the yes is told it was done.
    assert '"pinned"' in hub.planner.shown(3)


async def test_a_set_profile_runs_on_the_yes_and_the_next_activation_is_in_its_zone() -> None:
    """§8:5, §3:5: the field is the person's act by the yes; §3:6: the clock follows it."""
    hub, people = await _hub()
    hub.reader.nothing()
    hub.planner.then(
        RoundResponse(calls=(_call("c1", "set_profile", field="time_zone", value="Asia/Kolkata"),)),
        _ask(_ASKING_ZONE),
    )
    conversation, _ = await hub.turn("I've moved to Bangalore.")

    (question,) = await hub.said(conversation)
    assert question.text.endswith('set_profile — field: "time_zone"; value: "Asia/Kolkata"')
    shown_before = json.loads(hub.planner.shown(0))
    assert shown_before["time_zone"] == "UTC"

    hub.reader.yes(_ASKING_ZONE)
    hub.planner.then(_run_approved(), _DONE)
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.value(ProfileField.TIME_ZONE) == "Asia/Kolkata"
    (change,) = model.changes
    assert change.act.how is PersonActHow.APPROVAL

    hub.reader.nothing()
    hub.planner.then(_DONE)
    await hub.turn("What time is it?", conversation=conversation, message_id="m-3")

    shown_after = json.loads(hub.planner.shown(4))
    assert shown_after["time_zone"] == "Asia/Kolkata"
    assert shown_after["now"].endswith("+05:30")


async def test_a_pin_whose_memory_is_gone_by_the_asking_round_is_not_asked_about() -> None:
    """§8:6: no wording can be shown for a memory the store no longer holds."""
    hub, _ = await _hub()
    hub.reader.nothing()

    async def forget() -> None:
        await hub.memory.delete(DIET.id)

    hub.planner.then(
        _Hooked(forget, RoundResponse(calls=(_call("c1", "pin", memory="M1"),))),
        _ask(_ASKING_PIN),
    )
    conversation, asking = await hub.turn("I don't eat meat, keep that in mind.")

    assert _asked_calls(asking)[1] == ()
    assert "it cannot be asked about" in hub.planner.shown(1)
    (message,) = await hub.said(conversation)
    assert "pin —" not in message.text
