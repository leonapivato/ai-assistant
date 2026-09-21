"""Independent in-memory activation records for the canonical engine fake."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from ai_assistant.core.episode_encoding import canonical_json
from ai_assistant.core.errors import (
    AssistantError,
    ChannelProcessingTimeoutError,
    OversizedValueError,
    TranscriptionFailedError,
)
from ai_assistant.core.types import (
    ActivationLinks,
    Capture,
    ChannelIdentity,
    ChannelResult,
    EpisodeCaptureReport,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    EpisodicMemory,
    ExchangeDisposition,
    InformationalEventResult,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    ProcessingReason,
    ProcessingStatus,
    Provenance,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    RouteOutcome,
    SpeechChannelPayload,
    SpokenTurn,
    TurnOutcome,
    is_live_confirmation_park,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import datetime

    from ai_assistant.core.protocols import MemoryStore
    from ai_assistant.core.types import (
        ChannelInput,
        ConversationDigest,
        RecordedActivationTrigger,
        ReplyCapability,
    )


@dataclass
class FakeActivation:
    """One fake call's facts, passed explicitly rather than stored on its engine."""

    trigger: RecordedActivationTrigger
    at: datetime
    conversation_id: str | None = None
    activation_id: str | None = None
    episode_id: str | None = None
    outcome: TurnOutcome | None = None
    response: str | None = None
    response_kind: EpisodeResponseKind = EpisodeResponseKind.NONE
    spoken_degraded: bool = False
    no_words: bool = False
    links: ActivationLinks = field(default_factory=ActivationLinks)
    output_failure: OversizedValueError | None = None

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
                conversation=supplied.conversation,
                reply=reply,
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

    def transcription(self, text: str) -> None:
        """Keep the scripted transcript exactly, including no-words input."""
        if isinstance(self.trigger, RecordedChannelTrigger) and isinstance(
            self.trigger.payload, RecordedSpeechInput
        ):
            self.trigger = self.trigger.model_copy(
                update={"payload": self.trigger.payload.model_copy(update={"transcript": text})}
            )
            self.no_words = not text.strip()

    def observe(self, result: TurnOutcome | SpokenTurn | ChannelResult) -> None:
        """Observe the fake's produced result before a size check can refuse it."""
        if isinstance(result, ChannelResult):
            if isinstance(result.result, InformationalEventResult):
                self.response = result.result.summary
                self.response_kind = EpisodeResponseKind.INFORMATIONAL_SUMMARY
                return
            result = result.result.outcome
        if isinstance(result, SpokenTurn):
            self.spoken_degraded = result.spoken_degraded
            if result.outcome is None:
                return
            result = result.outcome
        self.outcome = result
        self.response = result.reply
        self.response_kind = (
            EpisodeResponseKind.NONE
            if result.reply is None
            else EpisodeResponseKind.CONVERSATION_REPLY
        )

    def report(self) -> EpisodeCaptureReport:
        """Reserve a complete receipt until the fake's index assigns the address."""
        if self.activation_id is None:
            return EpisodeCaptureReport(activation_id=None, episode_id=None, state="degraded")
        address = self.episode_id
        if address is None:
            address = (
                f"activation:{self.activation_id}"
                if self.conversation_id is None
                else f"conv:{self.conversation_id}:{2**63 - 1}"
            )
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=address, state="degraded"
        )

    def status(self, failure: BaseException | None) -> tuple[ProcessingStatus, ProcessingReason]:  # noqa: C901, PLR0911 — independent ordered fake classification
        """Classify the outcomes this deterministic fake can produce."""
        if isinstance(failure, asyncio.CancelledError):
            return ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED
        if isinstance(failure, ChannelProcessingTimeoutError):
            return ProcessingStatus.FAILED, ProcessingReason.TIMEOUT
        if isinstance(failure, TranscriptionFailedError):
            return ProcessingStatus.FAILED, ProcessingReason.TRANSCRIPTION_FAILED
        if isinstance(failure, OversizedValueError):
            return ProcessingStatus.FAILED, ProcessingReason.OUTPUT_OVERSIZED
        outcome = self.outcome
        if outcome is not None and outcome.reply_degraded:
            return ProcessingStatus.FAILED, ProcessingReason.COMPOSITION_FAILED
        if isinstance(failure, AssistantError) or (
            outcome is not None
            and outcome.routed is not None
            and outcome.routed.outcome is RouteOutcome.FAILED
        ):
            return ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED
        if failure is not None:
            return ProcessingStatus.FAILED, ProcessingReason.INTERNAL_ERROR
        if outcome is not None:
            if outcome.read_confirmation is not None or is_live_confirmation_park(outcome):
                return ProcessingStatus.WAITING, ProcessingReason.CONFIRMATION
            if outcome.clarification is not None:
                return ProcessingStatus.WAITING, ProcessingReason.CLARIFICATION
            if outcome.disambiguation is not None:
                return ProcessingStatus.WAITING, ProcessingReason.DISAMBIGUATION
        return (
            ProcessingStatus.COMPLETED,
            ProcessingReason.NO_CONTENT if self.no_words else ProcessingReason.RETURNED,
        )

    def record(self, address: str, failure: BaseException | None) -> EpisodicMemory:
        """Build a structured fake record with no raw fields in its embedding text."""
        assert self.activation_id is not None  # noqa: S101 — incomplete envelopes never persist
        status, reason = self.status(failure)
        eligible = self.outcome is not None
        modality = (
            self.trigger.payload.modality
            if isinstance(self.trigger, RecordedChannelTrigger)
            else Modality.TEXT
        )
        return EpisodicMemory(
            id=address,
            content=self.content(),
            outcome=self.response,
            disposition=self.disposition(),
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
                response_kind=self.response_kind,
                model_eligible=eligible,
                reply_degraded=self.outcome is not None and self.outcome.reply_degraded,
                spoken_degraded=self.spoken_degraded,
                links=self.links,
            ),
        )

    def content(self) -> str:
        """Render the fake's established conversational facts outside the raw snapshot."""
        if self.outcome is None:
            return "Recorded activation; inspect its processing record."
        lines: list[str] = []
        if self.outcome.turn is not None:
            lines.append(f"The user asked: {self.outcome.turn.utterance}")
            if self.outcome.turn.plan.rationale:
                lines.append(f"The assistant's plan: {self.outcome.turn.plan.rationale}")
        elif isinstance(self.trigger, RecordedChannelTrigger):
            payload = self.trigger.payload
            text = payload.text if isinstance(payload, RecordedTextInput) else payload.transcript
            if text is not None:
                lines.append(f"The user asked: {text}")
        if isinstance(self.trigger, RecordedResumeTrigger):
            lines.append("The user answered the confirmation this action was parked on.")
        if self.outcome.step is not None and self.outcome.step.tool_id is not None:
            lines.append(f"The action selected the tool {self.outcome.step.tool_id}.")
        return "\n".join(lines)

    def disposition(self) -> ExchangeDisposition | None:
        """Preserve the scripted result's own exchange vocabulary."""
        if self.outcome is None:
            return None
        if self.outcome.step is not None:
            return ExchangeDisposition(f"step_{self.outcome.step.disposition.value}")
        if self.outcome.routed is not None:
            return ExchangeDisposition(f"routed_{self.outcome.routed.outcome.value}")
        return ExchangeDisposition.NO_ACTION_NEEDED

    async def finish(  # noqa: C901, PLR0911, PLR0913 — bounded capture stages and truthful early-loss returns
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

        def degraded() -> EpisodeCaptureReport:
            return EpisodeCaptureReport(
                activation_id=self.activation_id, episode_id=self.episode_id, state="degraded"
            )

        if self.activation_id is None or (
            isinstance(self.trigger, RecordedResumeTrigger) and self.conversation_id is None
        ):
            return degraded()
        try:
            if (
                len(canonical_json(self.record(self.report().episode_id or "", failure)))
                > 8 * max_bytes + 65536
            ):
                return degraded()
            if self.conversation_id is not None:
                if self.conversation_id not in conversations:
                    return degraded()
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
            await memory.write_atomic(
                [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )
            if self.conversation_id is not None and self.conversation_id not in conversations:
                await memory.delete(address)
                self.episode_id = None
                return degraded()
        except Exception:
            return degraded()
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=address, state="recorded"
        )
