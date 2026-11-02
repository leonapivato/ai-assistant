"""ADR-0286 §15:3: the open episode, through production composition, on the phases.

``test_open_episode_composition`` drives these cases through ``converse``'s admission
and today's table, which the cutover retires (ADR-0309 §2:6, §5:1). Each case here is
one of them with the root's phases wired and a conversational activation started by a
message the chat's reader takes in: an episode is written open at admission, extended as
each stage ends and frozen by its end entry, the reads that feed a model pass over open
episodes, a restart closes what a dead process left open, and a capture that loses its
record ends without re-creating it.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Final

import pytest
from phases_composition_support import (
    SETTLE,
    Phased,
    answering,
    build_phased,
    hold,
    phased,
    saying,
)

from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.types import (
    ControllerRule,
    ControllerStage,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemoryWrite,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    StageOutcome,
)
from ai_assistant.orchestration.activation_state import active_state

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
    from pathlib import Path

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.orchestration.activation_state import ActivationState

pytestmark = pytest.mark.integration

#: How many frozen episodes the open-episode case seeds on its conversation, so the
#: episode window has frozen ones to hold beside the open ones it must not.
_FROZEN_COPIES: Final = 3


@pytest.fixture
async def composed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Phased]:
    """The production root with the phases, over a fresh data directory, started."""
    built = build_phased(tmp_path, monkeypatch, completer=answering())
    await built.engine.start()
    try:
        yield built
    finally:
        await built.engine.aclose()


def _open(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted open (ADR-0286 §1)."""
    assert record is not None
    processing = record.processing_record
    assert processing is not None
    assert processing.is_open, "the episode is open"
    assert record.content == ""
    assert record.placement.reach is PlacementReach.OWNER
    assert record.placement.set_by is PlacementSetter.DERIVED
    return processing


def _frozen(record: EpisodicMemory | None) -> EpisodeProcessingRecord:
    """The record's processing record, asserted frozen, on the phase path."""
    processing = phased(record).processing_record
    assert processing is not None
    assert not processing.is_open, "the episode is frozen"
    return processing


# --- an episode is stored open before the first stage -------------------------------


def _before_first_stage(
    monkeypatch: pytest.MonkeyPatch, composed: Phased, stage: str
) -> list[EpisodicMemory | None]:
    """What the store holds at the running pass's address as ``stage`` is entered."""
    seen: list[EpisodicMemory | None] = []
    original: Callable[[Any], Awaitable[None]] = getattr(composed.engine, stage)

    async def observed(working: Any) -> None:
        state = active_state()
        assert state is not None
        assert state.episode_address is not None
        if not state.stages.entries:
            seen.append(await composed.stored(state.episode_address))
        await original(working)

    monkeypatch.setattr(composed.engine, stage, observed)
    return seen


async def test_a_messages_episode_is_stored_open_before_its_first_stage(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1: inserted at admission, before any processing, carrying no stage entry."""
    seen = _before_first_stage(monkeypatch, composed, "_begin_conversation_stage")

    turn = await composed.say("hello")

    (opened,) = seen
    processing = _open(opened)
    assert opened is not None
    assert opened.id == turn.address
    assert processing.stages == ()
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    frozen = await composed.stored(turn.address)
    _frozen(frozen)
    assert frozen is not None
    # §2:2: the admission write's one capture timestamp, reused by the freeze.
    assert frozen.occurred_at == opened.occurred_at


async def test_an_informational_events_episode_is_stored_open_before_its_first_stage(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§2:1 for an event: its channel is set at admission, from the accepted identity."""
    seen = _before_first_stage(monkeypatch, composed, "_windows_stage")

    result = await composed.event()

    (opened,) = seen
    processing = _open(opened)
    assert processing.stages == ()
    assert processing.trigger.channel == result.channel
    assert result.capture.episode_id is not None
    _frozen(await composed.stored(result.capture.episode_id))


# --- each stage appends, and the frozen record is the one-write record ----------------


def _appends(
    monkeypatch: pytest.MonkeyPatch, composed: Phased
) -> list[EpisodeProcessingRecord | None]:
    """What the store holds after each of the engine's appends."""
    after: list[EpisodeProcessingRecord | None] = []
    coordinator = composed.engine._activation_coordinator
    original = coordinator.append

    async def append(state: ActivationState) -> None:
        await original(state)
        assert state.episode_address is not None
        record = await composed.stored(state.episode_address)
        after.append(None if record is None else record.processing_record)

    monkeypatch.setattr(coordinator, "append", append)
    return after


async def test_each_stage_end_leaves_one_more_entry_on_the_stored_record(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3:1: every stage's end replaces the stored episode with one more entry, open; the
    end entry is the freeze's (§4:1).

    The phases' own recorders extend the episode too, with each round, decision and
    message (ADR-0309 §3), so the record's stage entries grow one per stage across the
    stored versions, and none is ever lost.
    """
    after = _appends(monkeypatch, composed)

    turn = await composed.say("hello")

    frozen = _frozen(await composed.stored(turn.address))
    assert frozen.stages[-1].stage is ControllerStage.END
    staged = [len(stored.stages) for stored in after if stored is not None]
    assert all(stored is not None and stored.is_open for stored in after)
    assert staged == sorted(staged), "no stored version loses an entry"
    assert set(range(1, len(frozen.stages))) <= set(staged), "each stage end was stored"
    for stored in after:
        assert stored is not None
        assert stored.stages == frozen.stages[: len(stored.stages)]


async def test_a_frozen_record_is_the_one_a_single_write_at_the_end_would_store(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3's closing paragraph: both bounds keep a fixed head and a sliding tail, so a
    record frozen through appends equals the one-write record — here with a stage bound
    small enough that the appends cut it, so the elision is exercised on the way."""
    composed.engine._stage_record_limit = 3
    states: list[ActivationState] = []
    original = composed.engine._begin_conversation_stage

    async def keep(working: Any) -> None:
        state = active_state()
        assert state is not None
        states.append(state)
        await original(working)

    monkeypatch.setattr(composed.engine, "_begin_conversation_stage", keep)

    turn = await composed.say("hello")

    frozen = _frozen(await composed.stored(turn.address))
    (state,) = states
    assert frozen.ended_at is not None
    assert frozen == state.processing(frozen.ended_at, None)
    assert frozen.stages_elided > 0, "the bound cut the record"
    assert len(frozen.stages) == 3


# --- the reads that feed a model pass over open episodes ------------------------------


async def test_recall_and_the_episode_window_never_return_an_open_episode(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: no other activation's open episode reaches recall or the episode window.

    The conversation holds frozen episodes. A pass on another conversation is held open;
    a pass on the first then runs, and what its windows stage assembled is checked while
    its own and the other's open episodes are both stored. (A conversation runs one
    activation at a time, ADR-0293 §6:2, so the held one is on a second conversation.)
    """
    first = await composed.say("hello")
    template = await composed.stored(first.address)
    assert template is not None
    for n in range(_FROZEN_COPIES):
        await composed.memory.add(template.model_copy(update={"id": f"activation:copy-{n:02d}"}))
    other_conversation = await composed.start_conversation()
    gate = hold(monkeypatch, composed.engine, "_windows_stage", saying("held open"))
    observed: dict[str, Any] = {}
    original = composed.engine._windows_stage

    async def windows(working: Any) -> None:
        await original(working)
        if getattr(working, "utterance", None) == "while it is open":
            state = active_state()
            assert state is not None
            observed["own"] = state.episode_address
            observed["windows"] = working.windows

    monkeypatch.setattr(composed.engine, "_windows_stage", windows)
    await composed.write(other_conversation, "held open")
    await asyncio.wait_for(gate.entered.wait(), SETTLE)
    try:
        second = await composed.say("while it is open", first.conversation_id)
    finally:
        gate.release.set()
    await composed.idle(other_conversation)

    own, other = observed["own"], gate.address
    open_ids = {own, other}
    window = observed["windows"].episode_ids
    assert window, "the episode window holds the frozen episodes"
    assert not open_ids & set(window)
    recall = _frozen(await composed.stored(second.address)).recall
    assert recall is not None
    assert not open_ids & {item.id for item in recall.items}


# --- a restart closes what a dead process left open ------------------------------------


async def test_a_start_closes_an_open_episode_a_dead_process_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7: closed ``interrupted`` / ``hub_stopped`` by an end entry due ``hub_stopped``,
    owner-only, and its turn recorded on its conversation."""
    dying = build_phased(tmp_path, monkeypatch)
    await dying.engine.start()
    try:
        conversation_id = (await dying.say("hello")).conversation_id
        dying.cut_off()
        turn = await dying.say("dies mid-pass", conversation_id)
        left = _open(await dying.stored(turn.address))
        assert left.stages, "its stages were appended before it died"
    finally:
        await dying.engine.aclose()

    restarted = build_phased(tmp_path, monkeypatch)
    await restarted.engine.start()
    try:
        closed = await restarted.stored(turn.address)
        processing = _frozen(closed)
        assert closed is not None
        assert processing.status is ProcessingStatus.INTERRUPTED
        assert processing.reason is ProcessingReason.HUB_STOPPED
        end = processing.stages[-1]
        assert end.stage is ControllerStage.END
        assert end.due is ControllerRule.HUB_STOPPED
        assert end.outcome is StageOutcome.DONE
        assert end.started_at == end.ended_at == processing.ended_at
        assert processing.stages[:-1] == left.stages
        assert closed.placement.reach is PlacementReach.OWNER
        assert closed.placement.set_by is PlacementSetter.DERIVED
        assert closed.content == episode_content(closed)
        assert turn.address in await restarted.held(conversation_id)
        conversation = await restarted.conversations.get(conversation_id)
        assert conversation is not None
        assert conversation.last_turn_at == closed.occurred_at, "§7:3: record_turn was called"
    finally:
        await restarted.engine.aclose()


async def test_a_start_closes_no_episode_this_engine_admitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7:2: a second ``start`` closes nothing this engine admitted — the writer holds
    that episode."""
    started = build_phased(tmp_path, monkeypatch)
    await started.engine.start()
    try:
        conversation_id = (await started.say("hello")).conversation_id
        gate = hold(monkeypatch, started.engine, "_windows_stage", saying("still running"))
        await started.write(conversation_id, "still running")
        await asyncio.wait_for(gate.entered.wait(), SETTLE)
        try:
            await started.engine.start()
            _open(await started.stored(gate.address))
        finally:
            gate.release.set()
        await started.idle(conversation_id)
        assert _frozen(await started.stored(gate.address)).status is ProcessingStatus.COMPLETED
    finally:
        await started.engine.aclose()


# --- a capture failure ends capture and leaves no episode -----------------------------


def _episode_writes(monkeypatch: pytest.MonkeyPatch, memory: MemoryStore) -> list[str]:
    """Every record id the memory store is asked to write, in order."""
    written: list[str] = []
    original = memory.write_atomic

    async def write_atomic(writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written.extend(write.record.id for write in writes)
        return await original(writes)

    monkeypatch.setattr(memory, "write_atomic", write_atomic)
    return written


async def test_forget_during_a_pass_leaves_no_episode_and_its_later_stages_write_nothing(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§8: ``forget`` deletes the open episode at once; the pass runs on, its next write
    deletes instead, and nothing re-creates the episode."""
    conversation_id = (await composed.say("hello")).conversation_id
    gate = hold(monkeypatch, composed.engine, "_windows_stage", saying("forget me"))
    written = _episode_writes(monkeypatch, composed.memory)
    await composed.write(conversation_id, "forget me")
    await asyncio.wait_for(gate.entered.wait(), SETTLE)
    try:
        address = gate.address
        _open(await composed.stored(address))
        assert await composed.engine.forget(address) is True
        mark = len(written)
    finally:
        gate.release.set()
    await composed.idle(conversation_id)

    assert address not in written[mark:], "no write after the forget names the episode"
    assert await composed.stored(address) is None
    assert address not in await composed.held(conversation_id)


async def test_a_conversation_forgotten_during_a_pass_leaves_no_episode(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§5, ADR-0283 §8:1: the sweep takes the open episode on its channel, and the
    pass's next write finds no record — a mismatch, so capture ends."""
    conversation_id = (await composed.say("hello")).conversation_id
    gate = hold(monkeypatch, composed.engine, "_windows_stage", saying("forgotten under it"))
    await composed.write(conversation_id, "forgotten under it")
    await asyncio.wait_for(gate.entered.wait(), SETTLE)
    try:
        address = gate.address
        assert address in await composed.held(conversation_id), "its channel was appended"
        assert await composed.engine.forget_conversation(conversation_id) is True
    finally:
        gate.release.set()
    await composed.idle(conversation_id)

    assert await composed.stored(address) is None
    assert await composed.held(conversation_id) == []


async def test_a_forced_mismatch_ends_capture_and_leaves_no_episode(
    composed: Phased, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§3:4, §5: a stored record other than the one last written ends capture without a
    retry, deletes the episode, and the activation's answer stands."""
    conversation_id = (await composed.say("hello")).conversation_id
    gate = hold(monkeypatch, composed.engine, "_windows_stage", saying("moved under it"))
    await composed.write(conversation_id, "moved under it")
    await asyncio.wait_for(gate.entered.wait(), SETTLE)
    try:
        address = gate.address
        stored = await composed.stored(address)
        processing = _open(stored)
        assert stored is not None
        moved = stored.model_copy(
            update={"processing_record": processing.model_copy(update={"output_degraded": True})}
        )
        await composed.memory.write_atomic([MemoryWrite(record=moved)])
    finally:
        gate.release.set()
    await composed.idle(conversation_id)

    assert len(await composed.answered(conversation_id)) == 2, "processing was not failed by it"
    assert await composed.stored(address) is None


async def test_an_admission_collision_deletes_nothing(composed: Phased) -> None:
    """§2:4: the record at the address is not this activation's, so the collision writes
    nothing there and deletes nothing there."""
    first = await composed.say("hello")
    template = await composed.stored(first.address)
    assert template is not None
    minted = "5b7c0f0e-7a43-4d0c-9d3e-0c1f7f3a2b61"
    address = f"activation:{minted}"
    await composed.memory.add(template.model_copy(update={"id": address}))
    before = await composed.stored(address)
    composed.engine._activation_id_factory = lambda: minted

    await composed.say("collides", first.conversation_id)

    assert await composed.stored(address) == before
