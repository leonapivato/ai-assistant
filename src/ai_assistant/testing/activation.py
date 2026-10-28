"""Independent in-memory activation records for the canonical engine fake."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.episode_encoding import canonical_json, episode_content
from ai_assistant.core.errors import (
    AssistantError,
    MemoryStoreConflictError,
    ModelTimeoutError,
    OversizedValueError,
)
from ai_assistant.core.types import (
    ActivationUnderstanding,
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
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    StageEntry,
    StageOutcome,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
)
from ai_assistant.orchestration.activation_cleanup import drain_registered

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Mapping
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import (
        ChannelInput,
        ConversationDigest,
        ReplyCapability,
    )


def ended_pass(
    at: datetime, rule: ControllerRule = ControllerRule.NOTHING_DUE
) -> tuple[StageEntry, ...]:
    """The smallest stage record an activation's processing record admits.

    ADR-0280 §7 requires an activation's record to end in exactly one end
    entry, last. A test that builds a record by hand and is about something else
    passes this rather than spelling the entry out.

    Args:
        at: The instant of the end entry's one reading.
        rule: The rule that ended the pass.

    Returns:
        The one end entry, as a stage record.
    """
    return (
        StageEntry(
            stage=ControllerStage.END,
            due=rule,
            started_at=at,
            ended_at=at,
            outcome=StageOutcome.DONE,
        ),
    )


async def _withdraw(memory: MemoryStore, record: EpisodicMemory) -> None:
    """Delete ``record``'s address where the record stored there is this one.

    An insert whose outcome is not known may never have reached the store's
    collision check, so the address may hold another activation's record — another
    conversation's — which forgetting this one must not reach (ADR-0293 §2:8). Only
    a stored record carrying this one's trigger is this capture's, and only that is
    deleted.
    """
    stored = await memory.get(record.id)
    if (
        isinstance(stored, EpisodicMemory)
        and stored.processing_record is not None
        and record.processing_record is not None
        and stored.processing_record.trigger == record.processing_record.trigger
    ):
        await memory.delete(record.id)


async def _drained(cleanup: Coroutine[object, object, None]) -> None:
    """Run ``cleanup`` to its end through any cancellation, then pass a cancellation on.

    A forgotten capture's compensation is safety work (ADR-0275 §8:11): cancelling
    the caller must not cut it short and leave a forgotten episode stored. The drain
    is the engine's own (``drain_registered``, as its safety work uses it), so the
    fake and the engine hold a caller's cancellation the same way — including one
    that lands after the cleanup has finished (ADR-0060). A failure of the cleanup
    itself is dropped, as the engine's compensation logs and drops one; the
    cancellation it outlived is raised once it is done.
    """
    with contextlib.suppress(Exception):
        await drain_registered(asyncio.ensure_future(cleanup), cancel_on_interrupt=False)


@dataclass
class FakeActivation:
    """One fake call's facts, passed explicitly rather than stored on its engine."""

    trigger: RecordedChannelTrigger
    at: datetime
    conversation_id: str | None = None
    activation_id: str | None = None
    episode_id: str | None = None
    response: str | None = None
    spoken_degraded: bool = False
    no_words: bool = False
    output_failure: OversizedValueError | None = None
    #: Its conversation was forgotten while it ran (ADR-0293 §2:6): its capture writes
    #: nothing, and an episode already on its way is deleted once it lands.
    forgotten: bool = False
    understood: bool = False
    #: ADR-0297 §3: the stop mark, set by the fake's ``stop_activation`` on an
    #: activation that has not ended, and never cleared.
    stopped: bool = False
    #: The finalization reading was taken: for a stop, the activation has ended.
    ended: bool = False

    def stop(self) -> bool:
        """Set the stop mark unless the activation has ended, as the engine does (§3:3)."""
        if self.ended:
            return False
        self.stopped = True
        return True

    @classmethod
    def channel(
        cls, supplied: ChannelInput, reply: ReplyCapability | None, at: datetime
    ) -> FakeActivation:
        """Snapshot a validated fake channel admission without retaining audio."""
        event = (
            isinstance(supplied.target, ChannelIdentity)
            and supplied.target.channel_type == "informational_event"
        )
        payload = (
            RecordedSpeechInput(media_type=supplied.payload.audio.media_type, transcript=None)
            if isinstance(supplied.payload, SpeechChannelPayload)
            else RecordedTextInput(text=supplied.payload.text)
        )
        return cls(
            trigger=RecordedChannelTrigger(
                target=supplied.target,
                channel=supplied.target
                if event and isinstance(supplied.target, ChannelIdentity)
                else None,
                payload=payload,
                context=supplied.context,
                reply=reply,
                # ADR-0351 §3:1: the parties the channel's kind declares, fixed at
                # admission (§2:8).
                parties=declared_input(supplied.target)[0],
            ),
            at=at,
            conversation_id=(
                supplied.target.instance_id
                if isinstance(supplied.target, ChannelIdentity) and not event
                else None
            ),
        )

    def identify(self, factory: Callable[[], str]) -> None:
        """Keep failed metadata allocation separate from admitted processing."""
        try:
            value = factory()
            parsed = UUID(value)
            if str(parsed) != value or parsed.version != 4:  # noqa: PLR2004 — UUID version from ADR-0275
                raise ValueError("invalid activation id")
            self.activation_id = value
        except Exception:
            self.activation_id = None

    def resolved(self, conversation_id: str) -> None:
        """Retain a conversation actually resolved by the fake's processing."""
        self.conversation_id = conversation_id
        self.trigger = self.trigger.model_copy(
            update={
                "channel": ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
            }
        )

    def understand(self) -> None:
        """Mark that this fake pass reached the point the engine's stage runs (ADR-0276 §5).

        Called where the concrete engine enters its understanding stage — after the
        conversation resolves, or the event input does, and before anything is
        produced — so that the shared channel contract reads the same record from this
        double as from the engine: version 1 where the stage ran, and the omission
        value naming where the pass ended where it did not.
        """
        self.understood = True

    def said(self, text: str) -> None:
        """Keep a message the activation wrote, as its episode's ``outcome`` (ADR-0307 §10).

        The messages written, joined by a blank line, as the phases keep them. An event's
        place takes no message, so its episode keeps no outcome (ADR-0313 §4:3).
        """
        self.response = text if self.response is None else f"{self.response}\n\n{text}"

    def report(self) -> EpisodeCaptureReport:
        """Reserve a complete receipt at the address capture writes (ADR-0283 §2).

        Every episode's id is ``activation:<activation_id>``, fixed at admission, so
        the reservation is sized at that address whether or not the activation runs
        on a conversation — what the real engine's ``ActivationState.reserved_report``
        reserves — and no placeholder is sized.
        """
        if self.activation_id is None:
            return EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded")
        address = self.episode_id
        if address is None:
            address = f"activation:{self.activation_id}"
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=address, state="degraded"
        )

    def status(self, failure: BaseException | None) -> tuple[ProcessingStatus, ProcessingReason]:  # noqa: PLR0911 — independent ordered fake classification
        """Classify the outcomes this deterministic fake can produce (ADR-0318 §5:2)."""
        if self.stopped:
            # ADR-0297 §4: ahead of every other row, a cancellation's included.
            return ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED
        if isinstance(failure, asyncio.CancelledError):
            return ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED
        if isinstance(failure, ModelTimeoutError):
            return ProcessingStatus.FAILED, ProcessingReason.TIMEOUT
        if isinstance(failure, OversizedValueError):
            return ProcessingStatus.FAILED, ProcessingReason.OUTPUT_OVERSIZED
        if isinstance(failure, AssistantError):
            return ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED
        if failure is not None:
            return ProcessingStatus.FAILED, ProcessingReason.INTERNAL_ERROR
        return (
            ProcessingStatus.COMPLETED,
            ProcessingReason.NO_CONTENT if self.no_words else ProcessingReason.RETURNED,
        )

    def record(self, address: str, failure: BaseException | None) -> EpisodicMemory:
        """Build a structured fake record with no raw fields in its embedding text."""
        assert self.activation_id is not None  # noqa: S101 — incomplete envelopes never persist
        status, reason = self.status(failure)
        modality = self.trigger.payload.modality
        record = EpisodicMemory(
            id=address,
            content="",
            outcome=self.response,
            occurred_at=self.at,
            capture=Capture(modality=modality),
            provenance=Provenance(
                source=MemorySource.OBSERVED, confidence=0.9, last_updated=self.at
            ),
            processing_record=EpisodeProcessingRecord(
                activation_id=self.activation_id,
                started_at=self.at,
                ended_at=self.at,
                trigger=self.trigger,
                status=status,
                reason=reason,
                output_degraded=self.spoken_degraded,
                understanding=self.understanding(),
                understanding_omitted=self.omission(),
                stages=self.stages(failure),
            ),
        )
        # ADR-0284 §7:1: the one rule, as the engine's writer applies it.
        return record.model_copy(update={"content": episode_content(record)})

    def stages(self, failure: BaseException | None) -> tuple[StageEntry, ...]:
        """ADR-0280 §7's record shape over this fake's facts.

        The fake runs no controller. It records the pass's one end entry, choosing the
        rule from what it knows: ``stopped`` where its stop mark is set (ADR-0297 §4);
        ``interrupted`` on a cancellation; ``no_text_input`` for speech with no words;
        ``stage_failed`` on any other failure; and ``nothing_due`` otherwise.
        """
        if self.stopped:
            rule = ControllerRule.STOPPED
        elif isinstance(failure, asyncio.CancelledError):
            rule = ControllerRule.INTERRUPTED
        elif self.no_words:
            rule = ControllerRule.NO_TEXT_INPUT
        elif failure is not None:
            rule = ControllerRule.STAGE_FAILED
        else:
            rule = ControllerRule.NOTHING_DUE
        return ended_pass(self.at, rule)

    def understanding(self) -> tuple[ActivationUnderstanding, ...]:
        """The one version a pass that reached the stage records, and none otherwise."""
        if self.omission() is not None:
            return ()
        return (
            ActivationUnderstanding(
                version=1,
                recorded_at=self.at,
                producer=UnderstandingProducer.INTERPRETATION,
                meaning="This fake engine understood the input as stated.",
                meaning_ground=UnderstandingGround.STATED,
            ),
        )

    def omission(self) -> UnderstandingOmission | None:
        """ADR-0276 §5's classification, mirrored over the facts this fake holds."""
        if self.no_words:
            return UnderstandingOmission.NO_TEXT
        return None if self.understood else UnderstandingOmission.NOT_REACHED

    def was_forgotten(self) -> bool:
        """Whether its conversation was forgotten while it ran (ADR-0293 §2:6).

        A method rather than a read of :attr:`forgotten`, because the flag is set from
        outside across an ``await`` and a narrowed read would not see it change.
        """
        return self.forgotten

    async def finish(  # noqa: C901, PLR0911, PLR0912, PLR0913 — bounded capture stages, truthful early-loss returns, and the forgetting checks either side of the write
        self,
        *,
        memory: MemoryStore,
        conversations: Mapping[str, ConversationDigest],
        allocate: Callable[[str], str],
        max_bytes: int,
        failure: BaseException | None,
        check_output: Callable[[], object],
    ) -> EpisodeCaptureReport:
        """Insert once and report only confirmed live capture; never retry processing."""
        # ADR-0297 §3:2: the finalization reading ends the activation, for a stop.
        self.ended = True

        def forgotten() -> EpisodeCaptureReport:
            self.episode_id = None
            return EpisodeCaptureReport(
                activation_id=self.activation_id, episode_id=None, state="degraded"
            )

        def degraded() -> EpisodeCaptureReport:
            return EpisodeCaptureReport(
                activation_id=self.activation_id, episode_id=self.episode_id, state="degraded"
            )

        if self.activation_id is None:
            return degraded()
        try:
            if (
                len(canonical_json(self.record(self.report().episode_id or "", failure)))
                > 8 * max_bytes + 65536
            ):
                return degraded()
            if self.conversation_id is not None:
                # A conversation deleted mid-turn still gets its episode: deleting a
                # conversation forgets nothing (ADR-0293 §2:7), and the engine's open
                # episode, written at admission, is frozen and kept the same way.
                self.episode_id = allocate(self.conversation_id)
                self.resolved(self.conversation_id)
            address = self.episode_id or f"activation:{self.activation_id}"
            if failure is None:
                try:
                    check_output()
                except OversizedValueError as exc:
                    failure = self.output_failure = exc
            record = self.record(address, failure)
            if len(canonical_json(record)) > 8 * max_bytes + 65536:
                return degraded()
            if self.was_forgotten():
                return forgotten()
            try:
                await memory.write_atomic(
                    [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
                )
            except MemoryStoreConflictError:
                # The address holds another record, which a forget never reaches.
                raise
            except BaseException:
                # Indeterminate, a cancellation included: where the conversation was
                # forgotten meanwhile, the write may have committed, so the episode is
                # deleted before the failure goes on (ADR-0293 §2:6, ADR-0286 §8:2).
                if self.was_forgotten():
                    await _drained(_withdraw(memory, record))
                raise
            if self.was_forgotten():
                # Forgotten while the write was on its way: as ADR-0286 §8:2's next
                # write after the mark, the episode is deleted rather than kept.
                await _drained(_withdraw(memory, record))
                return forgotten()
            if self.conversation_id is not None and self.conversation_id not in conversations:
                # Kept, as the engine keeps it where ``record_turn`` answers ``None``
                # (ADR-0293 §2:7); the conversation never recorded the turn, so the
                # report stays degraded and names no episode, as the engine's does.
                return EpisodeCaptureReport(
                    activation_id=self.activation_id, episode_id=None, state="degraded"
                )
        except Exception:
            return degraded()
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=address, state="recorded"
        )
