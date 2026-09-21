"""Call-local facts for one admitted activation, never a durable start row."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from ai_assistant.core.errors import (
    AssistantError,
    ChannelProcessingTimeoutError,
    ModelTimeoutError,
    OversizedValueError,
    SpeechTimeoutError,
    TranscriptionFailedError,
)
from ai_assistant.core.types import (
    ActivationLinks,
    ChannelIdentity,
    EpisodeCaptureReport,
    EpisodeProcessingRecord,
    EpisodeResponseKind,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedResumeTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    RouteOutcome,
    SpeechChannelPayload,
    SpeechFailure,
    SpokenTurn,
    TurnOutcome,
    is_live_confirmation_park,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ChannelInput,
        ExchangeDisposition,
        Modality,
        ParkedBinding,
        RecordedActivationTrigger,
        ReplyCapability,
        SpokenDelivery,
    )

_log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CaptureFacts:
    """The canonical rendering and policy facts supplied by an existing capture path."""

    content: str
    asked: str | None
    response: str | None
    disposition: ExchangeDisposition
    modality: Modality
    supplied_withheld: bool
    derived_from_external: bool
    parked: ParkedBinding | None
    delivery: SpokenDelivery | None


@dataclass
class ActivationState:
    """Mutable facts confined to the worker owning one admission."""

    trigger: RecordedActivationTrigger
    activation_id: str | None
    started_at: datetime | None
    conversation_id: str | None
    facts: CaptureFacts | None = None
    outcome: TurnOutcome | None = None
    response: str | None = None
    response_kind: EpisodeResponseKind = EpisodeResponseKind.NONE
    links: ActivationLinks = field(default_factory=ActivationLinks)
    composition_timed_out: bool = False
    spoken_degraded: bool = False
    no_words: bool = False
    index_episode_id: str | None = None

    def transcription(self, transcript: str | None) -> None:
        """Keep exact text, including an empty transcript, without audio bytes."""
        trigger = self.trigger
        if isinstance(trigger, RecordedChannelTrigger) and isinstance(
            trigger.payload, RecordedSpeechInput
        ):
            self.trigger = trigger.model_copy(
                update={"payload": trigger.payload.model_copy(update={"transcript": transcript})}
            )
            self.no_words = transcript is not None and not transcript.strip()

    def resolved_conversation(self, conversation_id: str) -> None:
        """Use only the lifecycle's validated association, never a guessed neighbor."""
        self.conversation_id = conversation_id
        self.trigger = self.trigger.model_copy(
            update={
                "channel": ChannelIdentity(channel_type="conversation", instance_id=conversation_id)
            }
        )

    def observe_result(self, result: TurnOutcome | SpokenTurn) -> None:
        """Carry production degradation and response facts after synthesis decisions."""
        if isinstance(result, SpokenTurn):
            self.spoken_degraded = result.spoken_degraded
            outcome = result.outcome
        else:
            outcome = result
        if outcome is not None:
            self.outcome = outcome
            self.response = outcome.reply
            self.response_kind = (
                EpisodeResponseKind.NONE
                if outcome.reply is None
                else EpisodeResponseKind.CONVERSATION_REPLY
            )

    def processing(
        self, ended_at: datetime, failure: BaseException | None
    ) -> EpisodeProcessingRecord:
        """Build an immutable terminal record only when admission metadata is complete."""
        if self.activation_id is None or self.started_at is None:
            raise ValueError("activation admission metadata is incomplete")
        status, reason = terminal_status(self, failure)
        return EpisodeProcessingRecord(
            activation_id=self.activation_id,
            started_at=self.started_at,
            ended_at=ended_at,
            trigger=self.trigger,
            status=status,
            reason=reason,
            response_kind=self.response_kind,
            reply_degraded=self.outcome is not None and self.outcome.reply_degraded,
            spoken_degraded=self.spoken_degraded,
            model_eligible=self.facts is not None,
            links=self.links,
        )

    def relate(  # noqa: PLR0913 — each independently established relationship
        self,
        *,
        predecessor_episode_id: str | None = None,
        question_id: str | None = None,
        read_park_id: str | None = None,
        parked: ParkedBinding | None = None,
        goal_id: str | None = None,
        attempt_id: str | None = None,
    ) -> None:
        """Retain established relationships without manufacturing absent ones."""
        known = {
            "predecessor_episode_id": predecessor_episode_id,
            "question_id": question_id,
            "read_park_id": read_park_id,
            "parked": parked,
            "goal_id": goal_id,
            "attempt_id": attempt_id,
        }
        self.links = self.links.model_copy(
            update={name: value for name, value in known.items() if value is not None}
        )

    def reserved_report(self) -> EpisodeCaptureReport:
        """Bound the receipt before append, using SQLite's largest index ordinal."""
        address = self.index_episode_id
        if address is None:
            if self.conversation_id is not None:
                address = f"conv:{self.conversation_id}:9223372036854775807"
            elif self.activation_id is not None:
                address = f"activation:{self.activation_id}"
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=address, state="degraded"
        )

    def summary(self, text: str) -> None:
        """Observe a produced summary before the stage's final deadline check."""
        self.response = text
        self.response_kind = EpisodeResponseKind.INFORMATIONAL_SUMMARY

    def published(self, text: str) -> None:
        """Retain exactly the stream chunks actually published by this worker."""
        self.response = (self.response or "") + text
        self.response_kind = EpisodeResponseKind.CONVERSATION_REPLY

    def degraded_report(self) -> EpisodeCaptureReport:
        """An index address alone never claims that the episode was recorded."""
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=self.index_episode_id, state="degraded"
        )


@dataclass
class ActivationScope:
    """One worker's holder, allowing validated resume admission in a tracked child."""

    state: ActivationState | None = None


CURRENT_ACTIVATION: ContextVar[ActivationScope | None] = ContextVar("activation", default=None)


def active_state() -> ActivationState | None:
    """Read only this worker's admission, including one established by its child."""
    scope = CURRENT_ACTIVATION.get()
    return None if scope is None else scope.state


def admit_channel(
    input: ChannelInput,  # noqa: A002 — channel contract parameter
    reply: ReplyCapability | None,
    *,
    clock: Clock,
    id_factory: Callable[[], str],
) -> ActivationState:
    """Allocate capture metadata after channel validation, without making it admission policy."""
    event = (
        isinstance(input.target, ChannelIdentity)
        and input.target.channel_type == "informational_event"
    )
    payload = (
        RecordedSpeechInput(media_type=input.payload.audio.media_type, transcript=None)
        if isinstance(input.payload, SpeechChannelPayload)
        else RecordedTextInput(text=input.payload.text)
    )
    activation_id, started_at = _metadata(clock, id_factory)
    return ActivationState(
        trigger=RecordedChannelTrigger(
            target=input.target,
            channel=input.target if event and isinstance(input.target, ChannelIdentity) else None,
            payload=payload,
            context=input.context,
            conversation=input.conversation,
            reply=reply,
        ),
        activation_id=activation_id,
        started_at=started_at,
        conversation_id=(
            input.target.instance_id
            if isinstance(input.target, ChannelIdentity) and not event
            else None
        ),
    )


def admit_resume(
    *,
    approved: bool,
    remember_recipients_until: datetime | None,
    clock: Clock,
    id_factory: Callable[[], str],
) -> ActivationState:
    """Begin a control activation only after the worker resolves an unsettled park."""
    activation_id, started_at = _metadata(clock, id_factory)
    return ActivationState(
        trigger=RecordedResumeTrigger(
            channel=None, approved=approved, remember_recipients_until=remember_recipients_until
        ),
        activation_id=activation_id,
        started_at=started_at,
        conversation_id=None,
    )


def _metadata(clock: Clock, id_factory: Callable[[], str]) -> tuple[str | None, datetime | None]:
    activation_id = None
    started_at = None
    try:
        minted = id_factory()
        value = UUID(minted)
        if value.version != 4 or str(value) != minted:  # noqa: PLR2004 — mandated UUID version
            raise ValueError("activation IDs require canonical UUID4 text")
        activation_id = minted
    except Exception:
        _log.warning("activation_capture_degraded", stage="admission", reason="identifier")
    try:
        started_at = clock()
    except Exception:
        _log.warning("activation_capture_degraded", stage="admission", reason="clock")
    return activation_id, started_at


def terminal_status(  # noqa: C901, PLR0911 — ADR-0275's ordered terminal branches
    state: ActivationState, failure: BaseException | None
) -> tuple[ProcessingStatus, ProcessingReason]:
    """Apply ADR-0275's ordered terminal conditions without interpreting response prose."""
    if isinstance(failure, asyncio.CancelledError):
        return ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED
    if (
        state.composition_timed_out
        or isinstance(
            failure, ModelTimeoutError | SpeechTimeoutError | ChannelProcessingTimeoutError
        )
        or (
            isinstance(failure, TranscriptionFailedError)
            and failure.failure is SpeechFailure.TIMED_OUT
        )
    ):
        return ProcessingStatus.FAILED, ProcessingReason.TIMEOUT
    if isinstance(failure, TranscriptionFailedError):
        return ProcessingStatus.FAILED, ProcessingReason.TRANSCRIPTION_FAILED
    if isinstance(failure, OversizedValueError):
        return ProcessingStatus.FAILED, ProcessingReason.OUTPUT_OVERSIZED
    outcome = state.outcome
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
    if state.no_words:
        return ProcessingStatus.COMPLETED, ProcessingReason.NO_CONTENT
    return ProcessingStatus.COMPLETED, ProcessingReason.RETURNED
