"""The person model's calls end to end, through the engine and the phases (ADR-0338 §8:4-§8:8).

The yes-path hub of :mod:`test_phases_yes_path`, with a person-model store wired: a
``pin`` planning proposes needs the person's yes; the question shows the memory's
wording in its exact line, and records its id. A ``set_profile`` is asked the same way.
Until the authority run a yes approves nothing (ADR-0353 §11:3), so neither runs on one:
each goes back to planning as needing the person. With no store wired, none of the three
is offered, and nothing changes (§11:2). A ``pin`` or ``unpin`` whose memory the asking
round's live read does not return current, finds resting on outside content, or cannot
read is not asked about (§8:6).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest
from structlog.testing import capture_logs
from test_engine import AT
from test_person_block import _ended
from test_phases_yes_path import (
    _DONE,
    _ask,
    _asked_calls,
    _call,
    _Hooked,
    _Hub,
)

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import MemoryStoreError
from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    MemoryStatus,
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
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from ai_assistant.core.types import Memory, MemoryRecord
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


async def test_a_pin_is_asked_with_the_memorys_wording_and_a_yes_pins_nothing() -> None:
    """§8:5-§8:6: needs you by rule, and the line shows the wording; ADR-0353 §11:3: a
    yes records no pointer, so nothing is pinned."""
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

    hub.reader.yes()
    hub.planner.then(RoundResponse(text="I'm waiting on your answer above."))
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.standing_pins == ()
    assert "approved_actions" not in hub.planner.shown(2)


async def test_a_set_profile_is_asked_and_a_yes_sets_nothing() -> None:
    """§8:5: asked with its exact line; ADR-0353 §11:3: a yes approves nothing, so the
    field and the clock stay as they were."""
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

    hub.reader.yes()
    hub.planner.then(RoundResponse(text="I'm waiting on your answer above."))
    await hub.turn("Yes.", conversation=conversation, message_id="m-2")

    model = await people.store.read(OWNER_PERSON_ID)
    assert model is not None
    assert model.profile.value(ProfileField.TIME_ZONE) is None
    assert model.changes == ()

    hub.reader.nothing()
    hub.planner.then(_DONE)
    await hub.turn("What time is it?", conversation=conversation, message_id="m-3")

    shown_after = json.loads(hub.planner.shown(3))
    assert shown_after["time_zone"] == "UTC"


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


async def test_a_pin_whose_memory_is_retired_by_the_asking_round_is_not_asked_about() -> None:
    """ADR-0342 §5:1: only a memory a live read returns current is shown as one."""
    hub, _ = await _hub()
    hub.reader.nothing()

    async def retire() -> None:
        await hub.memory.add(_ended(DIET.id, DIET.content, successor=None))

    hub.planner.then(
        _Hooked(retire, RoundResponse(calls=(_call("c1", "pin", memory="M1"),))),
        _ask(_ASKING_PIN),
    )
    conversation, asking = await hub.turn("I don't eat meat, keep that in mind.")

    assert _asked_calls(asking)[1] == ()
    assert "it cannot be asked about" in hub.planner.shown(1)
    (message,) = await hub.said(conversation)
    assert "pin —" not in message.text


@pytest.mark.parametrize("capability", ["pin", "unpin"])
async def test_a_call_whose_memory_rests_on_outside_content_by_the_asking_round_is_not_asked(
    capability: str,
) -> None:
    """§8:6, ADR-0307 §9:2: no question shows a wording that rests on outside content.

    Planning is never shown a memory resting on outside content under a label (§7:9,
    ADR-0306 §5:16), so the memory takes its outside support between the round that
    names it and the round that may ask. The live read returns it current, so only the
    outside-content guard stands between its wording and the question.
    """
    assert not REMEMBERED_DIET.rests_on_outside_content
    assert OUTSIDE_DIET.rests_on_outside_content
    assert OUTSIDE_DIET.status is MemoryStatus.CURRENT
    hub, _ = await _hub(REMEMBERED_DIET)
    hub.reader.nothing()

    async def rest_on_outside() -> None:
        await hub.memory.add(OUTSIDE_DIET)

    hub.planner.then(
        _Hooked(rest_on_outside, RoundResponse(calls=(_call("c1", capability, memory="M1"),))),
        _ask(_ASKING_PIN),
    )
    conversation, asking = await hub.turn("I don't eat meat, keep that in mind.")

    assert _asked_calls(asking)[1] == ()
    assert "it cannot be asked about" in hub.planner.shown(1)
    (message,) = await hub.said(conversation)
    assert message.text == _ASKING_PIN


async def test_a_pin_whose_memory_cannot_be_read_by_the_asking_round_is_not_asked_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§8:6: a memory store fault on the live read leaves the call unaskable; the round runs.

    The fault is armed by the round that proposes the pin and raised once, by the next
    ``get_many``: the asking round's read of the memory for its wording.
    """
    hub, _ = await _hub()
    hub.reader.nothing()
    read = hub.memory.get_many
    armed: list[bool] = []

    async def get_many(record_ids: Sequence[str]) -> Mapping[str, MemoryRecord]:
        if armed:
            armed.clear()
            msg = "the memory store cannot be read"
            raise MemoryStoreError(msg)
        return await read(record_ids)

    async def arm() -> None:
        armed.append(True)

    monkeypatch.setattr(hub.memory, "get_many", get_many)
    hub.planner.then(
        _Hooked(arm, RoundResponse(calls=(_call("c1", "pin", memory="M1"),))),
        _ask(_ASKING_PIN),
    )
    with capture_logs() as logs:
        conversation, asking = await hub.turn("I don't eat meat, keep that in mind.")

    assert not armed
    assert [one for one in logs if one["event"] == "planning_wording_unread"] == [
        {
            "event": "planning_wording_unread",
            "log_level": "warning",
            "stage": "planning",
            "reason": "memory_fault",
        }
    ]
    assert _asked_calls(asking)[1] == ()
    assert "it cannot be asked about" in hub.planner.shown(1)
    (message,) = await hub.said(conversation)
    assert message.text == _ASKING_PIN
