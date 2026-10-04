"""Ended-activation capture ordering, uncertainty, and deletion compensation (ADR-0283 §7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.episode_encoding import episode_content
from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreConflictError,
    MemoryStoreError,
)
from ai_assistant.core.types import (
    ActivationLinks,
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    ControllerRule,
    ControllerStage,
    EpisodicMemory,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    NewConversation,
    ParkedBinding,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    RecordedChannelTrigger,
    SpokenDelivery,
    SpokenDeliveryState,
    StageEntry,
    StageOutcome,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import CaptureFacts, admit_channel
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing import FakeConversationStore, FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import Conversation, EpisodeCaptureReport
    from ai_assistant.orchestration.activation_state import ActivationState

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_UUID = "1bed03e1-3b38-4e67-a2e4-6f6bf9c97eb1"
_ADDRESS = f"activation:{_UUID}"


async def _drain(work: Awaitable[None]) -> None:
    await work


def freezes(writes: Sequence[MemoryWrite]) -> bool:
    """Whether a batch carries an episode's freezing write (ADR-0286 §4)."""
    return any(
        isinstance(write.record, EpisodicMemory)
        and write.record.processing_record is not None
        and not write.record.processing_record.is_open
        for write in writes
    )


class CommitThenFail(FakeMemoryStore):
    """A store whose freezing write can commit before the caller observes a failure."""

    def __init__(self, *, cancelled: bool = False, commits: bool = True) -> None:
        super().__init__(now=lambda: _AT)
        self.after: Callable[[], Awaitable[None]] | None = None
        self.cancelled = cancelled
        self.commits = commits

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        if not freezes(writes):
            return await super().write_atomic(writes)
        if self.commits:
            await super().write_atomic(writes)
        if self.after is not None:
            await self.after()
        if self.cancelled:
            raise asyncio.CancelledError
        raise MemoryStoreError("secret input must not appear in capture logs")


class Conflicting(FakeMemoryStore):
    """A store reporting the atomic collision that is known to have written nothing."""

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        raise MemoryStoreConflictError("an existing record holds this address")


class TurnUnrecordable(FakeConversationStore):
    """A conversation store whose ``record_turn`` outcome is unknown to its caller."""

    def __init__(self, *, unreadable: bool = False) -> None:
        super().__init__(now=lambda: _AT)
        self.unreadable = unreadable

    async def record_turn(
        self,
        conversation_id: str,
        *,
        episode_id: str,
        occurred_at: datetime,
        delivery: SpokenDelivery | None = None,
    ) -> Conversation | None:
        raise ConversationStoreError("private provider diagnostics")

    async def get(self, conversation_id: str) -> Conversation | None:
        if self.unreadable:
            raise ConversationStoreError("private provider diagnostics")
        return await super().get(conversation_id)


class Wiring:
    """The production writer with two observable canonical stores."""

    def __init__(
        self,
        *,
        memory: FakeMemoryStore | None = None,
        conversations: FakeConversationStore | None = None,
    ) -> None:
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: _AT)
        self.conversations = (
            conversations if conversations is not None else FakeConversationStore(now=lambda: _AT)
        )
        self.writer = ActivationWriter(
            memory=self.memory,
            conversations=self.conversations,
            retention=timedelta(days=30),
            now=lambda: _AT,
        )

    async def state(
        self,
        *,
        captured: bool = True,
        standalone: bool = False,
        parked: ParkedBinding | None = None,
        delivery: SpokenDelivery | None = None,
    ) -> ActivationState:
        """One admitted text activation, optionally with canonical conversational facts."""
        conversation = None if standalone else await self.conversations.start()
        state = admit_channel(
            ChannelInput(
                target=NewConversation()
                if conversation is None
                else ChannelIdentity(channel_type="conversation", instance_id=conversation.id),
                payload=TextChannelPayload(text="  exact request  "),
                context=ChannelContext(),
            ),
            WholeTextReply(),
            clock=lambda: _AT,
            id_factory=lambda: _UUID,
        )
        if captured:
            assert conversation is not None
            state.facts = CaptureFacts(
                modality=Modality.TEXT,
                supplied_withheld=False,
                derived_from_external=False,
                parked=parked,
                delivery=delivery,
            )
            state.response = "the complete reply"
        return state

    async def admit(self, state: ActivationState, *, limit: int = 1024) -> None:
        """The admission write, as the engine makes it before processing (ADR-0286 §2)."""
        await self.writer.admit(state, payload_limit=limit)

    async def append(self, state: ActivationState, *, limit: int = 1024) -> None:
        """One stage's append, as the engine makes it when the stage ends (§3)."""
        await self.writer.append(state, payload_limit=limit, drain=_drain)

    async def write(self, state: ActivationState, *, limit: int = 1024) -> EpisodeCaptureReport:
        """Admit, then freeze with a fixed end reading, rebuilt as the coordinator does."""
        await self.admit(state, limit=limit)
        return await self.writer.write(
            state,
            state.processing(_AT, None),
            payload_limit=limit,
            checked_output=lambda: state.processing(_AT, None),
            drain=_drain,
        )

    async def on_channel(self, state: ActivationState) -> list[str]:
        """The ids the store physically holds on this state's conversation channel."""
        held = await self.memory.channel_episode_ids(
            conversation_channel(str(state.conversation_id)), limit=1000
        )
        return [one.episode_id for one in held]

    async def last_turn_at(self, state: ActivationState) -> datetime | None:
        """The conversation's own ``last_turn_at``, which ``record_turn`` moves."""
        conversation = await self.conversations.get(str(state.conversation_id))
        assert conversation is not None
        return conversation.last_turn_at


async def test_an_ended_exchange_is_written_at_its_activation_address_on_its_channel() -> None:
    """§2, §7:1: the id is the activation's, the channel names the conversation, and the
    conversation and the episode carry one instant."""
    wiring = Wiring()
    state = await wiring.state()
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id == _ADDRESS
    episode = await wiring.memory.get(_ADDRESS)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.trigger.channel == conversation_channel(
        str(state.conversation_id)
    )
    assert state.recorded_episode_id == _ADDRESS
    assert episode.occurred_at == await wiring.last_turn_at(state) == _AT
    assert episode.expires_at == _AT + timedelta(days=30)
    assert episode.outcome == "the complete reply"
    # ADR-0284 §7:1: the writer sets `content` by the one rule — here no stage
    # understood the input, so a line of its status, then the user's own words.
    assert episode.content == episode_content(episode)
    assert episode.content == "status completed, reason returned\n  exact request  "


class CommitThen(FakeMemoryStore):
    """A store that runs a hook once a freezing write has committed, and then answers."""

    def __init__(self) -> None:
        super().__init__(now=lambda: _AT)
        self.after: Callable[[], Awaitable[None]] | None = None

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written = await super().write_atomic(writes)
        if self.after is not None and freezes(writes):
            await self.after()
        return written


async def test_a_record_forgotten_once_it_is_frozen_gets_no_record_turn() -> None:
    """ADR-0286 §8, as ADR-0287 §4 keeps it: the user forgot the record after its freeze.

    ``forget`` marks the capture and its delete takes the episode; the writer then sees
    the mark, calls no ``record_turn`` and reports the capture degraded.
    """
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    state = await wiring.state()

    async def forgotten() -> None:
        wiring.writer.forgetting(_ADDRESS)
        await memory.delete(_ADDRESS)

    memory.after = forgotten
    report = await wiring.write(state)

    assert report.state == "degraded"
    assert await wiring.memory.get(_ADDRESS) is None
    assert await wiring.last_turn_at(state) is None, "no record_turn for a forgotten episode"
    assert state.recorded_episode_id is None


async def test_an_episode_forgotten_before_it_commits_is_destroyed_by_its_capture() -> None:
    """ADR-0286 §8: ``forget`` found nothing yet, so the capture destroys what it writes."""
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    state = await wiring.state()
    wiring.writer.forgetting(_ADDRESS)  # before any capture: marks nothing

    async def marked() -> None:
        wiring.writer.forgetting(_ADDRESS)

    memory.after = marked
    report = await wiring.write(state)

    assert report.state == "degraded"
    assert await wiring.on_channel(state) == []
    assert await wiring.last_turn_at(state) is None
    assert wiring.writer._in_flight == {}, "the capture stopped being tracked"


@pytest.mark.parametrize("standalone", [False, True])
async def test_a_capture_with_no_capture_facts_is_in_history(
    standalone: bool,
) -> None:
    """A pass that ends before capture is still on its channel, and in its history.

    ADR-0284 §6:2 retires the eligibility axis (superseding ADR-0283 §7:5): the episode
    is read by history like any other. Its ``content`` is §7's one rule, as on every
    other episode, and it carries no ``disposition`` (§5:3).
    """
    wiring = Wiring()
    state = await wiring.state(captured=False, standalone=standalone)
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id == _ADDRESS
    episode = await wiring.memory.get(_ADDRESS)
    assert isinstance(episode, EpisodicMemory)
    assert episode.content == episode_content(episode)
    assert "disposition" not in episode.model_dump()
    assert episode.processing_record is not None
    if standalone:
        assert await wiring.conversations.recent() == []
        return
    channel = conversation_channel(str(state.conversation_id))
    page = await wiring.memory.channel_episodes(channel, limit=10)
    assert [entry.record.id for entry in page.entries] == [_ADDRESS]
    assert await wiring.on_channel(state) == [_ADDRESS]


async def test_complete_record_bound_refuses_before_any_write() -> None:
    wiring = Wiring()
    state = await wiring.state()
    assert isinstance(state.trigger, RecordedChannelTrigger)
    state.trigger = state.trigger.model_copy(
        update={"payload": state.trigger.payload.model_copy(update={"text": "x" * 100000})}
    )
    assert (await wiring.write(state)).state == "degraded"
    assert await wiring.memory.export() == []
    assert await wiring.last_turn_at(state) is None


async def test_an_unknown_record_turn_outcome_leaves_a_standing_conversation_s_writes() -> None:
    """A ``record_turn`` that raised is indeterminate: the fence re-reads, finds the
    conversation standing, and destroys nothing — but the capture cannot claim recorded."""
    wiring = Wiring(conversations=TurnUnrecordable())
    state = await wiring.state()
    with capture_logs() as logs:
        report = await wiring.write(state)
    assert report.state == "degraded"
    assert report.episode_id is None
    assert await wiring.memory.get(_ADDRESS) is not None
    assert logs == [
        {
            "event": "activation_capture_degraded",
            "stage": "record_turn",
            "reason": "failed",
            "log_level": "warning",
        }
    ]


async def test_an_unreadable_conversation_cannot_claim_recorded() -> None:
    wiring = Wiring(conversations=TurnUnrecordable(unreadable=True))
    state = await wiring.state()
    with capture_logs() as logs:
        report = await wiring.write(state)
    assert report.state == "degraded"
    assert await wiring.memory.get(_ADDRESS) is not None
    assert [row["stage"] for row in logs] == ["record_turn", "verify"]
    assert all("private" not in str(row) for row in logs)


@pytest.mark.parametrize("cancelled", [False, True])
async def test_commit_then_failure_on_a_deleted_conversation_leaves_no_episode(
    cancelled: bool,
) -> None:
    """§7:4, §14:2: an episode write that commits and then propagates cancellation (or
    fails), on a conversation deleted meanwhile, leaves no episode."""
    memory = CommitThenFail(cancelled=cancelled)
    wiring = Wiring(memory=memory)
    state = await wiring.state()

    async def deleted() -> None:
        await wiring.conversations.stamp_deleted(str(state.conversation_id))

    memory.after = deleted
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await wiring.write(state)
    else:
        with capture_logs() as logs:
            assert (await wiring.write(state)).state == "degraded"
        assert all("secret" not in str(row) for row in logs)
    assert await wiring.memory.export() == []
    assert await wiring.on_channel(state) == []
    assert state.recorded_episode_id is None


async def test_an_indeterminate_freeze_its_read_confirms_is_recorded() -> None:
    """ADR-0286 §3:5: the freezing write's outcome is not known, and one read before the
    ``record_turn`` finds the freezing revision stored, which confirms the freeze."""
    wiring = Wiring(memory=CommitThenFail())
    state = await wiring.state()
    assert (await wiring.write(state)).state == "recorded"
    assert await wiring.on_channel(state) == [_ADDRESS]
    assert await wiring.last_turn_at(state) == _AT
    episode = await wiring.memory.get(_ADDRESS)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert not episode.processing_record.is_open


async def test_an_indeterminate_freeze_that_did_not_land_leaves_no_episode() -> None:
    """ADR-0286 §3:5, §5:2: the read finds the open record, not the freezing revision —
    a mismatch, so no ``record_turn``, and the episode deleted, whatever the
    conversation's state."""
    wiring = Wiring(memory=CommitThenFail(commits=False))
    state = await wiring.state()
    with capture_logs() as logs:
        assert (await wiring.write(state)).state == "degraded"
    assert await wiring.on_channel(state) == []
    assert await wiring.memory.export() == []
    assert await wiring.last_turn_at(state) is None
    assert await wiring.conversations.get(str(state.conversation_id)) is not None
    assert [(row["stage"], row["reason"]) for row in logs] == [
        ("freeze", "failed"),
        ("freeze", "mismatch"),
    ]


async def test_a_conversation_deleted_before_record_turn_keeps_no_episode() -> None:
    """§7:2, §14:2: ``record_turn``'s ``None`` deletes the episode, and the capture is
    degraded."""
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    state = await wiring.state()

    async def deleted() -> None:
        await wiring.conversations.stamp_deleted(str(state.conversation_id))

    memory.after = deleted
    report = await wiring.write(state)
    assert report.state == "degraded"
    assert report.episode_id is None
    assert await wiring.memory.export() == []
    assert await wiring.on_channel(state) == []


async def test_a_write_known_not_to_have_committed_reaches_nothing_else() -> None:
    """ADR-0286 §2:4: an admission collision is a capture failure — no ``record_turn``,
    and no compensation that could delete the record already holding the address."""
    wiring = Wiring(memory=Conflicting(now=lambda: _AT))
    state = await wiring.state()
    assert (await wiring.write(state)).state == "degraded"
    assert await wiring.last_turn_at(state) is None


async def test_the_parked_binding_is_recorded_as_the_episode_s_own_park() -> None:
    """§3:4: ``links.parks`` is the binding this activation's own step parked, and a
    resume finds the episode by it (§5)."""
    binding = ParkedBinding(execution_id="execution-1", step_id="step-1")
    wiring = Wiring()
    state = await wiring.state(parked=binding)
    assert (await wiring.write(state)).state == "recorded"
    episode = await wiring.memory.get(_ADDRESS)
    assert isinstance(episode, EpisodicMemory)
    assert episode.processing_record is not None
    assert episode.processing_record.links.parks == binding
    assert episode.processing_record.links.parked is None
    parking = await wiring.memory.episode_parking(binding)
    assert parking is not None
    assert parking.id == _ADDRESS


async def test_a_spoken_capture_writes_its_unknown_delivery_row() -> None:
    """§10: capture passes ``UNKNOWN`` through ``record_turn``."""
    unknown = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    wiring = Wiring()
    state = await wiring.state(delivery=unknown)
    assert (await wiring.write(state)).state == "recorded"
    rows = await wiring.conversations.deliveries(str(state.conversation_id), episode_ids=[_ADDRESS])
    assert dict(rows) == {_ADDRESS: unknown}


async def test_standalone_collision_preserves_existing_record_and_does_not_retry() -> None:
    wiring = Wiring()
    first = await wiring.state(captured=False, standalone=True)
    report = await wiring.write(first)
    assert report.episode_id is not None
    before = await wiring.memory.get(report.episode_id)
    repeated = await wiring.state(captured=False, standalone=True)
    assert (await wiring.write(repeated)).state == "degraded"
    assert await wiring.memory.get(report.episode_id) == before
    assert len(await wiring.memory.export()) == 1


def _entry(stage: ControllerStage, due: ControllerRule) -> StageEntry:
    return StageEntry(stage=stage, due=due, started_at=_AT, ended_at=_AT, outcome=StageOutcome.DONE)


async def _freeze(wiring: Wiring, state: ActivationState) -> EpisodeCaptureReport:
    """The freezing write alone, the admission already made."""
    return await wiring.writer.write(
        state,
        state.processing(_AT, None),
        payload_limit=1024,
        checked_output=lambda: state.processing(_AT, None),
        drain=_drain,
    )


async def test_admission_writes_an_open_episode_each_append_extends_and_the_end_freezes() -> None:
    """ADR-0286 §1-§4: open at admission, one more entry per stage end, frozen last.

    The frozen record's processing record is the one a single write at the end would
    have stored (§3:3's closing paragraph).
    """
    wiring = Wiring()
    state = await wiring.state()

    await wiring.admit(state)

    opened = await wiring.memory.get(_ADDRESS)
    assert isinstance(opened, EpisodicMemory)
    assert opened.processing_record is not None
    assert opened.processing_record.is_open
    assert opened.processing_record.stages == ()
    assert opened.content == ""
    assert opened.placement.reach is PlacementReach.OWNER
    assert opened.placement.set_by is PlacementSetter.DERIVED
    assert opened.placement.set_at == opened.occurred_at == _AT
    stages = (
        (ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED),
        (ControllerStage.ASSOCIATE_GOAL, ControllerRule.ASSOCIATION_DUE),
    )
    for count, (stage, due) in enumerate(stages, start=1):
        state.stages.append(_entry(stage, due))
        await wiring.append(state)
        stored = await wiring.memory.get(_ADDRESS)
        assert isinstance(stored, EpisodicMemory)
        assert stored.processing_record is not None
        assert stored.processing_record.is_open
        assert len(stored.processing_record.stages) == count
    state.stages.end(ControllerRule.NOTHING_DUE, _AT)

    report = await _freeze(wiring, state)

    assert report.state == "recorded"
    frozen = await wiring.memory.get(_ADDRESS)
    assert isinstance(frozen, EpisodicMemory)
    assert frozen.processing_record == state.processing(_AT, None)
    assert frozen.content == episode_content(frozen)
    assert wiring.writer._in_flight == {}


async def test_a_stored_record_other_than_the_one_written_is_a_mismatch_and_leaves_none() -> None:
    """ADR-0286 §3:4, §5: anything but the record last written ends capture, without a
    retry, and deletes the episode by its id."""
    wiring = Wiring()
    state = await wiring.state()
    await wiring.admit(state)
    stored = await wiring.memory.get(_ADDRESS)
    assert isinstance(stored, EpisodicMemory)
    assert stored.processing_record is not None
    moved = stored.model_copy(
        update={
            "processing_record": stored.processing_record.model_copy(
                update={"links": ActivationLinks(goal_id="someone-else")}
            )
        }
    )
    await wiring.memory.write_atomic([MemoryWrite(record=moved)])
    state.stages.append(
        _entry(ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED)
    )

    with capture_logs() as logs:
        await wiring.append(state)
        report = await _freeze(wiring, state)

    assert [(row["stage"], row["reason"]) for row in logs] == [("append", "mismatch")]
    assert report.state == "degraded"
    assert await wiring.memory.export() == []
    assert await wiring.last_turn_at(state) is None


async def test_the_write_after_a_forget_mark_writes_nothing_and_deletes() -> None:
    """ADR-0286 §8:2: the next write after the mark deletes the episode by its id and
    ends capture; nothing re-creates it."""
    wiring = Wiring()
    state = await wiring.state()
    await wiring.admit(state)
    wiring.writer.forgetting(_ADDRESS)
    state.stages.append(
        _entry(ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED)
    )

    await wiring.append(state)
    report = await _freeze(wiring, state)

    assert report.state == "degraded"
    assert await wiring.memory.export() == []
    assert await wiring.last_turn_at(state) is None


class AdmitsThenCancels(FakeMemoryStore):
    """A store whose admission insert commits before its caller is cancelled."""

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written = await super().write_atomic(writes)
        if any(write.mode is MemoryWriteMode.INSERT_IF_ABSENT for write in writes):
            raise asyncio.CancelledError
        return written


async def test_a_cancellation_after_the_fallback_admission_commits_leaves_no_episode() -> None:
    """ADR-0286 §5:2: an activation cancelled at the admission barrier is admitted by its
    finalization; a cancellation that lands once that insert committed still ends the
    capture, deletes the episode by its id and stops tracking it."""
    wiring = Wiring(memory=AdmitsThenCancels(now=lambda: _AT))
    state = await wiring.state()

    with pytest.raises(asyncio.CancelledError):
        await _freeze(wiring, state)

    assert await wiring.memory.export() == []
    assert not wiring.writer.holds(_ADDRESS)
    assert await wiring.last_turn_at(state) is None


class LosesOneAppend(FakeMemoryStore):
    """A store whose next replacing write fails without committing anything."""

    def __init__(self) -> None:
        super().__init__(now=lambda: _AT)
        self.lose = False

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        if self.lose and any(write.mode is MemoryWriteMode.IF_UNCHANGED for write in writes):
            self.lose = False
            raise MemoryStoreError("private store diagnostics")
        return await super().write_atomic(writes)


async def test_a_write_whose_outcome_is_unknown_and_did_not_land_is_continued_from() -> None:
    """ADR-0286 §3:4: after a write whose outcome it does not know, the writer continues
    from the record that write carried or from the record it last wrote — here the
    second, since the write did not land — and the freeze carries every entry."""
    memory = LosesOneAppend()
    wiring = Wiring(memory=memory)
    state = await wiring.state()
    await wiring.admit(state)
    state.stages.append(
        _entry(ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED)
    )
    memory.lose = True

    with capture_logs() as logs:
        await wiring.append(state)
    state.stages.end(ControllerRule.NOTHING_DUE, _AT)
    report = await _freeze(wiring, state)

    assert [(row["stage"], row["reason"]) for row in logs] == [("append", "failed")]
    assert report.state == "recorded"
    frozen = await wiring.memory.get(_ADDRESS)
    assert isinstance(frozen, EpisodicMemory)
    assert frozen.processing_record == state.processing(_AT, None)


async def test_a_close_under_a_lowered_stage_limit_still_extends_the_stored_record() -> None:
    """ADR-0286 §7: a restart whose configured stage limit is below the entries a dead
    pass stored closes the episode anyway, under the shortest bound that extends it."""
    wiring = Wiring()
    state = await wiring.state()
    await wiring.admit(state)
    stored = (
        _entry(ControllerStage.BEGIN_CONVERSATION, ControllerRule.CONVERSATION_UNRESOLVED),
        _entry(ControllerStage.ASSOCIATE_GOAL, ControllerRule.ASSOCIATION_DUE),
        _entry(ControllerStage.COMPOSE, ControllerRule.REPLY_OWED),
    )
    for entry in stored:
        state.stages.append(entry)
        await wiring.append(state)

    await _restarted(wiring).close_open(stage_limit=2, payload_limit=1024)

    closed = await wiring.memory.get(_ADDRESS)
    assert isinstance(closed, EpisodicMemory)
    processing = closed.processing_record
    assert processing is not None
    assert not processing.is_open
    assert processing.reason is ProcessingReason.HUB_STOPPED
    assert processing.stages[:2] == (stored[0], stored[2])
    assert processing.stages[-1].due is ControllerRule.HUB_STOPPED
    assert processing.stages_elided == 1


def _restarted(wiring: Wiring) -> ActivationWriter:
    """A second process's writer over the same stores, holding no capture."""
    return ActivationWriter(
        memory=wiring.memory,
        conversations=wiring.conversations,
        retention=timedelta(days=30),
        now=lambda: _AT,
    )


async def test_a_close_that_would_exceed_the_record_bound_deletes_the_episode() -> None:
    """ADR-0286 §3:6, §7:3: the close is a freezing write, measured on the whole record
    it would store; one past ADR-0275 §9:1's bound is a capture failure, and the episode
    is deleted by its id (§5:2) rather than written or left open."""
    wiring = Wiring()
    state = await wiring.state()
    await wiring.admit(state)
    opened = await wiring.memory.get(_ADDRESS)
    assert isinstance(opened, EpisodicMemory)
    processing = opened.processing_record
    assert processing is not None
    assert isinstance(processing.trigger, RecordedChannelTrigger)
    trigger = processing.trigger.model_copy(
        update={"payload": processing.trigger.payload.model_copy(update={"text": "x" * 40_000})}
    )
    large = opened.model_copy(
        update={"processing_record": processing.model_copy(update={"trigger": trigger})}
    )
    # A dead pass's open episode holding a long input: written fresh, since the store
    # refuses to rewrite a stored trigger in place.
    await wiring.memory.delete(_ADDRESS)
    await wiring.memory.write_atomic([MemoryWrite(record=large)])

    with capture_logs() as logs:
        await _restarted(wiring).close_open(stage_limit=8, payload_limit=1024)

    assert [(row["stage"], row["reason"]) for row in logs] == [("close", "invalid_or_oversized")]
    assert await wiring.memory.export() == []
