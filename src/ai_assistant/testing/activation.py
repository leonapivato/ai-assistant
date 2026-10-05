"""Independent in-memory activation records for the canonical engine fake."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from ai_assistant.core.channel_validation import input_origin
from ai_assistant.core.episode_encoding import canonical_json, episode_content
from ai_assistant.core.errors import (
    AssistantError,
    ChannelProcessingTimeoutError,
    OversizedValueError,
    TranscriptionFailedError,
)
from ai_assistant.core.types import (
    ActivationLinks,
    ActivationUnderstanding,
    Capture,
    ChannelIdentity,
    ChannelResult,
    ControllerRule,
    ControllerStage,
    Disposition,
    EpisodeCaptureReport,
    EpisodeProcessingRecord,
    EpisodicMemory,
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
    StageEntry,
    StageOutcome,
    TurnOutcome,
    UnderstandingGround,
    UnderstandingOmission,
    UnderstandingProducer,
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


def ended_pass(
    at: datetime, rule: ControllerRule = ControllerRule.NOTHING_DUE
) -> tuple[StageEntry, ...]:
    """The smallest stage record a channel activation's processing record admits.

    ADR-0280 §7 requires a channel activation's record to end in exactly one end
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
    spoken_degraded: bool = False
    no_words: bool = False
    links: ActivationLinks = field(default_factory=ActivationLinks)
    output_failure: OversizedValueError | None = None
    understood: bool = False

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
                # ADR-0284 §2:2: what the channel declares, fixed at admission.
                origin=input_origin(supplied.target),
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

    def understand(self) -> None:
        """Mark that this fake pass reached the point the engine's stage runs (ADR-0276 §5).

        Called where the concrete engine enters its understanding stage — after the
        conversation resolves, or the event input does, and before anything is
        produced — so that the shared channel contract reads the same record from this
        double as from the engine: version 1 where the stage ran, and the omission
        value naming where the pass ended where it did not.
        """
        self.understood = True

    def observe(self, result: TurnOutcome | SpokenTurn | ChannelResult) -> None:
        """Observe the fake's produced result before a size check can refuse it."""
        if isinstance(result, ChannelResult):
            if isinstance(result.result, InformationalEventResult):
                self.response = result.result.summary
                return
            result = result.result.outcome
        if isinstance(result, SpokenTurn):
            self.spoken_degraded = result.spoken_degraded
            if result.outcome is None:
                return
            result = result.outcome
        self.outcome = result
        self.response = result.reply

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
        modality = (
            self.trigger.payload.modality
            if isinstance(self.trigger, RecordedChannelTrigger)
            else Modality.TEXT
        )
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
                response_degraded=self.outcome is not None and self.outcome.reply_degraded,
                output_degraded=self.spoken_degraded,
                links=self.links,
                understanding=self.understanding(),
                understanding_omitted=self.omission(),
                stages=self.stages(failure),
            ),
        )
        # ADR-0284 §7:1: the one rule, as the engine's writer applies it.
        return record.model_copy(update={"content": episode_content(record)})

    def stages(self, failure: BaseException | None) -> tuple[StageEntry, ...]:
        """ADR-0280 §7's record shape, with ADR-0284 §5's verdicts, over this fake's facts.

        The fake runs no controller. It records the one stage entry that carries a
        verdict where its scripted result reached one — ``routing`` with the route's
        outcome, or ``drive`` with the step's disposition (§5:2) — and the pass's one
        end entry, choosing the rule from what it knows: ``interrupted`` on a
        cancellation; ``no_text_input`` for speech with no words or a failed
        transcription; ``stage_failed`` on any other failure; ``route_taken`` for a
        routed turn; and ``nothing_due`` otherwise.

        **A resume records its stages** (§5:4): the continued stage, due
        ``park_answered`` with its verdict, then ``compose`` due ``reply_owed`` where
        it replied, then the end entry. One that continued nothing records the end
        entry alone.

        **A verdict the pass reached survives a later failure.** The verdict entry reads
        the observed result whether or not a failure followed it, so a reply refused as
        oversized after its route performed still records the ``routing`` entry with
        that outcome — what the engine's controller has already recorded by the time
        the output is checked, and the one place §5:2 keeps the verdict.
        """
        resume = isinstance(self.trigger, RecordedResumeTrigger)
        reached = self.outcome
        outcome = None if failure is not None else reached
        entries: list[StageEntry] = []
        if reached is not None and reached.routed is not None:
            entries.append(
                self._entry(
                    ControllerStage.ROUTING,
                    ControllerRule.PARK_ANSWERED if resume else ControllerRule.ROUTE_UNCHECKED,
                    route_outcome=reached.routed.outcome,
                )
            )
        elif reached is not None and reached.step is not None:
            entries.append(
                self._entry(
                    ControllerStage.DRIVE,
                    ControllerRule.PARK_ANSWERED if resume else ControllerRule.PLAN_HAS_STEPS,
                    step_disposition=reached.step.disposition,
                )
            )
        if resume and outcome is not None and outcome.reply is not None:
            entries.append(self._entry(ControllerStage.COMPOSE, ControllerRule.REPLY_OWED))
        if isinstance(failure, asyncio.CancelledError):
            rule = ControllerRule.INTERRUPTED
        elif not resume and (self.no_words or isinstance(failure, TranscriptionFailedError)):
            rule = ControllerRule.NO_TEXT_INPUT
        elif failure is not None:
            rule = ControllerRule.STAGE_FAILED
        elif not resume and outcome is not None and outcome.routed is not None:
            rule = ControllerRule.ROUTE_TAKEN
        else:
            rule = ControllerRule.NOTHING_DUE
        return (*entries, *ended_pass(self.at, rule))

    def _entry(
        self,
        stage: ControllerStage,
        due: ControllerRule,
        *,
        step_disposition: Disposition | None = None,
        route_outcome: RouteOutcome | None = None,
    ) -> StageEntry:
        return StageEntry(
            stage=stage,
            due=due,
            started_at=self.at,
            ended_at=self.at,
            outcome=StageOutcome.DONE,
            step_disposition=step_disposition,
            route_outcome=route_outcome,
        )

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
        if isinstance(self.trigger, RecordedResumeTrigger):
            return UnderstandingOmission.NO_INPUT
        if self.no_words:
            return UnderstandingOmission.NO_TEXT
        if self.outcome is not None and self.outcome.routed is not None:
            return UnderstandingOmission.ROUTED
        return None if self.understood else UnderstandingOmission.NOT_REACHED

    async def finish(  # noqa: PLR0913 — bounded capture stages and truthful early-loss returns
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
            await memory.write_atomic(
                [MemoryWrite(record=record, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )
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
