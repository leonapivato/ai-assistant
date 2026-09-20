"""Ended-activation capture ordering, uncertainty, and deletion compensation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from structlog.testing import capture_logs

from ai_assistant.core.errors import ConversationStoreError, MemoryStoreError
from ai_assistant.core.types import (
    ChannelContext,
    ChannelIdentity,
    ChannelInput,
    EpisodeResponseKind,
    EpisodicMemory,
    ExchangeDisposition,
    Modality,
    NewConversation,
    RecordedChannelTrigger,
    TextChannelPayload,
    WholeTextReply,
)
from ai_assistant.orchestration.activation_state import CaptureFacts, admit_channel
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.testing import (
    FakeConversationStore,
    FakeMemoryStore,
    FakeTranscriptArchiveWriter,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.types import Conversation, EpisodeCaptureReport, MemoryWrite
    from ai_assistant.orchestration.activation_state import ActivationState

_AT = datetime(2026, 9, 20, tzinfo=UTC)
_UUID = "1bed03e1-3b38-4e67-a2e4-6f6bf9c97eb1"


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


class VerificationFailure(FakeConversationStore):
    """A live index whose post-write verification is unavailable."""

    async def get(self, conversation_id: str) -> Conversation | None:
        raise ConversationStoreError("private provider diagnostics")


class Wiring:
    """The production writer with three observable canonical stores."""

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
        self.archive = FakeTranscriptArchiveWriter()
        self.writer = ActivationWriter(
            memory=self.memory,
            conversations=self.conversations,
            archive=self.archive,
            archive_enabled=True,
            retention=timedelta(days=30),
            now=lambda: _AT,
        )

    async def state(self, *, eligible: bool = True, standalone: bool = False) -> ActivationState:
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
                content="canonical exchange",
                asked="exact request",
                response="the complete reply",
                disposition=ExchangeDisposition.NO_ACTION_NEEDED,
                modality=Modality.TEXT,
                supplied_withheld=False,
                derived_from_external=False,
                parked=None,
                delivery=None,
            )
            state.response = "the complete reply"
            state.response_kind = EpisodeResponseKind.CONVERSATION_REPLY
        return state

    async def write(self, state: ActivationState, *, limit: int = 1024) -> EpisodeCaptureReport:
        """Use a fixed end reading and rebuild metadata after the index resolves."""
        return await self.writer.write(
            state,
            state.processing(_AT, None),
            payload_limit=limit,
            checked_output=lambda: state.processing(_AT, None),
            drain=_drain,
        )


async def test_ended_exchange_uses_one_index_address_and_shared_capture_timestamp() -> None:
    wiring = Wiring()
    state = await wiring.state()
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id is not None
    row = (await wiring.conversations.turns(str(state.conversation_id)))[0]
    episode = await wiring.memory.get(report.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.id == row.episode_id == state.index_episode_id
    assert episode.occurred_at == row.occurred_at == _AT
    assert episode.expires_at == _AT + timedelta(days=30)
    assert episode.processing_record == state.processing(_AT, None)
    assert episode.outcome == "the complete reply"
    assert wiring.archive.recorded[episode.id].asked == "exact request"


@pytest.mark.parametrize("standalone", [False, True])
async def test_inspection_only_capture_has_no_archive_or_eligible_history(standalone: bool) -> None:
    wiring = Wiring()
    state = await wiring.state(eligible=False, standalone=standalone)
    report = await wiring.write(state)
    assert report.state == "recorded"
    assert report.episode_id is not None
    episode = await wiring.memory.get(report.episode_id)
    assert isinstance(episode, EpisodicMemory)
    assert episode.content == "Recorded activation; inspect its processing record."
    assert episode.disposition is None
    assert episode.processing_record is not None
    assert not episode.processing_record.model_eligible
    assert wiring.archive.recorded == {}
    if standalone:
        assert report.episode_id == f"activation:{_UUID}"
        assert await wiring.conversations.recent() == []
    else:
        assert (
            await wiring.conversations.turns(str(state.conversation_id), model_eligible_only=True)
            == []
        )


async def test_complete_record_bound_refuses_before_index_or_content_writes() -> None:
    wiring = Wiring()
    state = await wiring.state()
    assert isinstance(state.trigger, RecordedChannelTrigger)
    state.trigger = state.trigger.model_copy(
        update={"payload": state.trigger.payload.model_copy(update={"text": "x" * 100000})}
    )
    assert (await wiring.write(state)).state == "degraded"
    assert await wiring.conversations.turns(str(state.conversation_id)) == []
    assert await wiring.memory.export() == []
    assert wiring.archive.recorded == {}


async def test_verification_uncertainty_cannot_claim_recorded() -> None:
    wiring = Wiring(conversations=VerificationFailure(now=lambda: _AT))
    state = await wiring.state()
    with capture_logs() as logs:
        report = await wiring.write(state)
    assert report.state == "degraded"
    assert report.episode_id is not None
    assert await wiring.memory.get(report.episode_id) is not None
    assert logs == [
        {
            "event": "activation_capture_degraded",
            "stage": "verify",
            "reason": "uncertain",
            "log_level": "warning",
        }
    ]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_commit_then_failure_still_drains_deletion_compensation(cancelled: bool) -> None:
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
    assert wiring.archive.recorded == {}
    assert state.index_episode_id is None


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
