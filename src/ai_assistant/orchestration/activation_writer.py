"""Post-processing episode writes and their conversation deletion fence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.episode_encoding import canonical_json
from ai_assistant.core.errors import MemoryStoreConflictError
from ai_assistant.core.types import (
    Capture,
    ChannelIdentity,
    EpisodeCaptureReport,
    EpisodicMemory,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    TranscriptEntry,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime, timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ConversationStore, MemoryStore, TranscriptArchiveWriter
    from ai_assistant.core.types import ConversationTurn, EpisodeProcessingRecord
    from ai_assistant.orchestration.activation_state import ActivationState

_log = structlog.get_logger(__name__)
_INSPECTION_CONTENT = "Recorded activation; inspect its processing record."


def capture_loss(stage: str, reason: str) -> None:
    """Log only code-owned vocabulary, never exception or activation material."""
    _log.warning("activation_capture_degraded", stage=stage, reason=reason)


@dataclass
class _Writes:
    episode_possible: bool = False
    archive_possible: bool = False
    episode_confirmed: bool = False
    archive_confirmed: bool = False
    verified: bool = False


class ActivationWriter:
    """Write once at an index-owned address, then drain deletion verification."""

    def __init__(  # noqa: PLR0913 — the same lifecycle collaborators and configuration
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        archive: TranscriptArchiveWriter,
        archive_enabled: bool,
        retention: timedelta | None,
        now: Clock,
    ) -> None:
        """Receive only the lifecycle's injected store contracts and capture settings."""
        self._conversations = conversations
        self._memory = memory
        self._archive = archive
        self._archive_enabled = archive_enabled
        self._retention = retention
        self._now = checked_clock(now, owner="ActivationWriter")

    async def write(
        self,
        state: ActivationState,
        processing: EpisodeProcessingRecord,
        *,
        payload_limit: int,
        checked_output: Callable[[], EpisodeProcessingRecord],
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> EpisodeCaptureReport:
        """Perform no work beyond final metadata, one capture, and its safety fence."""
        if isinstance(state.trigger, RecordedResumeTrigger) and state.conversation_id is None:
            capture_loss("association", "unresolved")
            return state.degraded_report()
        try:
            now = self._now()
            # SQLite's existing ordinal domain is [1, 2**63). This is a length
            # reservation, never a prediction or reservation of the next row.
            address = (
                f"activation:{processing.activation_id}"
                if state.conversation_id is None
                else f"conv:{state.conversation_id}:{2**63 - 1}"
            )
            preflight = processing
            if state.conversation_id is not None:
                preflight = processing.model_copy(
                    update={
                        "trigger": processing.trigger.model_copy(
                            update={
                                "channel": ChannelIdentity(
                                    channel_type="conversation",
                                    instance_id=state.conversation_id,
                                )
                            }
                        )
                    }
                )
            self._bounded(state, preflight, address, now, payload_limit)
        except Exception:
            capture_loss("preflight", "invalid_or_oversized")
            return state.degraded_report()
        turn = None
        if state.conversation_id is not None:
            try:
                facts = state.facts
                turn = await self._conversations.append(
                    state.conversation_id,
                    occurred_at=now,
                    parked=None if facts is None else facts.parked,
                    delivery=None if facts is None else facts.delivery,
                    model_eligible=processing.model_eligible,
                )
                state.index_episode_id = turn.episode_id
                state.resolved_conversation(turn.conversation_id)
                address = turn.episode_id
            except Exception:
                capture_loss("append", "failed")
                return state.degraded_report()
        try:
            processing = checked_output()
            episode = self._bounded(state, processing, address, now, payload_limit)
        except Exception:
            capture_loss("preflight", "invalid_or_oversized")
            return state.degraded_report()
        writes = _Writes()
        owed = turn is not None and state.facts is not None and self._archive_enabled
        try:
            if owed and turn is not None:
                await self._archive_once(state, turn, writes)
            await self._episode_once(episode, writes)
        finally:
            if turn is not None and (writes.episode_possible or writes.archive_possible):
                await drain(self._verify(state, turn, writes))
        if (
            writes.episode_confirmed
            and (not owed or writes.archive_confirmed)
            and (turn is None or writes.verified)
        ):
            return EpisodeCaptureReport(
                activation_id=processing.activation_id, episode_id=address, state="recorded"
            )
        return state.degraded_report()

    async def _archive_once(
        self, state: ActivationState, turn: ConversationTurn, writes: _Writes
    ) -> None:
        facts = state.facts
        assert facts is not None  # noqa: S101 — only canonical capture facts owe an archive entry
        try:
            entry = TranscriptEntry(
                address=turn.episode_id,
                conversation_id=turn.conversation_id,
                ordinal=turn.ordinal,
                occurred_at=turn.occurred_at,
                asked=facts.asked,
                replied=facts.response,
                disposition=facts.disposition,
            )
            writes.archive_possible = True
            await self._archive.append(entry)
            writes.archive_confirmed = True
        except Exception:
            capture_loss("archive", "failed")

    async def _episode_once(self, episode: EpisodicMemory, writes: _Writes) -> None:
        try:
            writes.episode_possible = True
            await self._memory.write_atomic(
                [MemoryWrite(record=episode, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )
            writes.episode_confirmed = True
        except MemoryStoreConflictError:
            # A known atomic collision did not create our record. Compensation
            # must not delete someone else's pre-existing record at this address.
            writes.episode_possible = False
            capture_loss("episode", "conflict")
        except Exception:
            capture_loss("episode", "failed")

    async def _verify(
        self, state: ActivationState, turn: ConversationTurn, writes: _Writes
    ) -> None:
        try:
            standing = await self._conversations.get(turn.conversation_id)
        except Exception:
            capture_loss("verify", "uncertain")
            return
        if standing is not None:
            writes.verified = True
            return
        state.index_episode_id = None
        if writes.archive_possible:
            try:
                await self._archive.discard(turn.episode_id)
            except Exception:
                capture_loss("compensate_archive", "failed")
                # Keep the memory record reachable until archive destruction
                # succeeds, as on the existing explicit-forget path.
                return
        if writes.episode_possible:
            try:
                await self._memory.delete(turn.episode_id)
            except Exception:
                capture_loss("compensate_episode", "failed")

    def _bounded(
        self,
        state: ActivationState,
        processing: EpisodeProcessingRecord,
        address: str,
        now: datetime,
        payload_limit: int,
    ) -> EpisodicMemory:
        facts = state.facts
        modality = (
            state.trigger.payload.modality
            if isinstance(state.trigger, RecordedChannelTrigger)
            else Modality.TEXT
        )
        episode = EpisodicMemory(
            id=address,
            content=_INSPECTION_CONTENT if facts is None else facts.content,
            occurred_at=now,
            outcome=state.response,
            disposition=None if facts is None else facts.disposition,
            capture=Capture(modality=modality if facts is None else facts.modality),
            expires_at=None if self._retention is None else now + self._retention,
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.9,
                last_updated=now,
                derived_from_external=facts is not None and facts.derived_from_external,
            ),
            placement=(
                Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=now)
                if facts is not None and facts.supplied_withheld
                else Placement()
            ),
            processing_record=processing,
        )
        if len(canonical_json(episode)) > 8 * payload_limit + 65536:
            raise ValueError("activation record exceeds its capture bound")
        return episode
