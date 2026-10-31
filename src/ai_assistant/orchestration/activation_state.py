"""Call-local facts for one admitted activation, and how far its episode's writes got.

The episode is written at admission and extended as stages end (ADR-0286 §2, §3);
:class:`EpisodeProgress` is the writer's account of what it has stored so far.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from ai_assistant.core.channel_validation import declared_input
from ai_assistant.core.errors import (
    AssistantError,
    ModelTimeoutError,
    OversizedValueError,
    SpeechTimeoutError,
    UnderstandingError,
)
from ai_assistant.core.types import (
    ChannelIdentity,
    ControllerRule,
    EpisodeCaptureReport,
    EpisodeProcessingRecord,
    JoinedInput,
    ProcessingReason,
    ProcessingStatus,
    RecordedChannelTrigger,
    RecordedSpeechInput,
    RecordedTextInput,
    SpeechChannelPayload,
    UnderstandingOmission,
)
from ai_assistant.orchestration.controller import (
    DEFAULT_STAGE_RECORD_LIMIT,
    StageRecord,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        ActivationDigest,
        ActivationRecall,
        ActivationUnderstanding,
        ChannelInput,
        EpisodicMemory,
        Memory,
        Modality,
        PlanningLabel,
        PlanningRound,
        RecordedCall,
        RecordedInputMessage,
        ReplyCapability,
        StageEntry,
    )
    from ai_assistant.orchestration.matters import InputStanding, Named, Offer
    from ai_assistant.orchestration.person_block import PersonBlock

_log = structlog.get_logger(__name__)


class Commitment(StrEnum):
    """What acting's commitment step found before a round's act (ADR-0349 §7:14)."""

    COMMITTED = "committed"
    """The activation is committed, if it was not already, and the round runs."""

    STOPPED = "stopped"
    """The stop mark is set: the round runs nothing, and the pass ends on the stop
    (ADR-0297 §4)."""


@dataclass(frozen=True)
class CaptureFacts:
    """The policy facts a capture path supplies.

    The episode's ``content`` is not among them: it is derived from the processing
    record by one rule at the write (ADR-0284 §7:1).
    """

    modality: Modality
    supplied_withheld: bool
    derived_from_external: bool


@dataclass
class EpisodeProgress:
    """What one activation's episode writes are known to have done (ADR-0286 §2-§5, §8).

    The writer keeps it from the admission write until the capture settles, and reads
    nothing else to decide whether to continue: each write after the first is
    conditioned on the stored record carrying exactly :attr:`written`, or, after a
    write whose outcome is not known, exactly :attr:`uncertain` (§3:4).
    """

    #: ``activation:<activation_id>`` (ADR-0283 §2).
    address: str
    #: The admission write's one capture timestamp (§2:2, as ADR-0287 left it):
    #: ``occurred_at``, ``expires_at``, the placement's ``set_at`` and the instant
    #: ``record_turn`` carries all reuse it.
    captured_at: datetime
    #: The record the store is known to carry: the last write that returned.
    written: EpisodicMemory | None = None
    #: The record a write whose outcome is not known carried, until a read settles it.
    uncertain: EpisodicMemory | None = None
    #: An episode may stand at the address, so ending capture owes its deletion.
    possible: bool = False
    #: Capture ended (§5): nothing further is written for this activation.
    ended: bool = False
    #: The freezing write is confirmed (§4).
    frozen: bool = False
    #: A record-scoped ``forget`` named this address while the capture was in flight
    #: (§8).
    forgotten: bool = False
    #: The conversation the activation was started from, as far as it is known: what
    #: forgetting a conversation marks its in-flight captures by (ADR-0293 §2:6).
    conversation_id: str | None = None


@dataclass
class ActivationState:
    """Mutable facts confined to the worker owning one admission."""

    trigger: RecordedChannelTrigger
    activation_id: str | None
    started_at: datetime | None
    conversation_id: str | None
    facts: CaptureFacts | None = None
    #: The response the episode records (its ``outcome``): the phases' last message,
    #: set when the pass captures.
    response: str | None = None
    spoken_degraded: bool = False
    no_words: bool = False
    #: The phases ended the pass without finishing it, having returned rather than
    #: raised: the round limit or the loop guard ended it, or its last message was
    #: refused or lost with none recorded after it (ADR-0317 §3:2-§3:4). Never set for
    #: an activation that ended silent, which has finished (§2). The *couldn't finish*
    #: message is owed, so the pass is classified ``failed / processing_failed``
    #: (ADR-0275 §5:3's sixth row, ADR-0317 §3:5) and the current state reads
    #: *couldn't finish* beside that message (ADR-0293 §8:3). A stop still classifies
    #: first: a stop is no failure (ADR-0297 §4).
    unfinished: bool = False
    #: The episode's id once its conversation recorded the turn (ADR-0283 §7:1): set
    #: when ``ConversationStore.record_turn`` returned the conversation, so the
    #: episode is on the channel. ``None`` for a standalone capture and for a
    #: conversational one that never got that far.
    recorded_episode_id: str | None = None
    understanding: tuple[ActivationUnderstanding, ...] = ()
    understanding_elided: int = 0
    understanding_omitted: UnderstandingOmission | None = None
    understanding_unparseable: bool = False
    #: ADR-0281 §6: recall's decision, held once the stage ends and written with the
    #: stage's append (ADR-0286 §3). ``None`` where recall made no decision on the pass.
    recall: ActivationRecall | None = None
    #: ADR-0308 §2, §7: recall's second decision, made on what understanding found, held
    #: once that run ends and written with its stage's append, as the first's is.
    recall_second_run: ActivationRecall | None = None
    #: ADR-0307 §2:3-§2:4, §5:7: the planning rounds and the labels they and the
    #: digests assigned, and ADR-0308 §5:2's digests, each added as its recorder is
    #: called and written with the append that follows (ADR-0286 §3).
    rounds: tuple[PlanningRound, ...] = ()
    labels: tuple[PlanningLabel, ...] = ()
    digests: tuple[ActivationDigest, ...] = ()
    #: ADR-0356 §8:2, §8:6: one entry for each call a round proposed, each added once its
    #: outcome is known, or with none at the freeze, and written with the append that
    #: follows, as a round is.
    call_records: tuple[RecordedCall, ...] = ()
    #: Whether a recorder is extending the episode, and the owner's next append, owed
    #: to the recorders that added to the record since its current one began. The
    #: writer's append reads, then writes conditioned on what it read, so two at once
    #: would end capture (ADR-0286 §3:4): the recorder extending it owns the appends,
    #: and a recorder that finds it owned awaits the owner's next append, which carries
    #: its addition, resolved ``True`` once it returned, or ``False`` where the owner
    #: stopped first. No lock is taken (ADR-0306 §5:17).
    extending: bool = field(default=False, repr=False, compare=False)
    extension: asyncio.Future[bool] | None = field(default=None, repr=False, compare=False)
    #: ADR-0280 §6: the stages the controller ran, readable while the pass runs and
    #: written as each ends (ADR-0286 §3), bounded at ``stage_limit`` entries.
    stages: StageRecord = field(default_factory=StageRecord)
    stage_limit: int = DEFAULT_STAGE_RECORD_LIMIT
    #: ADR-0280 §3: the pass's working set — the decisions its stages made, which
    #: the rules read. Held here while the pass runs and never persisted; its shape
    #: is the engine's, which is the one component that knows each decision's type.
    working: object | None = None
    #: ADR-0223's value for this pass's episode, once the pass holds it: computed over
    #: its own supply (§3:2) or retained from a parked turn (§3:3). ``None`` until
    #: then. ADR-0286 §4:3 carries the latest value into every append after that.
    derived_from_external: bool | None = None
    #: The writer's account of this activation's episode, from its admission write.
    capture: EpisodeProgress | None = field(default=None, repr=False)
    #: ADR-0347 §4:1: the story store's position, read by the admission write and
    #: recorded on the episode beside ``started_at``. ``None`` until that write reads
    #: it, and where it could not; never changed once read, as the record keeps it.
    stories_position: int | None = None
    #: ADR-0297 §3: the stop mark, set by :meth:`stop` and never cleared. The
    #: controller reads it before each evaluation of the rules and once each stage's
    #: result is in hand (§4), and a resume reads it before it composes.
    stopped: bool = field(default=False, init=False)
    #: ADR-0332 §3:2, ADR-0349 §3:5: the committed mark, set by acting's commitment step
    #: (:meth:`commit`) before its first call that is not a pure read, or the round's
    #: message, and by an absorption or a take of this activation (§7:7, §7:21); never
    #: cleared. Once set, nothing absorbs it.
    committed: bool = field(default=False, init=False)
    #: ADR-0349 §7:7, §7:21: the inputs it took in beside its trigger's, in the order it
    #: took them in, each naming the activation it was absorbed from or whose offered
    #: input it took; recorded on the episode's ``joined``.
    joined: tuple[JoinedInput, ...] = field(default=(), init=False)
    #: How many of :attr:`joined` a merge brought, each covered by the understanding
    #: version that named it or the meaning its offer carried (§7:9).
    merge_covered: int = field(default=0, init=False)
    #: The order the engine admitted it in, by which "started before" is read (§7:5).
    order: int = field(default=0, init=False)
    #: ADR-0349 §7:5: who wrote the trigger's input, as its place establishes it, and what
    #: it carries; set when the pass begins. ``None`` until then, and on an activation
    #: whose kind establishes no author: it shares nothing (§5:3-§5:5).
    standing: InputStanding | None = None
    #: The trigger's messages, each kept apart and dated, as the pass took them in: what
    #: an absorption or a take brings (ADR-0349 §7:7, §7:21). The line records the same
    #: on its trigger (ADR-0323 §5:4); the hub chat's trigger records none, so its
    #: messages are held here.
    input_messages: tuple[RecordedInputMessage, ...] = ()
    #: ADR-0349 §7:7: the activation that absorbed this one, where one did.
    absorbed_by: str | None = field(default=None, init=False)
    #: §7:21: the older activation that took this one's offered input, where one did.
    handed_to: str | None = field(default=None, init=False)
    #: §7:10: each activation it absorbed or whose offered input it took, and in turn each
    #: one those had, in the order they were taken in: whose findings planning is shown.
    merged: tuple[str, ...] = field(default=(), init=False)
    #: §7:25: each activation it waits on, reached under §7:17, in the order reached.
    waits_on: tuple[str, ...] = field(default=(), init=False)
    #: §7:20-§7:23: the older activation its own open offer is made to, while it is open.
    offered_to: str | None = field(default=None, init=False)
    #: §7:23: each decline of its offer, by the older that declined, with the reason.
    declined: tuple[tuple[str, str], ...] = field(default=(), init=False)
    #: §7:19: the offers open to this activation, by the offering activation, in the
    #: order they were made.
    offers: dict[str, Offer] = field(default_factory=dict, init=False, repr=False)
    #: §7:22: the offers ever made to it that it did not take, open, declined or
    #: withdrawn, each counted toward ``held_input_limit`` from when it was made.
    offers_untaken: int = field(default=0, init=False)
    #: ADR-0349 §10:4: the takeover decision for each understanding version that named an
    #: activation in ``continues``: each one named and what became of it. The working
    #: set's, never persisted.
    takeovers: dict[int, list[Named]] = field(default_factory=dict, init=False, repr=False)
    #: §10:4's last sentence: each take this activation made of an offer, recorded in its
    #: decisions too.
    took: list[Named] = field(default_factory=list, init=False, repr=False)
    #: ADR-0338 §7:1: the activation's person block, assembled once, before understanding,
    #: and read by every planning round, which writes back what §7:10 drops from it.
    #: ``None`` for an activation that is no person's, before assembly, or where no
    #: person-model store is wired.
    person_block: PersonBlock | None = field(default=None, init=False)
    #: Whether the block's assembly was made, whatever it gave: it is made once.
    person_block_assembled: bool = field(default=False, init=False)
    #: Every memory of the person block the activation was given, to understanding or to
    #: a planning round, kept whatever is dropped from the block later (§7:10): what
    #: capture's placement inherits from (ADR-0309 §5:10, ADR-0217 §3), even where no
    #: round is planned.
    person_given: tuple[Memory, ...] = field(default=(), init=False)
    #: The finalization reading was taken (ADR-0280 §6:2): an activation the
    #: controller never ended gains its end entry there, so for a stop it has ended
    #: from that reading on, whether or not the record carries the entry yet.
    _finalized: bool = field(default=False, init=False, repr=False)
    _last_understanding_version: int = field(default=0, init=False, repr=False)
    #: How many inputs each recorded understanding version covers: those the activation
    #: held when the stage that recorded it began (ADR-0332 §3:9, §3:10).
    _covered: dict[int, int] = field(default_factory=dict, init=False, repr=False)

    def gave_person_memories(self, memories: Sequence[Memory]) -> None:
        """Hold memories of the person block the activation was given (ADR-0338 §7:1).

        Args:
            memories: What a stage was shown of the block, each held once.
        """
        held = {id(one) for one in self.person_given}
        self.person_given = (*self.person_given, *(one for one in memories if id(one) not in held))

    @property
    def ended(self) -> bool:
        """Its end entry is appended, by the controller or at finalization (ADR-0297 §3:2)."""
        return self.stages.ended or self._finalized

    def stop(self) -> bool:
        """Set the stop mark, unless the activation has ended (ADR-0297 §3:3).

        The test and the set are **one synchronous step with no await between them**,
        and every end entry is appended in a synchronous step of its own on the same
        event loop, so the two are totally ordered: either the mark is set first and
        the pass's end entry will be the stop's, or the end entry was appended first
        and this finds the activation ended. A mark already set on an activation
        still running is found set, which is a repeated stop's retry of the record
        (§3:7); once the end entry is appended, the activation has ended whatever the
        mark says.

        Returns:
            Whether the activation was still running, its mark now set — ``False``
            exactly where its end entry was already appended, and nothing changed.
        """
        if self.ended:
            return False
        self.stopped = True
        return True

    @property
    def place(self) -> ChannelIdentity | None:
        """The place the activation was started from, where its target names one.

        The hub chat's conversation, the line's chat, an event's channel, the schedule:
        what caused it, and nothing more (ADR-0349 §2:1).
        """
        target = self.trigger.target
        return target if isinstance(target, ChannelIdentity) else None

    @property
    def inputs_held(self) -> int:
        """How many inputs it holds: its trigger's, and each a merge brought (ADR-0349 §9:2)."""
        return 1 + len(self.joined)

    def take_inputs(self, inputs: Sequence[JoinedInput], *, merged: Sequence[str]) -> None:
        """Take in what a merge brings, in the step that stops the other (§7:7, §7:21).

        Each of ``inputs`` names the activation it came from, and is covered by the
        understanding version or the offer's meaning that brought it (§7:9), so no
        understanding runs again for it. ``merged`` are the activations whose findings
        planning is shown from here on (§7:10).
        """
        self.joined = (*self.joined, *inputs)
        self.merge_covered += len(inputs)
        self.merged = (*self.merged, *(one for one in merged if one not in self.merged))

    def commit(self) -> Commitment:
        """Acting's commitment step, before a round's act (ADR-0349 §7:14).

        One synchronous step with no await between the check and the mark: where the
        stop mark is set, the round runs nothing; otherwise the activation is marked
        committed, if it was not already.

        Returns:
            What the step found.
        """
        if self.stopped:
            return Commitment.STOPPED
        self.committed = True
        return Commitment.COMMITTED

    def covers(self, version: int) -> int:
        """How many inputs the recorded understanding ``version`` covers (§3:9)."""
        return self._covered.get(version, 0)

    def recorded_round(
        self, planning_round: PlanningRound, labels: tuple[PlanningLabel, ...]
    ) -> None:
        """Add a planning round and the labels it assigned, after those recorded (§2:3)."""
        self.rounds = (*self.rounds, planning_round)
        self.labels = (*self.labels, *labels)

    def recorded_calls(self, entries: Sequence[RecordedCall]) -> None:
        """Add calls' entries, after those recorded (ADR-0356 §8:6)."""
        self.call_records = (*self.call_records, *entries)

    def recorded_digest(self, digest: ActivationDigest, labels: tuple[PlanningLabel, ...]) -> None:
        """Add a digest and the labels it took, after those recorded (ADR-0308 §5:2)."""
        self.digests = (*self.digests, digest)
        self.labels = (*self.labels, *labels)

    def holds_external(self, *, value: bool) -> None:
        """Record ADR-0223's value as the pass now holds it (ADR-0286 §4:3)."""
        self.derived_from_external = value

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

    def understood(
        self, understanding: ActivationUnderstanding, *, limit: int, inputs: int = 1
    ) -> None:
        """Accumulate one version on the carrier, bounded at ``limit`` (ADR-0276 §7).

        ``inputs`` is how many inputs the version covers: those the activation held when
        the stage that recorded it began (ADR-0332 §3:9), which acting's commitment step
        reads (§3:5).

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
        self._covered[understanding.version] = inputs
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

    def processing(
        self, ended_at: datetime, failure: BaseException | None
    ) -> EpisodeProcessingRecord:
        """Build an immutable terminal record only when admission metadata is complete."""
        # ADR-0297 §3:2: the finalization reading ends the activation for a stop. Set
        # before anything here can raise, in the same synchronous step as the reading
        # of the mark below, so a stop either lands first and this reading is the
        # stop's, or finds the activation ended.
        self._finalized = True
        if self.activation_id is None or self.started_at is None:
            raise ValueError("activation admission metadata is incomplete")
        status, reason = terminal_status(self, failure)
        stages, stages_elided = self._stage_record(ended_at, failure)
        return EpisodeProcessingRecord(
            activation_id=self.activation_id,
            started_at=self.started_at,
            ended_at=ended_at,
            trigger=self.trigger,
            status=status,
            reason=reason,
            output_degraded=self.spoken_degraded,
            understanding=self.understanding,
            understanding_omitted=self._omission(),
            understanding_elided=self.understanding_elided,
            stages=stages,
            recall=self.recall,
            recall_second_run=self.recall_second_run,
            stages_elided=stages_elided,
            rounds=self.rounds,
            labels=self.labels,
            digests=self.digests,
            joined=self.joined,
            stories_position=self.stories_position,
            taken_over_by=self.taken_over_by if reason is ProcessingReason.STOPPED else None,
            call_records=self.call_records,
        )

    @property
    def taken_over_by(self) -> str | None:
        """The activation that took this one's matter, where one did (ADR-0352 §5:2).

        The one that absorbed it (ADR-0349 §7:7), or the one that took its offered input
        (§7:21), as the takeover decisions set them, each in the step that set its stop
        mark. ``None`` for every other activation, one a person stopped included.
        """
        return self.absorbed_by or self.handed_to

    def open_processing(self) -> EpisodeProcessingRecord:
        """The open record as the pass stands now (ADR-0286 §1, §3).

        It carries what the pass has recorded into the record's own fields — the
        trigger as it stands, the understanding versions, the recall results and the
        stage entries ended so far, each under its bound — and no status, reason, end
        time, omission or end entry. ``output_degraded`` stays unset here: the freezing
        write sets it, and an unset field may take a value then (§3:3).

        Raises:
            ValueError: If admission metadata is incomplete.
        """
        if self.activation_id is None or self.started_at is None:
            raise ValueError("activation admission metadata is incomplete")
        entries = self.stages.entries
        if self.stages.ended:
            entries = entries[:-1]
        stages, stages_elided = StageRecord(list(entries)).bounded(self.stage_limit)
        return EpisodeProcessingRecord(
            activation_id=self.activation_id,
            started_at=self.started_at,
            trigger=self.trigger,
            understanding=self.understanding,
            understanding_elided=self.understanding_elided,
            stages=stages,
            recall=self.recall,
            recall_second_run=self.recall_second_run,
            stages_elided=stages_elided,
            rounds=self.rounds,
            labels=self.labels,
            digests=self.digests,
            joined=self.joined,
            stories_position=self.stories_position,
            call_records=self.call_records,
        )

    def _stage_record(
        self, ended_at: datetime, failure: BaseException | None
    ) -> tuple[tuple[StageEntry, ...], int]:
        """The stage record as capture writes it (ADR-0280 §5, §6).

        An activation the controller never ended — cancelled at the admission
        barrier, or ended at the speech edge — gains its end entry here, at the
        finalization reading: ``interrupted`` for a cancellation, ``no_text_input``
        for speech with no words or whose transcription failed, and
        ``ended_before_controller`` for any other end ahead of the controller.

        **A marked pass ends with the stop's end entry** (ADR-0297 §4), ahead of
        every other reading, a cancellation's included — at the point ADR-0280 §5:4
        appends ``interrupted``, for an activation ended before the controller was
        entered.

        The state itself is not changed, so a second finalization reading builds the
        same record, and no exception, status or reason moves.
        """
        if self.stopped:
            rule = ControllerRule.STOPPED
        elif isinstance(failure, asyncio.CancelledError):
            rule = ControllerRule.INTERRUPTED
        elif self.understanding_omitted is UnderstandingOmission.NO_TEXT:
            rule = ControllerRule.NO_TEXT_INPUT
        else:
            rule = ControllerRule.ENDED_BEFORE_CONTROLLER
        return self.stages.bounded(self.stage_limit, ending=(rule, ended_at))

    def _omission(self) -> UnderstandingOmission | None:
        """ADR-0276 §5's classification, by where the pass ended and never by its text.

        A pass that recorded a version records no omission, whatever ended it.
        Otherwise the branch the pass took — ``no_text``, ``failed`` — or
        ``not_reached`` for everything that ended ahead of the stage's entry: a
        cancellation, an expired deadline, a failure in any step before it.
        """
        if self.understanding:
            return None
        if self.understanding_omitted is not None:
            return self.understanding_omitted
        return UnderstandingOmission.NOT_REACHED

    def reserved_report(self) -> EpisodeCaptureReport:
        """Bound the receipt before capture, at the address fixed at admission.

        ADR-0283 §2: every episode's id is ``activation:<activation_id>``, on every
        channel, so the receipt is sized at the very address capture writes and no
        placeholder is sized.
        """
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=self.episode_address, state="degraded"
        )

    @property
    def episode_address(self) -> str | None:
        """The episode's id, ``activation:<activation_id>`` (ADR-0283 §2), once admitted."""
        return None if self.activation_id is None else f"activation:{self.activation_id}"

    def degraded_report(self) -> EpisodeCaptureReport:
        """Name the episode only where its conversation recorded it, never claiming more."""
        return EpisodeCaptureReport(
            activation_id=self.activation_id, episode_id=self.recorded_episode_id, state="degraded"
        )


@dataclass
class ActivationScope:
    """One worker's holder of its admission, readable in a tracked child."""

    state: ActivationState | None = None


CURRENT_ACTIVATION: ContextVar[ActivationScope | None] = ContextVar("activation", default=None)


def active_state() -> ActivationState | None:
    """Read only this worker's admission, including one established by its child."""
    scope = CURRENT_ACTIVATION.get()
    return None if scope is None else scope.state


def admit_channel(  # noqa: PLR0913 — the input, its reply, the two metadata seams, the stage bound and the messages it took in
    input: ChannelInput,  # noqa: A002 — channel contract parameter
    reply: ReplyCapability | None,
    *,
    clock: Clock,
    id_factory: Callable[[], str],
    stage_limit: int = DEFAULT_STAGE_RECORD_LIMIT,
    messages: Sequence[RecordedInputMessage] = (),
    carries_outside_mark: bool = False,
) -> ActivationState:
    """Allocate capture metadata after channel validation, without making it admission policy.

    The trigger's ``parties`` are what the channel's kind declares of its input
    (ADR-0351 §3:1), read from the one declaration beside the dispatch table and fixed
    on the episode here (§2:8), and each of its ``messages`` carries the party the kind
    declares for it: the owner's for one the sender wrote, a forward's original sender,
    claimed, for a forward (§2:6, §2:7). ``declared_input`` refuses a channel type that
    declares none; the dispatch table has already refused every such type by the time
    this runs.

    A channel that is not a conversation is on its own channel from admission, as an
    event's is, so its episode is read by it (ADR-0283 §1, ADR-0323 §10); a
    conversation's is named once its lifecycle has resolved it (ADR-0275 §4:5).
    ``messages`` are each message the input took in, recorded on the trigger
    (ADR-0323 §5:4); none for a channel that records none. ``carries_outside_mark`` is
    whether the input carries the outside-content mark, as an occurrence of a scheduled
    task carrying it does (ADR-0350 §3:8): its kind declares its parties for that, with
    unknown beside the assistant's statement (ADR-0351 §3:6).
    """
    parties, recorded = declared_input(
        input.target, messages, carries_outside_mark=carries_outside_mark
    )
    on_its_channel = (
        isinstance(input.target, ChannelIdentity) and input.target.channel_type != "conversation"
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
            channel=(
                input.target
                if on_its_channel and isinstance(input.target, ChannelIdentity)
                else None
            ),
            payload=payload,
            context=input.context,
            reply=reply,
            parties=parties,
            messages=recorded,
        ),
        activation_id=activation_id,
        started_at=started_at,
        conversation_id=(
            input.target.instance_id
            if isinstance(input.target, ChannelIdentity) and not on_its_channel
            else None
        ),
        stage_limit=stage_limit,
    )


def canonical_activation_id(minted: object) -> bool:
    """Whether ``minted`` is canonical UUID4 text, which an activation id is (ADR-0275 §6:1)."""
    if not isinstance(minted, str):
        return False
    try:
        value = UUID(minted)
    except ValueError:
        return False
    return value.version == 4 and str(value) == minted  # noqa: PLR2004 — mandated UUID version


def _metadata(clock: Clock, id_factory: Callable[[], str]) -> tuple[str | None, datetime | None]:
    activation_id = None
    started_at = None
    try:
        minted = id_factory()
        if not canonical_activation_id(minted):
            raise ValueError("activation IDs require canonical UUID4 text")
        activation_id = minted
    except Exception:
        _log.warning("activation_capture_degraded", stage="admission", reason="identifier")
    try:
        started_at = clock()
    except Exception:
        _log.warning("activation_capture_degraded", stage="admission", reason="clock")
    return activation_id, started_at


def terminal_status(  # noqa: PLR0911 — ADR-0275's ordered terminal branches, and ADR-0276 §6's row among them
    state: ActivationState, failure: BaseException | None
) -> tuple[ProcessingStatus, ProcessingReason]:
    """Apply ADR-0275's ordered terminal conditions without interpreting response prose.

    ADR-0275 §5:3's table without rows 5, 8, 9 and 10, which classified the old
    path's composition failure and its parks and questions, and with row 6 reading
    "another declared operational error" alone (ADR-0318 §5:2).

    A pass whose end entry is the stop's — whose mark is set, which is the same fact
    (ADR-0297 §3:3) — is ``interrupted / stopped``, ahead of every other row, the
    cancellation row included (ADR-0297 §4).

    A phases pass that returned unfinished (:attr:`ActivationState.unfinished`) is
    ``failed / processing_failed``: it could not finish, so the state shows *couldn't
    finish* beside the message saying so (ADR-0293 §8:3, ADR-0317 §3:5). One that
    returned silent has finished, and is ``completed / returned`` (ADR-0317 §2:3).
    """
    if state.stopped:
        return ProcessingStatus.INTERRUPTED, ProcessingReason.STOPPED
    if isinstance(failure, asyncio.CancelledError):
        return ProcessingStatus.INTERRUPTED, ProcessingReason.CANCELLED
    if isinstance(failure, ModelTimeoutError | SpeechTimeoutError):
        return ProcessingStatus.FAILED, ProcessingReason.TIMEOUT
    # No failure classifies as a transcription failure since ADR-0313 §3:1 retired
    # `converse_spoken`, whose `TranscriptionFailedError` was the one that did.
    # ADR-0276 §6: immediately below transcription failure and above output oversize.
    # The flag carries the reason through the event path's outward mapping.
    if isinstance(failure, UnderstandingError) or (
        failure is not None and state.understanding_unparseable
    ):
        return ProcessingStatus.FAILED, ProcessingReason.UNDERSTANDING_FAILED
    if isinstance(failure, OversizedValueError):
        return ProcessingStatus.FAILED, ProcessingReason.OUTPUT_OVERSIZED
    if isinstance(failure, AssistantError) or (failure is None and state.unfinished):
        return ProcessingStatus.FAILED, ProcessingReason.PROCESSING_FAILED
    if failure is not None:
        return ProcessingStatus.FAILED, ProcessingReason.INTERNAL_ERROR
    if state.no_words:
        return ProcessingStatus.COMPLETED, ProcessingReason.NO_CONTENT
    return ProcessingStatus.COMPLETED, ProcessingReason.RETURNED
