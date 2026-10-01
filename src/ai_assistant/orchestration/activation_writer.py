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
    from ai_assistant.core.types import EpisodeProcessingRecord
    from ai_assistant.orchestration.activation_state import ActivationState, CaptureFacts

_log = structlog.get_logger(__name__)
_INSPECTION_CONTENT = "Recorded activation; inspect its processing record."


def _content(facts: CaptureFacts | None, processing: EpisodeProcessingRecord) -> str:
    """What an episode is embedded on: its canonical rendering, or its understanding.

    ADR-0281 §3: an inspection-only record whose activation recorded an understanding
    is embedded on the latest one's ``meaning`` — the stage's digest of the input,
    never the raw input — so recall can find it by what it was about. One with none
    keeps ADR-0275 §8:5's constant. The trigger's input and context are never
    embedded.
    """
    if facts is not None:
        return facts.content
    if processing.understanding:
        return processing.understanding[-1].meaning
    return _INSPECTION_CONTENT


def capture_loss(stage: str, reason: str) -> None:
    """Log only code-owned vocabulary, never exception or activation material."""
    _log.warning("activation_capture_degraded", stage=stage, reason=reason)


@dataclass
class _Writes:
    """What one capture's writes are known to have done, for its fence and its report."""

    #: The episode write was attempted and is not known to have failed uncommitted:
    #: an episode at this address may exist, so a deleted conversation owes its delete.
    episode_possible: bool = False
    episode_confirmed: bool = False
    archive_possible: bool = False
    archive_confirmed: bool = False
    #: ``record_turn`` returned the conversation: it stands, and it knows the turn.
    verified: bool = False
    #: ``record_turn`` returned ``None``: the conversation is absent or stamped.
    gone: bool = False
    #: A record-scoped ``forget`` named this address while the capture was in flight
    #: (:meth:`ActivationWriter.forgetting`).
    forgotten: bool = False


class ActivationWriter:
    """Write one episode at its admission address, then verify and fence it (ADR-0283 §7)."""

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
        #: The captures in flight, by address, so a ``forget`` can reach one.
        self._in_flight: dict[str, list[_Writes]] = {}

    def forgetting(self, address: str) -> None:
        """Tell any capture in flight at ``address`` that its record is being forgotten.

        ADR-0283 §7:1 writes a conversational episode before its archive entry, so a
        record-scoped ``forget`` (ADR-0225 §5) landing between the two would find no
        entry to discard, delete the episode, and leave the entry to be written for a
        record the user was told was gone. ``forget`` calls this **before** its
        discard: an entry appended before that discard is destroyed by it, and a
        capture that appends after it sees the mark, calls no ``record_turn``, and
        destroys its own entry and episode through the fence.

        The coordination is in-process, which is the whole of the hub's: one resident
        process per data directory owns both the writer and ``forget``. It reads no
        store, so neither a failing read nor an episode's ordinary expiry can stand in
        for the user's act.
        """
        for writes in self._in_flight.get(address, ()):
            writes.forgotten = True

    async def write(
        self,
        state: ActivationState,
        processing: EpisodeProcessingRecord,
        *,
        payload_limit: int,
        checked_output: Callable[[], EpisodeProcessingRecord],
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> EpisodeCaptureReport:
        """Write the episode, then the archive entry, then ``record_turn`` (ADR-0283 §7).

        **The address is fixed at admission**: ``activation:<activation_id>`` on every
        channel (§2), so it is sized, written and reported as one value and nothing is
        allocated by a store first. A conversational episode is written on the
        conversation's channel; a standalone one is written alone.

        **For a conversational capture the order is the protocol** (§7:1): the episode,
        insert-if-absent; then, only where it is confirmed written, the archive entry
        where one is owed; then ``record_turn``, which is the deletion verification
        (§7:2). A ``None`` from it means the conversation was deleted, and the fence
        discards the archive entry and deletes the episode.

        **Where the episode write is known not to have committed** — the store's
        conflict, which created nothing at this address — no archive entry is written
        and ``record_turn`` is not called (§7:3). **Where its outcome is
        indeterminate** — any other failure, cancellation and timeout included — no
        archive entry is written either, and the fence re-reads the conversation and
        deletes the episode by id where it is stamped or absent (§7:4). Either way the
        capture is reported degraded.

        **The fence runs through ``drain``** (ADR-0275 §8:11), on every path where an
        episode may have landed and the conversation was not verified standing, so a
        cancellation of this call cannot strand an episode on a conversation the user
        deleted.

        **A record the user forgets while it is captured leaves nothing** (ADR-0225
        §5): where :meth:`forgetting` marked this capture before ``record_turn``, the
        turn is not recorded and the fence destroys the entry and the episode.
        """
        if isinstance(state.trigger, RecordedResumeTrigger) and state.conversation_id is None:
            capture_loss("association", "unresolved")
            return state.degraded_report()
        conversation_id = state.conversation_id
        facts = state.facts
        if facts is not None and facts.parked is not None:
            # ADR-0283 §3:4: the binding this activation's own step parked, which is
            # what a later resume finds its conversation through (§5).
            state.relate(parks=facts.parked)
        if conversation_id is not None:
            # ADR-0275 §4:5 as ADR-0283 partially supersedes it: a conversational
            # channel names the conversation the episode is written for.
            state.resolved_conversation(conversation_id)
        try:
            now = self._now()
            address = f"activation:{processing.activation_id}"
            preflight = processing.model_copy(
                update={"trigger": state.trigger, "links": state.links}
            )
            self._bounded(state, preflight, address, now, payload_limit)
            processing = checked_output()
            episode = self._bounded(state, processing, address, now, payload_limit)
        except Exception:
            capture_loss("preflight", "invalid_or_oversized")
            return state.degraded_report()
        writes = _Writes()
        owed = conversation_id is not None and facts is not None and self._archive_enabled
        self._in_flight.setdefault(address, []).append(writes)
        try:
            await self._episode_once(episode, writes)
            if conversation_id is not None and writes.episode_confirmed:
                if owed and not writes.forgotten:
                    # A record already forgotten is never given an entry (ADR-0225 §5).
                    await self._archive_once(state, conversation_id, episode, writes)
                if not writes.forgotten:
                    await self._record_turn(state, conversation_id, episode, writes)
        finally:
            try:
                if (
                    conversation_id is not None
                    and (writes.episode_possible or writes.archive_possible)
                    and not writes.verified
                ):
                    await drain(self._fence(conversation_id, address, writes))
            finally:
                self._settled(address, writes)
        if (
            writes.episode_confirmed
            and (not owed or writes.archive_confirmed)
            and (conversation_id is None or writes.verified)
        ):
            return EpisodeCaptureReport(
                activation_id=processing.activation_id, episode_id=address, state="recorded"
            )
        return state.degraded_report()

    async def _archive_once(
        self,
        state: ActivationState,
        conversation_id: str,
        episode: EpisodicMemory,
        writes: _Writes,
    ) -> None:
        """Write the transcript entry at the episode's own address, with no ordinal."""
        facts = state.facts
        assert facts is not None  # noqa: S101 — only canonical capture facts owe an archive entry
        try:
            entry = TranscriptEntry(
                address=episode.id,
                conversation_id=conversation_id,
                occurred_at=episode.occurred_at,
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

    async def _record_turn(
        self,
        state: ActivationState,
        conversation_id: str,
        episode: EpisodicMemory,
        writes: _Writes,
    ) -> None:
        """Tell the conversation its episode landed, which is the verification (§7:2)."""
        facts = state.facts
        try:
            standing = await self._conversations.record_turn(
                conversation_id,
                episode_id=episode.id,
                occurred_at=episode.occurred_at,
                delivery=None if facts is None else facts.delivery,
            )
        except Exception:
            # Indeterminate, so the fence re-reads the conversation (§7:4's posture).
            capture_loss("record_turn", "failed")
            return
        if standing is None:
            writes.gone = True
            return
        writes.verified = True
        state.recorded_episode_id = episode.id

    def _settled(self, address: str, writes: _Writes) -> None:
        """Stop tracking one capture at ``address`` once its fence has run."""
        held = self._in_flight.get(address)
        if held is None:
            return
        held[:] = [one for one in held if one is not writes]
        if not held:
            del self._in_flight[address]

    async def _fence(self, conversation_id: str, address: str, writes: _Writes) -> None:
        """Destroy what this capture wrote where its conversation is gone (§7:2, §7:4).

        ``record_turn``'s ``None`` is the conversation's own answer and needs no
        re-read. Every other unverified path re-reads the conversation, and an
        unreadable one leaves the writes standing: where it was in fact stamped,
        recovery's sweep finds the episode on its channel while the tombstone stands
        (ADR-0283 §8).

        **The archive entry goes first**, on ADR-0225 §5's rule that the residue of a
        partial failure must be one the user can still reach and destroy.

        **A forgotten capture is destroyed whatever its conversation's state**,
        because the user's act named the record itself (ADR-0225 §5).
        """
        if not writes.gone and not writes.forgotten:
            try:
                standing = await self._conversations.get(conversation_id)
            except Exception:
                capture_loss("verify", "uncertain")
                return
            if standing is not None:
                return
        if writes.archive_possible and not await self._discard(address):
            # Keep the memory record reachable until archive destruction succeeds,
            # as on the existing explicit-forget path.
            return
        if writes.episode_possible:
            try:
                await self._memory.delete(address)
            except Exception:
                capture_loss("compensate_episode", "failed")

    async def _discard(self, address: str) -> bool:
        """Discard this capture's archive entry, answering whether that succeeded."""
        try:
            await self._archive.discard(address)
        except Exception:
            capture_loss("compensate_archive", "failed")
            return False
        return True

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
            content=_content(facts, processing),
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
