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
    TranscriptArchiveError,
)
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    EpisodeResponseKind,
    EpisodicMemory,
    ExchangeDisposition,
    Modality,
    NewConversation,
    ParkedBinding,
    RecordedChannelTrigger,
    SpokenDelivery,
    SpokenDeliveryState,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import CaptureFacts, admit_channel
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeTranscriptArchiveWriter,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import (
        Conversation,
        EpisodeCaptureReport,
        MemoryWrite,
        TranscriptEntry,
    )
    from ai_assistant.orchestration.activation_state import ActivationState

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_UUID = "1bed03e1-3b38-4e67-a2e4-6f6bf9c97eb1"
_ADDRESS = f"activation:{_UUID}"


async def _drain(work: Awaitable[None]) -> None:
    await work


class CommitThenFail(FakeMemoryStore):
    """A store that can commit before the caller observes a failure."""

    def __init__(self, *, cancelled: bool = False) -> None:
        super().__init__(now=lambda: _AT)
        self.after: Callable[[], Awaitable[None]] | None = None
        self.cancelled = cancelled

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
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


class DeletingArchive(FakeTranscriptArchiveWriter):
    """An archive whose append is followed by the conversation's deletion."""

    def __init__(self) -> None:
        super().__init__()
        self.after: Callable[[], Awaitable[None]] | None = None

    async def append(self, entry: TranscriptEntry) -> None:
        await super().append(entry)
        if self.after is not None:
            await self.after()


class Wiring:
    """The production writer with three observable canonical stores."""

    def __init__(
        self,
        *,
        memory: FakeMemoryStore | None = None,
        conversations: FakeConversationStore | None = None,
        archive_enabled: bool = True,
    ) -> None:
        self.memory = memory if memory is not None else FakeMemoryStore(now=lambda: _AT)
        self.conversations = (
            conversations if conversations is not None else FakeConversationStore(now=lambda: _AT)
        )
        self.archive = DeletingArchive()
        self.writer = ActivationWriter(
            memory=self.memory,
            conversations=self.conversations,
            archive=self.archive,
            archive_enabled=archive_enabled,
            retention=timedelta(days=30),
            now=lambda: _AT,
        )

    async def state(
        self,
        *,
        eligible: bool = True,
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
        if eligible:
            assert conversation is not None
            state.facts = CaptureFacts(
                asked="exact request",
                response="the complete reply",
                disposition=ExchangeDisposition.NO_ACTION_NEEDED,
                modality=Modality.TEXT,
                supplied_withheld=False,
                derived_from_external=False,
                parked=parked,
                delivery=delivery,
            )
            state.response = "the complete reply"
            state.response_kind = EpisodeResponseKind.CONVERSATION_REPLY
        return state

    async def write(self, state: ActivationState, *, limit: int = 1024) -> EpisodeCaptureReport:
        """Use a fixed end reading, rebuilt from the state as the coordinator does."""
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
    entry = wiring.archive.recorded[_ADDRESS]
    assert entry.asked == "exact request", "the archive's half is threaded, not the content"
    assert entry.replied == "the complete reply"
    assert entry.occurred_at == _AT


class CommitThen(FakeMemoryStore):
    """A store that runs a hook once its write has committed, and then answers."""

    def __init__(self) -> None:
        super().__init__(now=lambda: _AT)
        self.after: Callable[[], Awaitable[None]] | None = None

    async def write_atomic(self, writes: Sequence[MemoryWrite]) -> Sequence[str]:
        written = await super().write_atomic(writes)
        if self.after is not None:
            await self.after()
        return written


async def test_a_record_forgotten_between_episode_and_entry_leaves_no_entry() -> None:
    """ADR-0225 §5 under §7:1: the user forgot the record before its entry landed.

    ``forget`` marks the capture, its discard finds nothing and its delete takes the
    episode; the writer then appends the entry, sees the mark, calls no
    ``record_turn`` and destroys the entry through the fence.
    """
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    state = await wiring.state()

    async def forgotten() -> None:
        wiring.writer.forgetting(_ADDRESS)
        await wiring.archive.discard(_ADDRESS)
        await memory.delete(_ADDRESS)

    memory.after = forgotten
    report = await wiring.write(state)

    assert report.state == "degraded"
    assert wiring.archive.recorded == {}
    assert await wiring.memory.get(_ADDRESS) is None
    assert await wiring.last_turn_at(state) is None, "no record_turn for a forgotten episode"
    assert state.recorded_episode_id is None


class Undiscardable(DeletingArchive):
    """An archive whose discard fails, as a broken backing's would."""

    async def discard(self, address: str) -> bool:
        raise TranscriptArchiveError("private provider diagnostics")


async def test_a_record_forgotten_before_its_entry_is_never_given_one() -> None:
    """ADR-0225 §5: a marked capture writes no entry, so no failed discard can strand one."""
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    wiring.archive = Undiscardable()
    wiring.writer._archive = wiring.archive
    state = await wiring.state()

    async def forgotten() -> None:
        wiring.writer.forgetting(_ADDRESS)
        await memory.delete(_ADDRESS)

    memory.after = forgotten
    report = await wiring.write(state)

    assert report.state == "degraded"
    assert wiring.archive.recorded == {}, "no entry was written for a forgotten record"
    assert await wiring.memory.get(_ADDRESS) is None
    assert await wiring.last_turn_at(state) is None


async def test_an_episode_forgotten_before_it_commits_is_destroyed_by_its_capture() -> None:
    """ADR-0225 §5: ``forget`` found nothing yet, so the capture destroys what it writes."""
    memory = CommitThen()
    wiring = Wiring(memory=memory)
    state = await wiring.state()
    wiring.writer.forgetting(_ADDRESS)  # before any capture: marks nothing

    async def marked() -> None:
        wiring.writer.forgetting(_ADDRESS)

    memory.after = marked
    report = await wiring.write(state)

    assert report.state == "degraded"
    assert wiring.archive.recorded == {}
    assert await wiring.on_channel(state) == []
    assert await wiring.last_turn_at(state) is None
    assert wiring.writer._in_flight == {}, "the capture stopped being tracked"


async def test_an_expired_episode_keeps_its_transcript() -> None:
    """ADR-0225 §5: expiry removes nothing from the archive, and no read stands in for forget.

    The episode's retention has already passed when the entry is written; the capture
    is unmarked, so the entry, the turn and the report stand.
    """
    later = _AT + timedelta(seconds=5)
    wiring = Wiring(memory=FakeMemoryStore(now=lambda: later))
    wiring.writer._retention = timedelta(seconds=1)
    state = await wiring.state()
    report = await wiring.write(state)

    assert report.state == "recorded"
    assert _ADDRESS in wiring.archive.recorded
    assert await wiring.memory.get(_ADDRESS) is None, "the episode reads as expired"
    assert await wiring.last_turn_at(state) == _AT


async def test_the_archive_switch_off_records_the_episode_and_the_turn_and_no_entry() -> None:
    """ADR-0225 §6: with the archive switched off the capture is otherwise unchanged."""
    wiring = Wiring(archive_enabled=False)
    state = await wiring.state()
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id == _ADDRESS
    assert wiring.archive.recorded == {}
    assert await wiring.on_channel(state) == [_ADDRESS]
    assert state.recorded_episode_id == _ADDRESS
    assert await wiring.last_turn_at(state) == _AT


@pytest.mark.parametrize("standalone", [False, True])
async def test_a_capture_with_no_capture_facts_has_no_archive_entry_and_is_in_history(
    standalone: bool,
) -> None:
    """A pass that ends before capture is still on its channel, and in its history.

    ADR-0284 §6:2 retires the eligibility axis (superseding ADR-0283 §7:5): the episode
    is read by history like any other. Its ``content`` is §7's one rule, as on every
    other episode, and it owes no transcript entry.
    """
    wiring = Wiring()
    state = await wiring.state(eligible=False, standalone=standalone)
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id == _ADDRESS
    episode = await wiring.memory.get(_ADDRESS)
    assert isinstance(episode, EpisodicMemory)
    assert episode.content == episode_content(episode)
    assert episode.disposition is None
    assert episode.processing_record is not None
    assert wiring.archive.recorded == {}
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
    assert wiring.archive.recorded == {}
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
    assert _ADDRESS in wiring.archive.recorded
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
    fails), on a conversation deleted meanwhile, leaves no episode and no archive entry."""
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
    assert wiring.archive.recorded == {}
    assert state.recorded_episode_id is None


async def test_an_indeterminate_write_on_a_standing_conversation_writes_no_archive_entry() -> None:
    """§7:4: no archive entry and no ``record_turn`` after an indeterminate write, and
    the episode it may have left stays where the conversation stands."""
    wiring = Wiring(memory=CommitThenFail())
    state = await wiring.state()
    assert (await wiring.write(state)).state == "degraded"
    assert wiring.archive.recorded == {}
    assert await wiring.on_channel(state) == [_ADDRESS]
    assert await wiring.last_turn_at(state) is None


async def test_a_conversation_deleted_before_record_turn_keeps_neither_write() -> None:
    """§7:2, §14:2: ``record_turn``'s ``None`` deletes the episode and discards the
    archive entry, and the capture is degraded."""
    wiring = Wiring()
    state = await wiring.state()

    async def deleted() -> None:
        await wiring.conversations.stamp_deleted(str(state.conversation_id))

    wiring.archive.after = deleted
    report = await wiring.write(state)
    assert report.state == "degraded"
    assert report.episode_id is None
    assert await wiring.memory.export() == []
    assert await wiring.on_channel(state) == []
    assert wiring.archive.recorded == {}


async def test_a_write_known_not_to_have_committed_reaches_nothing_else() -> None:
    """§7:3: no archive entry and no ``record_turn``, and no compensation that could
    delete the record already holding the address."""
    wiring = Wiring(memory=Conflicting(now=lambda: _AT))
    state = await wiring.state()
    assert (await wiring.write(state)).state == "degraded"
    assert wiring.archive.recorded == {}
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
    first = await wiring.state(eligible=False, standalone=True)
    report = await wiring.write(first)
    assert report.episode_id is not None
    before = await wiring.memory.get(report.episode_id)
    repeated = await wiring.state(eligible=False, standalone=True)
    assert (await wiring.write(repeated)).state == "degraded"
    assert await wiring.memory.get(report.episode_id) == before
    assert len(await wiring.memory.export()) == 1
