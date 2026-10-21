"""A fetched record resting on outside content marks the episode from then on (#3270).

ADR-0223's value for an episode is a disjunction over what its pass was given, so a
record the pass fetched resting on outside content makes it true the moment it is seen.
The pass holds it from there, and ADR-0286 §4:3 carries it into every append after: the
episode is marked on its stored record while the activation still runs, not only by the
freezing write. A restart's close keeps what the episode stored (ADR-0286 §7), so an
activation the hub's stop cut off before its freeze is marked too, and the observer,
which reads the stored record alone, reads it as having read outside content (ADR-0306
§4:5, ADR-0328 §4:3).

The one outside thing in each case is a past episode marked as resting on outside
content, which recall's second run finds and planning is shown: no digest, no marked
note and no outside trigger.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from test_engine import AT, Harness
from test_engine_phases import (
    _BOOK,
    _DENTIST,
    _NOTHING_DIGESTED,
    _call,
    _conversation,
    _GatedCompleter,
    _no_episode_window,
    _phases,
    _running_activation,
    _say,
    _settled,
)
from test_planning import _episode as _past_episode
from understanding_support import recall_stage, understanding_stage

from ai_assistant.core.types import (
    EpisodicMemory,
    ProcessingReason,
    ProcessingStatus,
    RoundResponse,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.authorizer import (
    OutsideGround,
    WorkingRecord,
    read_outside_content,
)
from ai_assistant.orchestration.understanding import WindowsStage
from ai_assistant.testing import FakeMemoryStore, FakeModelProvider, FakeToolCallingCompleter

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore

_PAST: Final = "activation:past"
_SETTLE: Final = 5.0


async def _harness(completer: FakeToolCallingCompleter) -> Harness:
    """A test hub whose store holds one past episode resting on outside content."""
    store = FakeMemoryStore(now=lambda: AT)
    past = _past_episode(_PAST).model_copy(update={"content": f"{_DENTIST} booked for Friday"})
    await store.add(
        past.model_copy(
            update={
                "provenance": past.provenance.model_copy(update={"derived_from_external": True})
            }
        )
    )
    understanding = FakeModelProvider(
        reply=json.dumps({"meaning": _DENTIST, "meaning_ground": "stated"})
    )
    return Harness(
        understanding=understanding_stage(model=understanding),
        tools=(_BOOK,),
        memory=store,
        windows=WindowsStage(episodes=_no_episode_window),
        recall=recall_stage(store),
        phases=_phases(completer, digests=FakeModelProvider(reply=_NOTHING_DIGESTED)),
    )


async def _read_as_the_observer(memory: MemoryStore, episode: EpisodicMemory) -> list[str]:
    """The grounds that hold over the stored record alone, as the observer reads it.

    No working set outlives its activation, so nothing it held is handed in.
    """
    record = episode.processing_record
    assert record is not None
    grounds: list[OutsideGround] = []
    assert await read_outside_content(
        memory, record.activation_id, working=WorkingRecord(), grounds=grounds
    )
    return [one.ground for one in grounds if one.record == episode.id]


async def test_an_activation_whose_one_ground_is_a_fetched_record_freezes_marked() -> None:
    """ADR-0286 §4:2-§4:3: the frozen episode carries the mark, and reads as outside."""
    completer = FakeToolCallingCompleter.scripted(RoundResponse(text="It is on Friday."))
    harness = await _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "when?")
    episode = await _settled(harness, conversation, seeded=frozenset({_PAST}))

    record = episode.processing_record
    assert record is not None
    assert record.recall_second_run is not None
    assert [one.id for one in record.recall_second_run.items] == [_PAST]
    assert record.digests == ()
    assert not any(one.notes_marked for one in record.rounds)
    assert episode.provenance.derived_from_external
    # Its own mark, read off the stored record, is a ground of its own.
    assert await _read_as_the_observer(harness.memory, episode) == ["episode_marked"]


async def test_an_activation_cut_off_after_the_fetch_is_closed_marked() -> None:
    """#3270, ADR-0286 §4:3, §7: the append after the fetch is marked, and the close keeps it.

    The first round books, and the second waits on its model call. The hub's stop
    leaves the episode open, as a crash leaves it, and the next process's close freezes
    it ``interrupted`` / ``hub_stopped`` with the provenance it stored.
    """
    completer = _GatedCompleter(
        RoundResponse(text="Booking it.", calls=(_call("c1", "book", date="2026-10-12"),)),
        RoundResponse(text="Booked."),
        gated=2,
    )
    harness = await _harness(completer)
    conversation = await _conversation(harness)

    await _say(harness, conversation, "book it")
    await asyncio.wait_for(completer.entered.wait(), _SETTLE)
    activation = await _running_activation(harness)
    address = f"activation:{activation}"
    stored = await harness.memory.get(address)
    assert isinstance(stored, EpisodicMemory)
    assert stored.processing_record is not None
    assert stored.processing_record.is_open
    assert stored.processing_record.rounds
    assert stored.provenance.derived_from_external

    restarted = ActivationWriter(
        memory=harness.memory,
        conversations=harness.conversation_store,
        retention=timedelta(days=30),
        now=lambda: AT,
    )
    await restarted.close_open(stage_limit=64, payload_limit=1 << 20)

    closed = await harness.memory.get(address)
    assert isinstance(closed, EpisodicMemory)
    assert closed.processing_record is not None
    assert (closed.processing_record.status, closed.processing_record.reason) == (
        ProcessingStatus.INTERRUPTED,
        ProcessingReason.HUB_STOPPED,
    )
    assert closed.provenance.derived_from_external
    assert await _read_as_the_observer(harness.memory, closed) == ["episode_marked"]
    # The cut-off pass is let go and left to end; what it does then is not this case's.
    completer.gate.set()
    await _ended(harness, conversation)


async def _ended(harness: Harness, conversation: str) -> None:
    """Wait for the conversation's activation to end."""
    deadline = asyncio.get_running_loop().time() + _SETTLE
    while True:
        state = await harness.engine.conversation(conversation)
        if state is not None and not state.state.working:
            return
        if asyncio.get_running_loop().time() > deadline:
            msg = "the activation did not end"
            raise AssertionError(msg)
        await asyncio.sleep(0.001)
