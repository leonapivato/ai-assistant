"""Seeding a conversation's channel with episodes, for the orchestration suites.

Since ADR-0283 a conversation's history *is* the episodes on its channel — the
``conversation`` channel whose instance is the conversation's id — so a case that
needs a conversation with a past seeds that channel directly rather than through a
turn index that no longer exists. :func:`conversation_episode` builds the smallest
episode a channel read admits: a completed channel activation whose recorded
trigger's ``channel`` names the conversation (ADR-0283 §3).

A case about *how* the writer records an episode drives the writer instead; this is
for the many that need history and are about something else.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ai_assistant.core.types import (
    ActivationLinks,
    ChannelContext,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    MemorySource,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedTextInput,
    UnderstandingOmission,
    WholeTextReply,
)
from ai_assistant.orchestration.conversations import conversation_channel
from ai_assistant.testing.activation import ended_pass

if TYPE_CHECKING:
    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import ParkedBinding

#: The instant a seeded episode carries unless a case says otherwise.
SEEDED_AT = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)


def conversation_episode(  # noqa: PLR0913 — one keyword per axis a seeding case varies
    conversation_id: str,
    episode_id: str,
    *,
    content: str | None = None,
    occurred_at: datetime = SEEDED_AT,
    eligible: bool = True,
    parks: ParkedBinding | None = None,
    **fields: Any,
) -> EpisodicMemory:
    """An episode on ``conversation_id``'s channel, as ADR-0283 §3 reads one.

    Args:
        conversation_id: The conversation whose channel the episode is on.
        episode_id: The record id. Production mints ``activation:<id>`` (§2); a case
            may pick any id, since a channel read keys on the channel and not on it.
        content: The episode's text; a default naming the id where omitted.
        occurred_at: The instant the episode records.
        eligible: Whether the pass completed. ``False`` records a failed pass carrying
            the retired ``model_eligible=False`` flag, which no read filters on any
            more (ADR-0284 §6:2): the episode is on the channel and read like any other.
        parks: The binding the activation's step parked (§3:4), for a resume case.
        **fields: Further ``EpisodicMemory`` fields, applied last (``expires_at``,
            ``validity``, ``placement`` ...).

    Returns:
        The episode, ready to ``add`` to a ``MemoryStore``.
    """
    channel = conversation_channel(conversation_id)
    record = EpisodicMemory(
        id=episode_id,
        content=content if content is not None else f"the user said something in {episode_id}",
        occurred_at=occurred_at,
        provenance=Provenance(
            source=MemorySource.OBSERVED, confidence=0.9, last_updated=occurred_at
        ),
        processing_record=EpisodeProcessingRecord(
            activation_id=episode_id.removeprefix("activation:"),
            started_at=occurred_at,
            ended_at=occurred_at,
            trigger=RecordedChannelTrigger(
                target=channel,
                channel=channel,
                payload=RecordedTextInput(text="exact input"),
                context=ChannelContext(),
                conversation=None,
                reply=WholeTextReply(),
            ),
            status=ProcessingStatus.COMPLETED if eligible else ProcessingStatus.FAILED,
            reason=ProcessingReason.RETURNED if eligible else ProcessingReason.PROCESSING_FAILED,
            response_kind=EpisodeResponseKind.NONE,
            model_eligible=eligible,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(occurred_at),
            links=ActivationLinks(parks=parks),
        ),
    )
    return record.model_copy(update=fields) if fields else record


async def channel_records(memory: MemoryStore, conversation_id: str) -> list[EpisodicMemory]:
    """Every live episode on ``conversation_id``'s channel, in number order.

    Every episode the store holds on the channel, failed passes included.
    """
    page = await memory.channel_episodes(conversation_channel(conversation_id), limit=1000)
    return [entry.record for entry in page.entries]


async def channel_ids(memory: MemoryStore, conversation_id: str) -> list[str]:
    """The ids of every live episode on ``conversation_id``'s channel, in number order."""
    held = await memory.channel_episode_ids(conversation_channel(conversation_id), limit=1000)
    return [entry.episode_id for entry in held]


async def channel_numbers(memory: MemoryStore, conversation_id: str) -> dict[str, int]:
    """Each live episode on ``conversation_id``'s channel, id to number, in number order."""
    held = await memory.channel_episode_ids(conversation_channel(conversation_id), limit=1000)
    return {entry.episode_id: entry.number for entry in held}
