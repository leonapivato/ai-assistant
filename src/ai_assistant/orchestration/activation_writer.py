"""The episode's writes: admission, appends, the freeze, and the restart's close.

ADR-0286 writes an activation's episode at admission (§2), replaces it with a record
that extends it as each stage ends (§3), and freezes it with the end entry (§4);
``record_turn`` follows the freeze (§4:4, as ADR-0287 left it). Any capture failure
before the freeze is confirmed ends capture and deletes the episode (§5). A restart
closes the episodes a dead process left open (§7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.episode_encoding import canonical_json, episode_content, episode_extends
from ai_assistant.core.errors import MemoryStoreConflictError, MemoryStoreStaleError
from ai_assistant.core.types import (
    Capture,
    ChannelIdentity,
    ControllerRule,
    ControllerStage,
    EpisodeCaptureReport,
    EpisodeProcessingRecord,
    EpisodicMemory,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    StageOutcome,
    UnderstandingOmission,
)
from ai_assistant.orchestration.activation_state import EpisodeProgress
from ai_assistant.orchestration.controller import StageRecord

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import ConversationStore, MemoryStore
    from ai_assistant.core.types import MemoryRecord, RecordedActivationTrigger
    from ai_assistant.orchestration.activation_state import ActivationState

_log = structlog.get_logger(__name__)

#: How many open episodes the restart's close reads per page (ADR-0286 §7, §12:1).
_OPEN_PAGE = 100


def _on_its_conversation(trigger: RecordedActivationTrigger) -> RecordedActivationTrigger:
    """``trigger`` on the conversation it targets, where a dead pass had not yet named it.

    A conversational pass names the conversation its episode is written for once the
    conversation is resolved (ADR-0275 §4:5 as ADR-0283 reads it), so a process that
    died before that left an open episode on no channel, its target alone naming the
    conversation. The restart's close puts it on that place: ADR-0293 §9:2 has the
    current state show *interrupted* after a restart, and the place's episodes are
    where it is read, as forgetting the conversation walks them (§2:4). Setting an
    unset ``channel`` extends the record (ADR-0286 §3:3).
    """
    if not isinstance(trigger, RecordedChannelTrigger) or trigger.channel is not None:
        return trigger
    target = trigger.target
    if not isinstance(target, ChannelIdentity) or target.channel_type != "conversation":
        return trigger
    return trigger.model_copy(update={"channel": target})


def capture_loss(stage: str, reason: str) -> None:
    """Log only code-owned vocabulary, never exception or activation material."""
    _log.warning("activation_capture_degraded", stage=stage, reason=reason)


@dataclass
class _Writes:
    """What a frozen episode's ``record_turn`` is known to have done."""

    #: ``record_turn`` returned the conversation: it stands, and it knows the turn.
    verified: bool = False


class ActivationWriter:
    """Write one episode at its admission address, extend it, freeze it, fence it."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        retention: timedelta | None,
        now: Clock,
    ) -> None:
        """Receive only the lifecycle's injected store contracts and capture settings."""
        self._conversations = conversations
        self._memory = memory
        self._retention = retention
        self._now = checked_clock(now, owner="ActivationWriter")
        #: The captures in flight, by address, from the admission write until each
        #: settles — so a ``forget`` can reach one and a restart's close passes over it.
        self._in_flight: dict[str, list[EpisodeProgress]] = {}

    def forgetting(self, address: str) -> None:
        """Tell any capture in flight at ``address`` that its record is being forgotten.

        ``forget`` calls this **before** its deletion, in the same call (ADR-0286 §8:1,
        as ADR-0287 §4 keeps it). The capture's next write after the mark writes
        nothing: it deletes the episode by its id and ends capture (§8:2). A capture
        whose freeze is already confirmed calls no ``record_turn`` after the mark, and
        destroys its episode through the fence.

        The coordination is in-process, which is the whole of the hub's: one resident
        process per data directory owns both the writer and ``forget``. It reads no
        store, so neither a failing read nor an episode's ordinary expiry can stand in
        for the user's act.
        """
        for progress in self._in_flight.get(address, ()):
            progress.forgotten = True

    def holds(self, address: str) -> bool:
        """Whether a capture of this process is in flight at ``address`` (ADR-0286 §7:2)."""
        return address in self._in_flight

    async def admit(self, state: ActivationState, *, payload_limit: int) -> None:
        """Insert the open episode at ``activation:<activation_id>`` (ADR-0286 §2).

        Called once the activation is admitted and before any of its processing runs.
        The record carries what admission holds — the trigger as admitted,
        ``started_at``, the links established, no stage entry — and the write takes the
        capture timestamp once (§2:2). A resume whose conversation is not resolved
        writes nothing (§2:3).

        **A collision writes nothing and deletes nothing** (§2:4): the record at the
        address is not this activation's, so capture ends without touching it. Any
        other failure is indeterminate, and the next write's read settles it (§3:4).
        Never raises but for a cancellation.
        """
        address = state.episode_address
        if state.capture is not None or address is None or state.started_at is None:
            return
        if isinstance(state.trigger, RecordedResumeTrigger) and state.conversation_id is None:
            return
        try:
            captured_at = self._now()
        except Exception:
            capture_loss("admission", "clock")
            return
        progress = EpisodeProgress(address=address, captured_at=captured_at)
        state.capture = progress
        self._in_flight.setdefault(address, []).append(progress)
        try:
            episode = self._open(state, progress, payload_limit)
        except Exception:
            capture_loss("admission", "invalid_or_oversized")
            progress.ended = True
            return
        progress.uncertain = episode
        progress.possible = True
        try:
            await self._memory.write_atomic(
                [MemoryWrite(record=episode, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )
        except MemoryStoreConflictError:
            progress.uncertain = None
            progress.possible = False
            progress.ended = True
            capture_loss("episode", "conflict")
            return
        except Exception:
            capture_loss("episode", "failed")
            return
        progress.written = episode
        progress.uncertain = None

    async def append(
        self,
        state: ActivationState,
        *,
        payload_limit: int,
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> None:
        """Replace the open episode with the record the pass now stands at (ADR-0286 §3).

        Called as each stage ends, inside the pass's own deadline. Its failure never
        fails processing, replaces an answer or repeats a stage (§3:8): a capture
        failure ends capture and deletes the episode (§5), and the pass runs on.
        Never raises but for a cancellation.
        """
        progress = state.capture
        if progress is None or progress.ended or progress.frozen:
            return
        try:
            revision = self._open(state, progress, payload_limit)
        except Exception:
            capture_loss("append", "invalid_or_oversized")
            await self._end(progress, drain)
            return
        if progress.uncertain is None and revision == progress.written:
            return
        await self._replace(progress, revision, stage="append", drain=drain)

    async def write(
        self,
        state: ActivationState,
        processing: EpisodeProcessingRecord,
        *,
        payload_limit: int,
        checked_output: Callable[[], EpisodeProcessingRecord],
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> EpisodeCaptureReport:
        """Freeze the episode, then call ``record_turn``.

        An activation cancelled at the admission barrier ran no processing and wrote
        no episode yet; its admission write is made first, here, so the freeze always
        follows one (§2:1).

        **The freezing write is the last append** (ADR-0286 §4:1): the end entry and
        its fields, with the fields capture derives from the pass — ``content``, the
        placement, ``Provenance.derived_from_external`` and the capture modality
        (§4:2). It is conditioned on the stored record as every append is (§3:4), and
        where its outcome is not known, one read confirms it or calls it a mismatch
        (§3:5).

        **Any capture failure before the freeze is confirmed ends capture** (§5:2):
        no ``record_turn``, and the episode deleted by its id through ``drain``,
        whatever the conversation's state.

        **Once the freeze is confirmed, ``record_turn`` follows** (§4:4, as ADR-0287
        left it). A ``None`` from it means the conversation was deleted, and **the
        episode is kept** (ADR-0293 §2:7, superseding ADR-0283 §7:2 and §7:4 and
        ADR-0286 §4:4 in their deletion): deleting a conversation forgets nothing, and
        its episodes stay on its place until the user forgets them. The report stays
        degraded, since the conversation never recorded the turn.

        **A record the user forgets while it is captured leaves nothing** (ADR-0286
        §8).
        """
        if isinstance(state.trigger, RecordedResumeTrigger) and state.conversation_id is None:
            capture_loss("association", "unresolved")
            if state.capture is not None:
                await self._settle(state.capture, drain)
            return state.degraded_report()
        writes = _Writes()
        conversation_id = state.conversation_id
        try:
            if state.capture is None:
                # Cancelled at the admission barrier, so no processing ran and none
                # will: the admission write is still owed ahead of the freeze (§2:1).
                # It sits inside this scope, so a cancellation that lands after its
                # insert committed still ends the capture and deletes the episode.
                await self.admit(state, payload_limit=payload_limit)
            if state.capture is None:
                # The admission write could not be made, and logged why (§2).
                return state.degraded_report()
            return await self._freeze(
                state,
                state.capture,
                processing,
                writes,
                payload_limit=payload_limit,
                checked_output=checked_output,
                drain=drain,
            )
        finally:
            if state.capture is not None:
                await self._finished(state.capture, conversation_id, writes, drain)

    async def _finished(
        self,
        progress: EpisodeProgress,
        conversation_id: str | None,
        writes: _Writes,
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> None:
        """Fence a frozen capture or end an unfrozen one, then stop tracking it."""
        try:
            if progress.frozen:
                if conversation_id is not None and not writes.verified:
                    await drain(self._fence(progress))
            elif not progress.ended:
                # Cut short before the freeze was confirmed — cancelled, timed out or
                # raised: §5:2's capture failure.
                capture_loss("freeze", "unconfirmed")
                await self._end(progress, drain)
        finally:
            self._settled(progress)

    async def abandon(
        self,
        state: ActivationState,
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> None:
        """End a capture finalization could not build a record for (ADR-0286 §5:2)."""
        progress = state.capture
        if progress is not None:
            await self._settle(progress, drain)

    async def close_open(self, *, stage_limit: int, payload_limit: int) -> None:
        """Close every open episode no capture of this process holds (ADR-0286 §7).

        Each is frozen ``interrupted`` / ``hub_stopped`` by an end entry due
        ``hub_stopped`` with outcome ``done``, at this clock's one reading. The
        placement and ``Provenance.derived_from_external`` stay as stored, and
        ``record_turn`` is called with no delivery only where the episode is on a
        conversation's channel; a ``None`` from it keeps the episode (ADR-0293 §2:7,
        superseding §7:3 in its deletion). The closed record is measured against
        ADR-0275 §9:1's bound as every write of an episode is (§3:6), and one that
        exceeds it is deleted by its id as a capture failure (§5:2).

        Raises:
            MemoryStoreError: If the store cannot be read or written (§7:4).
            ConversationStoreError: If ``record_turn`` fails.
        """
        after: int | None = None
        while True:
            page = await self._memory.open_episodes(after=after, limit=_OPEN_PAGE)
            for entry in page:
                if not self.holds(entry.record.id):
                    await self._close(
                        entry.record, stage_limit=stage_limit, payload_limit=payload_limit
                    )
            if len(page) < _OPEN_PAGE:
                return
            after = page[-1].number

    async def _close(self, stored: EpisodicMemory, *, stage_limit: int, payload_limit: int) -> None:
        processing = stored.processing_record
        if processing is None or not processing.is_open:  # pragma: no cover — the read's own
            return
        now = self._now()
        # The bound is the record's own where it already bit. Otherwise it is the
        # configured one, but never below the entries already stored: the record does
        # not carry its limit (ADR-0280 §6:6), and under a setting lowered since the
        # pass wrote them, a shorter bound is a revision that does not extend the
        # stored record (§3:3), which the store refuses at every start.
        limit = (
            len(processing.stages)
            if processing.stages_elided
            else max(stage_limit, len(processing.stages))
        )
        stages, elided = StageRecord(list(processing.stages)).bounded(
            limit, ending=(ControllerRule.HUB_STOPPED, now)
        )
        frozen = EpisodeProcessingRecord.model_validate(
            {
                **dict(processing),
                "trigger": _on_its_conversation(processing.trigger),
                "status": ProcessingStatus.INTERRUPTED,
                "reason": ProcessingReason.HUB_STOPPED,
                "ended_at": now,
                "stages": stages,
                "stages_elided": processing.stages_elided + elided,
                "understanding_omitted": _closed_omission(processing),
            }
        )
        closed = stored.model_copy(update={"processing_record": frozen})
        closed = closed.model_copy(update={"content": episode_content(closed)})
        try:
            _bounded(closed, payload_limit)
        except ValueError:
            # §3:6 on the freezing write the close is (§7:3): a capture failure, so
            # the episode is deleted by its id (§5:2) rather than left open for every
            # later start to fail on again.
            capture_loss("close", "invalid_or_oversized")
            await self._memory.delete(stored.id)
            return
        await self._memory.write_atomic(
            [
                MemoryWrite(
                    record=closed,
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=stored.revision,
                )
            ]
        )
        channel = frozen.trigger.channel
        if channel is None or channel.channel_type != "conversation":
            return
        # A ``None`` is a deleted conversation, and the episode is kept (ADR-0293 §2:7).
        await self._conversations.record_turn(
            channel.instance_id, episode_id=stored.id, occurred_at=stored.occurred_at
        )

    async def _freeze(  # noqa: PLR0913 — the capture, its record, its writes and the three seams
        self,
        state: ActivationState,
        progress: EpisodeProgress,
        processing: EpisodeProcessingRecord,
        writes: _Writes,
        *,
        payload_limit: int,
        checked_output: Callable[[], EpisodeProcessingRecord],
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> EpisodeCaptureReport:
        if progress.ended:
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
            preflight = processing.model_copy(
                update={"trigger": state.trigger, "links": state.links}
            )
            self._frozen(state, preflight, progress, payload_limit)
            processing = checked_output()
            episode = self._frozen(state, processing, progress, payload_limit)
        except Exception:
            capture_loss("preflight", "invalid_or_oversized")
            await self._end(progress, drain)
            return state.degraded_report()
        confirmed = await self._replace(progress, episode, stage="freeze", drain=drain)
        if confirmed is None:
            confirmed = await self._confirm(progress, episode, drain)
        if not confirmed:
            return state.degraded_report()
        progress.frozen = True
        return await self._recorded(state, progress, episode, writes)

    async def _recorded(
        self,
        state: ActivationState,
        progress: EpisodeProgress,
        episode: EpisodicMemory,
        writes: _Writes,
    ) -> EpisodeCaptureReport:
        """``record_turn``, once the freeze is confirmed (§4:4, as ADR-0287 left it)."""
        conversation_id = state.conversation_id
        if conversation_id is not None and not progress.forgotten:
            await self._record_turn(state, conversation_id, episode, writes)
        if conversation_id is None or writes.verified:
            return EpisodeCaptureReport(
                activation_id=state.activation_id, episode_id=episode.id, state="recorded"
            )
        return state.degraded_report()

    async def _replace(
        self,
        progress: EpisodeProgress,
        revision: EpisodicMemory,
        *,
        stage: str,
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> bool | None:
        """Replace the stored episode with ``revision``, conditioned on the read (§3:4).

        Answers ``True`` where the write returned, ``False`` where capture ended, and
        ``None`` where the write's outcome is not known: the next read then accepts
        ``revision`` as well as the record last written, since either is what that
        write leaves stored, and the write after it is conditioned on the read.
        """
        if progress.forgotten:
            # ADR-0286 §8:2: the next write after the mark writes nothing.
            capture_loss(stage, "forgotten")
            await self._end(progress, drain)
            return False
        refusal: str | None
        try:
            stored = await self._memory.get(progress.address)
        except Exception:
            stored, refusal = None, "read_failed"
        else:
            refusal = _refusal(stored, _expected(stored, progress), revision)
        if stored is None or refusal is not None:
            capture_loss(stage, refusal or "mismatch")
            await self._end(progress, drain)
            return False
        progress.uncertain = revision
        try:
            await self._memory.write_atomic(
                [
                    MemoryWrite(
                        record=revision,
                        mode=MemoryWriteMode.IF_UNCHANGED,
                        expected_revision=stored.revision,
                    )
                ]
            )
        except MemoryStoreStaleError:
            progress.uncertain = None
            capture_loss(stage, "mismatch")
            await self._end(progress, drain)
            return False
        except Exception:
            capture_loss(stage, "failed")
            return None
        progress.written = revision
        progress.uncertain = None
        return True

    async def _confirm(
        self,
        progress: EpisodeProgress,
        episode: EpisodicMemory,
        drain: Callable[[Awaitable[None]], Awaitable[None]],
    ) -> bool:
        """Settle a freezing write whose outcome is not known, by one read (§3:5)."""
        try:
            stored = await self._memory.get(progress.address)
        except Exception:
            capture_loss("freeze", "read_failed")
            await self._end(progress, drain)
            return False
        if stored is None or not _carries(stored, episode):
            capture_loss("freeze", "mismatch")
            await self._end(progress, drain)
            return False
        progress.written = episode
        progress.uncertain = None
        return True

    async def _settle(
        self, progress: EpisodeProgress, drain: Callable[[Awaitable[None]], Awaitable[None]]
    ) -> None:
        """End an unfrozen capture and stop tracking it."""
        try:
            if not progress.frozen and not progress.ended:
                await self._end(progress, drain)
        finally:
            self._settled(progress)

    async def _end(
        self, progress: EpisodeProgress, drain: Callable[[Awaitable[None]], Awaitable[None]]
    ) -> None:
        """End capture, and delete the episode by its id through the drain (§5:2)."""
        progress.ended = True
        if progress.possible:
            await drain(self._delete(progress))

    async def _delete(self, progress: EpisodeProgress) -> None:
        try:
            await self._memory.delete(progress.address)
        except Exception:
            # The episode stays open, and the next restart closes it (ADR-0286 §5).
            capture_loss("compensate_episode", "failed")
            return
        progress.possible = False

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
            # The conversation was deleted; the episode is kept (ADR-0293 §2:7).
            return
        writes.verified = True
        state.recorded_episode_id = episode.id

    def _settled(self, progress: EpisodeProgress) -> None:
        """Stop tracking one capture once its fence has run."""
        held = self._in_flight.get(progress.address)
        if held is None:
            return
        held[:] = [one for one in held if one is not progress]
        if not held:
            del self._in_flight[progress.address]

    async def _fence(self, progress: EpisodeProgress) -> None:
        """Destroy a frozen episode the user forgot while it was captured (ADR-0286 §8).

        **A forgotten capture is destroyed whatever its conversation's state**,
        because the user's act named the record itself. **Nothing else is**: where
        ``record_turn`` answered ``None``, or could not be told, the conversation's
        state decides nothing, because deleting a conversation forgets nothing
        (ADR-0293 §2:7, superseding ADR-0283 §7:2 and §7:4 in their deletion).
        """
        if not progress.forgotten:
            return
        try:
            await self._memory.delete(progress.address)
        except Exception:
            capture_loss("compensate_episode", "failed")

    def _open(
        self, state: ActivationState, progress: EpisodeProgress, payload_limit: int
    ) -> EpisodicMemory:
        """The open episode as the pass stands now (ADR-0286 §1, §3).

        Empty ``content`` and reach ``OWNER`` set ``DERIVED``, stamped with the
        admission write's reading (§1:3); no response, which the freezing write sets
        (§4); and ADR-0223's value as the pass last held it, ``False`` until it holds
        one (§4:3).
        """
        now = progress.captured_at
        episode = EpisodicMemory(
            id=progress.address,
            content="",
            occurred_at=now,
            outcome=None,
            capture=Capture(modality=_trigger_modality(state)),
            expires_at=None if self._retention is None else now + self._retention,
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=0.9,
                last_updated=now,
                derived_from_external=bool(state.derived_from_external),
            ),
            placement=Placement(
                reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=now
            ),
            processing_record=state.open_processing(),
        )
        _bounded(episode, payload_limit)
        return episode

    def _frozen(
        self,
        state: ActivationState,
        processing: EpisodeProcessingRecord,
        progress: EpisodeProgress,
        payload_limit: int,
    ) -> EpisodicMemory:
        """The freezing revision: the record's end and what capture derives (§4:2)."""
        facts = state.facts
        now = progress.captured_at
        episode = EpisodicMemory(
            id=progress.address,
            content="",
            occurred_at=now,
            outcome=state.response,
            capture=Capture(modality=_trigger_modality(state) if facts is None else facts.modality),
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
        # ADR-0284 §7:1: one rule sets every processing-record episode's search text,
        # on every channel, and nothing else composes it — a pure function of the
        # processing record just built, so it is derived from the episode itself.
        episode = episode.model_copy(update={"content": episode_content(episode)})
        _bounded(episode, payload_limit)
        return episode


def _trigger_modality(state: ActivationState) -> Modality:
    trigger = state.trigger
    return (
        trigger.payload.modality if isinstance(trigger, RecordedChannelTrigger) else Modality.TEXT
    )


def _bounded(episode: EpisodicMemory, payload_limit: int) -> None:
    """ADR-0275 §9:1's bound, on the whole record a write would store (ADR-0286 §3:6)."""
    if len(canonical_json(episode)) > 8 * payload_limit + 65536:
        raise ValueError("activation record exceeds its capture bound")


def _refusal(
    stored: MemoryRecord | None, expected: EpisodicMemory | None, revision: EpisodicMemory
) -> str | None:
    """Why the writer may not continue from ``stored`` to ``revision``, or ``None`` (§3:4).

    Anything but exactly the record the writer expects is a mismatch, no record
    included. A revision that does not extend it is one the store's guard would refuse
    (§12:2): a writer that built one has a defect, and a retry would hide it (§5).
    """
    if stored is None or expected is None or not _carries(stored, expected):
        return "mismatch"
    if not episode_extends(expected, revision):
        return "not_an_extension"
    return None


def _expected(stored: MemoryRecord | None, progress: EpisodeProgress) -> EpisodicMemory | None:
    """The record the writer may continue from, where ``stored`` is exactly it (§3:4).

    That is the record it last wrote, or, after a write whose outcome it does not
    know, the record that write carried: a write cut short may or may not have landed,
    and either record is one this capture wrote. ``None`` where it is neither.
    """
    if stored is None:
        return None
    for candidate in (progress.uncertain, progress.written):
        if candidate is not None and _carries(stored, candidate):
            return candidate
    return None


def _carries(stored: MemoryRecord, expected: EpisodicMemory) -> bool:
    """Whether the stored record is exactly ``expected``, its store-authored fields aside."""
    return (
        stored.model_copy(update={"revision": expected.revision, "score": expected.score})
        == expected
    )


def _closed_omission(processing: EpisodeProcessingRecord) -> UnderstandingOmission | None:
    """ADR-0276 §5's classification, read off what the open record shows of the pass.

    A restart's close is the freezing write (ADR-0286 §7:3), which carries the
    omission (§4:1); it classifies by where the record shows the pass ended, never by
    its text. A recorded version outranks every omission; a resume carries no input;
    speech whose recorded transcript is blank yielded no words; a non-``done``
    understanding entry is the stage's failure and a routing entry carrying an
    outcome a taken route; anything else ended before the stage was entered.
    """
    if processing.understanding:
        return None
    trigger = processing.trigger
    if isinstance(trigger, RecordedResumeTrigger):
        return UnderstandingOmission.NO_INPUT
    payload = trigger.payload
    if (
        isinstance(payload, RecordedSpeechInput)
        and payload.transcript is not None
        and not payload.transcript.strip()
    ):
        return UnderstandingOmission.NO_TEXT
    for entry in processing.stages:
        if entry.stage is ControllerStage.UNDERSTANDING and entry.outcome is not StageOutcome.DONE:
            return UnderstandingOmission.FAILED
        if entry.stage is ControllerStage.ROUTING and entry.route_outcome is not None:
            return UnderstandingOmission.ROUTED
    return UnderstandingOmission.NOT_REACHED
