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
    UnderstandingError,
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
    UnderstandingOmission,
    is_live_confirmation_park,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActivationUnderstanding,
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
    reply_degraded: bool = False
    spoken_degraded: bool = False
    no_words: bool = False
    index_episode_id: str | None = None
    understanding: tuple[ActivationUnderstanding, ...] = ()
    understanding_elided: int = 0
    understanding_omitted: UnderstandingOmission | None = None
    understanding_unparseable: bool = False
    _last_understanding_version: int = field(default=0, init=False, repr=False)

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
            if transcript is None or not transcript.strip():
                # ADR-0276 §5: speech that yielded no words, or whose transcription
                # failed, is a branch the pass took — the stage is never entered.
                self.omit(UnderstandingOmission.NO_TEXT)

    def omit(self, omission: UnderstandingOmission) -> None:
        """Record the branch that ended the pass without an understanding (ADR-0276 §5).

        The first branch taken is the one recorded: each value names where the pass
        ended, and a later step of a pass that already ended there cannot move it.
        A version recorded on this state outranks every omission at capture.
        """
        if self.understanding_omitted is None:
            self.understanding_omitted = omission

    def understanding_failed(self, failure: BaseException) -> None:
        """The stage was entered and raised: ``failed``, whatever the class (ADR-0276 §5).

        ``understanding_unparseable`` keeps ADR-0276 §6's reason when the event path
        maps the raise outward, so the record is the same on both paths.
        """
        self.omit(UnderstandingOmission.FAILED)
        if isinstance(failure, UnderstandingError):
            self.understanding_unparseable = True

    def next_understanding_version(self) -> int:
        """The version the next recorded understanding takes: one greater than the last."""
        return self._last_understanding_version + 1

    def understood(self, understanding: ActivationUnderstanding, *, limit: int) -> None:
        """Accumulate one version on the carrier, bounded at ``limit`` (ADR-0276 §7).

        Where more than ``limit`` versions have been recorded, the history keeps
        version 1 and the latest ``limit - 1``, in version order, and
        ``understanding_elided`` counts the versions dropped. The latest is never
        elided.

        Raises:
            ValueError: If ``understanding`` is not the next version, or ``limit`` is
                below 2 — a bound that keeps version 1 and the latest needs both.
        """
        if limit < 2:  # noqa: PLR2004 — version 1 and the latest
            msg = "the understanding history keeps version 1 and the latest (ADR-0276 §7)"
            raise ValueError(msg)
        if understanding.version != self.next_understanding_version():
            msg = "an understanding version is one greater than the last recorded"
            raise ValueError(msg)
        self._last_understanding_version = understanding.version
        history = (*self.understanding, understanding)
        if len(history) > limit:
            self.understanding_elided += len(history) - limit
            history = (history[0], *history[len(history) - (limit - 1) :])
        self.understanding = history

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

    def composition(self, text: str | None, *, degraded: bool, timed_out: bool) -> None:
        """Retain the completed composition before later bookkeeping can fail."""
        self.response = text
        self.response_kind = (
            EpisodeResponseKind.NONE if text is None else EpisodeResponseKind.CONVERSATION_REPLY
        )
        self.reply_degraded = degraded
        self.composition_timed_out = timed_out

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
            reply_degraded=self.reply_degraded
            or (self.outcome is not None and self.outcome.reply_degraded),
            spoken_degraded=self.spoken_degraded,
            model_eligible=self.facts is not None,
            links=self.links,
            understanding=self.understanding,
            understanding_omitted=self._omission(),
            understanding_elided=self.understanding_elided,
        )

    def _omission(self) -> UnderstandingOmission | None:
        """ADR-0276 §5's classification, by where the pass ended and never by its text.

        A pass that recorded a version records no omission, whatever ended it. A
        resume carries no input. Otherwise the branch the pass took — ``routed``,
        ``no_text``, ``failed`` — or ``not_reached`` for everything that ended ahead
        of the stage's entry: a cancellation, an expired deadline, a failure in any
        step before it.
        """
        if self.understanding:
            return None
        if isinstance(self.trigger, RecordedResumeTrigger):
            return UnderstandingOmission.NO_INPUT
        if self.understanding_omitted is not None:
            return self.understanding_omitted
        return UnderstandingOmission.NOT_REACHED

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


def terminal_status(  # noqa: C901, PLR0911, PLR0912 — ADR-0275's ordered terminal branches, and ADR-0276 §6's row among them
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
    # ADR-0276 §6: immediately below transcription failure and above output oversize.
    # The flag carries the reason through the event path's outward mapping.
    if isinstance(failure, UnderstandingError) or (
        failure is not None and state.understanding_unparseable
    ):
        return ProcessingStatus.FAILED, ProcessingReason.UNDERSTANDING_FAILED
    if isinstance(failure, OversizedValueError):
        return ProcessingStatus.FAILED, ProcessingReason.OUTPUT_OVERSIZED
    outcome = state.outcome
    if state.reply_degraded or (outcome is not None and outcome.reply_degraded):
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
