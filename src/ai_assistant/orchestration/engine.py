"""The engine façade an interface adapter drives (ADR-0042 §1, §3, §4).

:class:`Engine` is the single, concrete surface `interfaces/` depends on. It is
**not** a Protocol (ADR-0042 §1): there is one orchestration engine and one class
of consumer, so a contract modelling substitutability would encode a
substitutability that does not exist, and pay a triad's cost for it. Its
collaborators are addressable to the adapter only through the façade's own methods
(ADR-0042 §1); sequencing them is the orchestration this package owns, and an
adapter doing it would pull pipeline logic into `interfaces/` (ADR-0042
Alternatives).

**The phases plan every activation** (ADR-0309 §2:6). A message written into a
conversation is taken in by the chat's reader, whose activation the phases run and
which writes its own messages as it runs (ADR-0293 §6, ADR-0307 §3); an
informational event is admitted by :meth:`Engine.receive` and runs through them as
one activation whose place takes no message (ADR-0313 §4). The controller runs each
pass's stages by ADR-0309 §3's table.

Beside them sits the **inspection surface** — :meth:`Engine.beliefs`,
:meth:`Engine.belief` and
:meth:`Engine.forget` — lets a person read what the assistant believes about them
and destroy any of it (:class:`Belief`; ADR-0073 §7). Inspection is where
:func:`~ai_assistant.core.types.band_of` is applied, **once**: classifying a record
into its band is ADR-0072 §1's projection, and an adapter doing it would put that
projection in `interfaces/` (ADR-0073 §7).

Beside those sits the **maintenance surface** ADR-0083 §8 adds for that scheduler:
:meth:`Engine.start`'s sweeps, :meth:`Engine.purge_expired`,
:meth:`Engine.notice_upcoming_events`, :meth:`Engine.tidy_stories`,
:meth:`Engine.decide_story_flags`, :meth:`Engine.observe_episodes` and
:attr:`Engine.drain_phase`. New *concrete* surface on
this class rather than ``core`` contract surface — the scheduler holds this object from
inside the hub, not the ``AssistantEngine`` Protocol a client sees, which names none of
these.

**No operation here reads a source to propose what it read into memory**
(ADR-0294 §1). The calendar's and the email source's scheduled ingestion are
retired; what a reader still feeds is the upcoming-event producer, over its own
reader instance and under its own grant use (ADR-0294 §2). The request-path facet
it also fed left with the old path (ADR-0318 §6:2).

Nothing concrete is imported: every collaborator arrives by injection and is seen
only through its Protocol or through this package's own stage objects (CLAUDE.md
golden rule 1). The wiring that constructs the concrete subsystems is the
composition root's, a separate package (ADR-0042 §2).
"""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Final, TypeVar, cast
from zoneinfo import ZoneInfo

import structlog

from ai_assistant.core.channel_validation import message_party, origin_kind, snapshot
from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.device_context import (
    current_requesting_device,
    without_requesting_device,
)
from ai_assistant.core.episode_encoding import check_detail, check_list
from ai_assistant.core.errors import (
    ActivationStoppedError,
    ConfigurationError,
    MemoryStoreError,
    MemoryStoreStaleError,
    ModelError,
    ModelTimeoutError,
    NotificationBudgetError,
    OversizedValueError,
    PlanningError,
    SpeechError,
    StoryStoreError,
    TraceStoreError,
    UnderstandingError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    OWNER_PERSON_ID,
    ActivationEnding,
    ActivationRecall,
    ActivationStop,
    ApprovalCardState,
    ApprovalChoice,
    ApprovalGiver,
    ApprovalOutcomePush,
    ApprovalPanel,
    ApprovalPanelEntry,
    ApprovalPanelTap,
    ApprovalPanelTapAnswer,
    ApprovalRequestState,
    ApprovalStepAnswer,
    ApprovalTap,
    AskedCall,
    Belief,
    BeliefSummary,
    ChannelContext,
    ChannelContextItem,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ControllerStage,
    ConversationSummary,
    DueAfterTasks,
    DueOnRule,
    EpisodeCaptureReport,
    EpisodeChunk,
    EpisodePage,
    EpisodicMemory,
    InformationalEventResult,
    Memory,
    MemoryKind,
    MemoryWrite,
    MemoryWriteMode,
    MessageAuthor,
    Modality,
    NotificationDelivery,
    OccurrencePush,
    OccurrenceState,
    PendingCandidate,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingStatus,
    ProvisioningState,
    RecallOutcome,
    RecordedInputMessage,
    RecordedTextInput,
    ReplyCapability,
    SpokenAudioFormat,
    SpokenRendering,
    SpokenReply,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StoryNoteId,
    StoryOutcome,
    SupportPart,
    TextChannelPayload,
    WholeTextReply,
    approval_choice,
    belief_summary,
    belief_view,
    chat_conversation_ids,
    check_chat_cursor,
    check_chat_position,
    check_story_page,
    checked_chat_devices,
    describe_untrusted,
    episode_summary,
    episode_view,
    part_episode,
    person_model_lists,
    profile_field,
    profile_value,
    secret_value,
    story_members,
    story_move_members,
    story_note_ids,
    story_note_text,
    user_message,
)
from ai_assistant.orchestration import person_panel
from ai_assistant.orchestration.activation_coordinator import ActivationCoordinator
from ai_assistant.orchestration.activation_state import (
    CURRENT_ACTIVATION,
    ActivationScope,
    ActivationState,
    active_state,
    admit_channel,
    terminal_status,
)
from ai_assistant.orchestration.activation_writer import capture_loss
from ai_assistant.orchestration.approval_calls import (
    ApprovalCalls,
    ApprovalsSeams,
    CardFacts,
    card_state,
    card_text,
)
from ai_assistant.orchestration.approval_sensor import ApprovalsSensor
from ai_assistant.orchestration.approvals import (
    REQUEST_APPROVAL_CAPABILITY,
    THE_APPROVALS,
    Ticket,
    approval_input,
    ticket_of,
)
from ai_assistant.orchestration.candidates import held_candidates
from ai_assistant.orchestration.change_stream import Activity, ChangeStream
from ai_assistant.orchestration.channel_kinds import place_of
from ai_assistant.orchestration.channels import (
    UNCAPTURED,
    ChannelProjection,
    ResolvedChannelInput,
    captured_result,
)
from ai_assistant.orchestration.chat import (
    CHAT_TURN_BUDGET,
    CHAT_WINDOW_SIZE,
    DEFAULT_CHAT_COMPOSING_CAP,
    DEFAULT_CHAT_COMPOSING_LAPSE,
    DEFAULT_CHAT_START_WAIT,
    ChatInput,
    ChatReader,
)
from ai_assistant.orchestration.controller import (
    ACTIVATION_RULES,
    DEFAULT_STAGE_RECORD_LIMIT,
    ActivationController,
    ControllerStageRun,
    PassFacts,
    Stage,
    StageRecord,
    StageResult,
    TolerantStage,
)
from ai_assistant.orchestration.conversations import (
    check_devices_fit,
    check_message_fits,
    episode_conversation,
    fit_changes,
    fit_transcript,
)
from ai_assistant.orchestration.defects import is_defect, log_defect
from ai_assistant.orchestration.device_checks import DeviceChecks, device_changes
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    TurnSupply,
    notification_is_speakable,
)
from ai_assistant.orchestration.episode_reads import fit_chunk, fit_page, without_open_episodes
from ai_assistant.orchestration.matters import (
    DEFAULT_HELD_INPUT_LIMIT,
    DEFAULT_IN_PROGRESS_LIMIT,
    Became,
    Matters,
    input_standing,
)
from ai_assistant.orchestration.notifications import RulingPolicy, hand_off
from ai_assistant.orchestration.outside_content import relayed_by
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_keyless_call,
    check_payload,
    check_provisioning_call,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
)
from ai_assistant.orchestration.person_block import activation_person, person_zone, still_held
from ai_assistant.orchestration.phase_path import PlaceTarget, Scheduling, failing_stage
from ai_assistant.orchestration.planning import PlaceAuthor, PlaceItem, exact_line
from ai_assistant.orchestration.recall import Recalled
from ai_assistant.orchestration.speech import (
    DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
    classify_speech_failure,
)
from ai_assistant.orchestration.stories import (
    DEFAULT_STORY_SUMMARY_VIEW_NOTES,
    fitted,
    owner_summary,
    resolved_view,
    unknown_activation,
)
from ai_assistant.orchestration.story_links import StoryLinksDecision
from ai_assistant.orchestration.story_standing import OWNER_READER
from ai_assistant.orchestration.story_standing import story_standing as standing_of
from ai_assistant.orchestration.support_parts import (
    episodes_to_read,
    part_content,
    remember_activations,
    requests_to_read,
)
from ai_assistant.orchestration.task_manager import (
    PlaceLists,
    ScheduledTaskCalls,
    TaskManager,
    TaskSchedulerSeams,
)
from ai_assistant.orchestration.task_rules import PersonZones, rule_push, task_zone
from ai_assistant.orchestration.task_scheduler import (
    SCHEDULE,
    SPAWNING_KINDS,
    LineageStep,
    ListedPlace,
    StillLive,
    lineage_occurrence,
    lineage_steps,
    task_input,
)
from ai_assistant.orchestration.task_sensor import SensorLimits, TaskSchedulerSensor
from ai_assistant.orchestration.telegram import (
    LINE_GIVER,
    TELEGRAM,
    TelegramReader,
    TelegramWriter,
)
from ai_assistant.orchestration.traces import Observation, OperationTraces
from ai_assistant.orchestration.understanding import (
    ChannelWindow,
    SuppliedWindow,
    TranscriptWindow,
    fetch_held,
    place_window_links,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        AuditTrail,
        DiagnosticRetention,
        DiagnosticSink,
        MemoryStore,
        NotificationPolicy,
        NotificationStore,
        PlanStore,
        SourceReadTrail,
        SpeechSynthesizer,
        SpeechTranscriber,
        SpendLedger,
        StoryStore,
        TraceRetention,
        TraceSink,
    )
    from ai_assistant.core.types import (
        ActivationUnderstanding,
        ApprovalRequest,
        BeliefBand,
        ChatChanges,
        ChatDevice,
        ChatStreamChunk,
        ChatStreamEnd,
        ConnectedAccount,
        ConnectionAct,
        Conversation,
        ConversationDigest,
        DueOccurrence,
        EncodableText,
        GrantableSource,
        GrantScope,
        HeldNotification,
        Identifier,
        MessageReceipt,
        NonBlankEncodableText,
        NotificationCandidate,
        NotificationDisposition,
        NotificationPreferences,
        PermissionDecision,
        PersonModelEdit,
        PersonModelList,
        PersonModelView,
        ProfileChange,
        ProfileField,
        RecordedCall,
        RecordedChannelTrigger,
        RecordedInvocation,
        RequestingDevice,
        RulePush,
        ScheduledTask,
        SecretValue,
        SourceGrant,
        SourceReadRecord,
        SpendTotal,
        SpokenAudio,
        StoryHeader,
        StoryLogPage,
        StoryNoteOutcome,
        StoryPage,
        StoryStanding,
        StorySummaryView,
        StoryView,
        TranscriptPage,
        UserMessage,
    )
    from ai_assistant.orchestration.connections import ConnectionOperations
    from ai_assistant.orchestration.conversations import ConversationLifecycle
    from ai_assistant.orchestration.delivery import DeliveryOutbox
    from ai_assistant.orchestration.grants import GrantOperations
    from ai_assistant.orchestration.matters import InProgressEntry
    from ai_assistant.orchestration.matters_pass import MattersPass, MattersPassReport
    from ai_assistant.orchestration.notifications import PolicyForZone
    from ai_assistant.orchestration.observer import Observer, RunOutcome
    from ai_assistant.orchestration.person_block import PersonBlock, PersonBlocks
    from ai_assistant.orchestration.phase_path import PhasePath, PhaseWorking
    from ai_assistant.orchestration.recall import RecallStage
    from ai_assistant.orchestration.story_links import (
        Candidates,
        StoryCandidates,
        StoryLinksStage,
    )
    from ai_assistant.orchestration.story_tidy_up import ScheduledTidyUp, ScheduledTidyUpReport
    from ai_assistant.orchestration.telegram import TelegramInput, TelegramLineSeams
    from ai_assistant.orchestration.understanding import (
        Fetched,
        UnderstandingStage,
        Windows,
        WindowsStage,
    )
    from ai_assistant.orchestration.upcoming import UpcomingEventStage

_log = structlog.get_logger(__name__)

#: What a pass whose deadline expired before or inside the understanding stage says
#: (ADR-0276 §5, §6): code-owned, so no provider content reaches the caller.
_UNDERSTANDING_EXPIRED: Final = "the pass's deadline expired during understanding"
_RECALL_EXPIRED: Final = "the pass's deadline expired during recall"
_WINDOWS_EXPIRED: Final = "the pass's deadline expired while assembling the windows"
_STORY_LINKS_EXPIRED: Final = "the pass's deadline expired while recording the story links"
_TAKEOVER_EXPIRED: Final = "the pass's deadline expired before the takeover"


class _NothingTakenInError(Exception):
    """The reader's activation marked none of its input taken in, so it did nothing."""


def _unchecked(_result: object) -> None:
    """No output check: the reader's activation returns to no caller (ADR-0293 §10).

    What it produced is written into the conversation by the chat's writer, which holds
    the message to its own bound (:func:`~ai_assistant.orchestration.conversations.fitted_message`).
    """


_T = TypeVar("_T")


def _elapsed_since(started: datetime, now: datetime) -> timedelta:
    """How long a poll has run, never negative.

    A clock that steps backwards would otherwise lengthen the budget rather than
    spend it, and on a maximal budget the subtraction against it would overflow.
    """
    elapsed = now - started
    return max(elapsed, timedelta(0))


#: ADR-0131 §5a's ``hub_max_notification_budget``, as the figure this engine
#: refuses a poll above. Carried as a default so an engine built without the hub's
#: ``Settings`` still refuses the same range rather than none: §5a is explicit that
#: none of its five figures is nullable, because "a hub serving delivery with… no
#: budget bound… has the failure the clause naming it exists to prevent".
_DEFAULT_MAX_NOTIFICATION_BUDGET = timedelta(seconds=300)

#: The page size every enumeration on this surface returns by saying nothing is
#: :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and the three private
#: constants that used to carry the figure in this package are gone (ADR-0085 §3a):
#: the Protocol states these defaults, so they need a public name to refer to, and
#: the default is a **contract clause** rather than a signature detail — an
#: implementation called without ``limit`` behaves as though it had been passed.
#: It is still relayed explicitly on every store call, so a store whose own default
#: drifted could not silently change what this surface returns.

#: What :meth:`Engine._reject_if_closing` raises a ``RuntimeError`` *saying*.
#:
#: Public and named because ADR-0083 §8 makes a caller act on it: "the scheduler
#: treats the ``RuntimeError`` that ``_reject_if_closing`` raises… as **stop**, not
#: as a job failure to log and retry". A caller that has to tell *this*
#: ``RuntimeError`` from any other one needs something to compare against, and the
#: alternatives are worse in both directions — treating every ``RuntimeError`` as a
#: shutdown would silence real bugs by turning them into a clean exit, and matching
#: a message re-spelled at the comparison site would stop matching the moment this
#: one is reworded. Sharing the constant makes the two sides the same object, so
#: they cannot drift.
#:
#: The exception *type* is deliberately unchanged: ``RuntimeError`` is what
#: ``AssistantEngine``'s Protocol docstrings declare every public method raises when
#: the engine is closing, and narrowing it to a subclass here would be contract
#: surface (golden rule 5) for a distinction only one caller needs.
ENGINE_SHUTTING_DOWN: Final = "the engine is shutting down and is not accepting new work"


class DrainPhase(StrEnum):
    """Which phase of ADR-0083 §4's two-phase drain a shutdown ended in.

    Read by the hub *after* :meth:`Engine.aclose` returns, so a shutdown that has
    completed says how it completed (#559). Phase B is the transition an operator
    most needs to see: it is the only one where in-flight work was actively
    cancelled, and the only one whose tail ADR-0083 §4 leaves unbounded.
    """

    #: :meth:`Engine.aclose` has not been entered, or has not reached the drain.
    NOT_RUN = "not_run"
    #: Every tracked task finished **on its own** — either nothing was in flight,
    #: or phase A's budget was enough. Nothing was cancelled.
    QUIESCED = "phase_a_quiesced"
    #: Phase A's budget was reached; the remainder was cancelled and then awaited
    #: to completion, unbounded (ADR-0083 §4).
    CANCELLED = "phase_b_cancelled"


@dataclass(frozen=True, slots=True)
class _SupportReading:
    """One page's supports, resolved (ADR-0328 §15:2, §15:7).

    Attributes:
        contents: Each part's readable content, or ``None`` where it is gone.
        held: The episodes the store still holds, of those the page's parts point into.
    """

    contents: Mapping[SupportPart, str | None]
    held: frozenset[str]

    def all_gone(self, memory: Memory) -> bool:
        """Whether none of ``memory``'s supports' episodes resolves (§15:7).

        Keyed on the episode, as §15:7 is: a part missing from an episode the store
        still holds is shown as gone, but the episode resolves. A legacy support points
        into no episode, and is gone where the record it carries has no content.
        """
        return all(
            self.contents.get(support.points_at) is None
            if (episode := part_episode(support.points_at)) is None
            else episode not in self.held
            for support in memory.supports
        )


@dataclass(frozen=True, slots=True)
class PurgeReport:
    """What one retention sweep physically reclaimed (ADR-0083 §7, §8).

    The result of :meth:`Engine.purge_expired`, which is **one** job over every
    store swept on a horizon, never a sweeping mechanism per store (ADR-0083 §7).
    ADR-0119 §10 sends the trace store to the same place rather than giving the
    seventh database a job of its own.

    The memory count is reclamation, not visibility: the memory store already
    hides what is past its deadline at *read* time (ADR-0007 §2), so a sweep that
    never runs leaves expired rows on disk and changes no answer. The trace count
    is different, and ADR-0119 §10 says why: "the horizon is enforced by deletion
    only… there is no read-time retention filter", so what this sweep does not
    delete is what a walk still returns.

    The counts are here so the job can say what it did — a sweep whose log line is
    indistinguishable from a sweep that found nothing is the shape #559 objects to
    at the other end of the lifecycle.

    A plain dataclass rather than a ``core`` DTO **deliberately**: this is
    maintenance surface on a concrete class in ``orchestration`` (ADR-0083 §8), not
    something that crosses a subsystem boundary, and the only caller is the
    scheduler that lives above the composition root.
    """

    #: Expired :class:`~ai_assistant.core.types.MemoryRecord` rows removed.
    records: int
    #: :class:`~ai_assistant.core.types.EvaluationTrace` rows past the horizon
    #: removed, or ``None`` where the horizon is "keep forever" and the sweep was
    #: therefore **not run** (ADR-0119 §10). ``None`` rather than ``0`` for the
    #: reason ADR-0083 §7 makes a disabled job's interval ``None`` and never zero:
    #: "off" and "found nothing" are different facts about a run, and a value that
    #: conflates them is the one an operator cannot recover afterwards.
    traces: int | None
    #: Purgeable held-notification rows removed, or ``None`` where no notification
    #: store is wired and the sweep was therefore **not run** (ADR-0130 §7).
    #: ``None`` rather than ``0`` for :attr:`traces`' reason: "not wired" and
    #: "found nothing" are different facts about a run.
    notifications: int | None = None
    #: Diagnostic-record files past their window deleted (ADR-0314 §7:2), or ``None``
    #: where no record is wired and the sweep was therefore **not run**, for
    #: :attr:`notifications`' reason.
    diagnostics: int | None = None


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_positive_int(value: int, *, name: str) -> None:
    """Refuse a constructor knob that is not a positive integer.

    Two of this façade's knobs are byte bounds, and each fails *open and
    silently* rather than loudly when it cannot bind: ``float("nan")`` compares
    ``False`` against every ``>``, so a bound built from one admits everything while
    the engine reports health, and a ``float`` count truncates somewhere later
    instead.

    **An allowlist of the exact ``int``, not a denylist naming ``bool``**, which is
    the rule ``core.config``'s own integer-setting validator states in these words:
    "every value this refuses — ``bool``, and any other ``int`` subclass whose
    instances mean something other than their integer value — is precisely an
    ``isinstance`` match". A ``bool`` is the familiar case (a flag is not a count,
    and as a byte bound it is a one-byte one), but it is not the only one and the
    denylist form cannot close the class: an ``int`` subclass overriding ``__lt__``
    passes a positivity check, and — because Python gives a subclass's *reflected*
    comparison priority — one overriding ``__gt__`` then answers every
    ``size > limit`` this engine performs, which is the fail-open this guard exists
    to prevent. ``numpy.bool_`` is the other end of the same class: a flag by any
    reading, not a ``bool`` subclass, and producible here (ADR-0024's embedder).

    The refusal describes the value through :func:`describe_untrusted` rather than
    ``repr``, because the value is untrusted at exactly this seam: an object whose
    ``__repr__`` raises would otherwise destroy the diagnosis from inside the
    message that reports it, and the caller would see that object's exception in
    place of the ``TypeError`` this constructor documents.

    Written once so the three guards are identical **by construction** rather than by
    copy. The canonical fake holds its own copies of these arguments to the same
    words (ADR-0084 §4, which runs in both directions), and a guard that drifted in
    class or in wording would make the two implementations disagree about what kind
    of failure a bad deployment is.

    Args:
        value: The knob as the caller passed it.
        name: The parameter's name, which is what the refusal names.

    Raises:
        TypeError: If it is not an exact ``int`` — ``bool`` and every other
            subclass included.
        ValueError: If it is not positive.
    """
    if type(value) is not int:
        msg = f"{name} must be an integer, got {describe_untrusted(value)}"
        raise TypeError(msg)
    if value < 1:
        msg = f"{name} must be positive, got {value}"
        raise ValueError(msg)


def _check_diagnostic_sweep(
    retention: DiagnosticRetention | None, window: timedelta | None
) -> None:
    """Refuse a diagnostic sweep given its seam without its window, or the reverse.

    Raises:
        ValueError: If exactly one of the two is given (ADR-0314 §7:2).
    """
    if (retention is None) != (window is None):
        msg = "the diagnostic record's sweep takes its seam and its window together"
        raise ValueError(msg)


#: The oldest instant a horizon can name, and therefore one nothing predates.
#: A valid ``UtcInstant`` — ``canonical_utc`` accepts it — though *not* a valid
#: clock reading, which ADR-0026 §3 keeps a day clear of this boundary so a
#: reading survives localization. A horizon is neither localized nor read from a
#: clock, so the boundary itself is available to it.
_INSTANT_FLOOR: Final = datetime.min.replace(tzinfo=UTC)


def _horizon(now: datetime, retention: timedelta) -> datetime:
    """The instant ``retention`` before ``now``, saturating at :data:`_INSTANT_FLOOR`.

    **Saturating rather than raising, because the input is accepted
    configuration.** ADR-0119 §10 refuses a horizon only for being non-finite or
    non-positive, so ``trace_retention`` may be any positive duration a
    ``timedelta`` can hold — up to 999999999 days, three orders of magnitude past
    the calendar. Subtracting one of those from any real clock reading raises
    ``OverflowError``, and it would do so *inside* the maintenance operation,
    after the two Tier 1 sweeps had already run, on every tick — a hub whose
    retention job never completes because a setting asked for more history than
    there are dates.

    The saturated answer is not a guess: a horizon nothing can predate deletes
    nothing, which is exactly what "keep traces for longer than the calendar"
    means. It stays distinguishable from "keep forever", which is ``None`` and
    does not call the sweep at all (:attr:`PurgeReport.traces`).

    Args:
        now: The clock reading, already guarded by
            :func:`~ai_assistant.core.clock.checked_clock`.
        retention: The horizon's length; positive, per ``Settings``.

    Returns:
        The instant to sweep below.
    """
    # Computed as a comparison rather than caught as an ``OverflowError``: this
    # subtraction is always representable (the widest possible gap between two
    # datetimes is exactly ``timedelta.max``), so the guard is total without
    # depending on which operation raises first.
    if retention > now - _INSTANT_FLOOR:
        return _INSTANT_FLOOR
    return now - retention


def _utcnow() -> datetime:
    """Read the instant the trace horizon is measured back from (ADR-0119 §10).

    The default reading, guarded by
    :func:`~ai_assistant.core.clock.checked_clock` at construction exactly as
    :class:`~ai_assistant.orchestration.conversations.ConversationLifecycle`
    guards its own — a horizon is subtracted from this, so a non-conforming
    reading would sweep against an instant nobody chose.
    """
    return datetime.now(UTC)


def _purged(report: PurgeReport) -> Observation:
    """Read one maintenance sweep onto its own ``OPERATION`` trace (ADR-0119 §8).

    **``traces`` is absent when the horizon is "keep forever"**, and that is §3's
    observation rule rather than a convenience: "a metric key appears in a trace
    only when the quantity it names was **observed**. An absent key means *not
    observed* and never zero". :attr:`PurgeReport.traces` is ``None`` for exactly
    that reason — the sweep did not run — and writing a zero would report a store
    swept clean by a sweep that never happened.

    Args:
        report: What the stores reclaimed. ``notifications`` is absent for
            ``traces``' reason, there being no notification store wired.

    Returns:
        The counts, keyed by literals written here (§2's second clause).
    """
    metrics: dict[str, int | float | bool] = {
        "records": report.records,
    }
    if report.traces is not None:
        metrics["traces"] = report.traces
    if report.notifications is not None:
        metrics["notifications"] = report.notifications
    if report.diagnostics is not None:
        metrics["diagnostics"] = report.diagnostics
    return Observation(metrics=metrics)


def _noticed(count: int) -> Observation:
    """Read one producer run onto its own ``OPERATION`` trace (ADR-0119 §8).

    **The count and nothing else.** ADR-0004 §5 keeps Tier 1 content out of the
    operational record, and a producer's candidates are free text drawn from the
    user's calendar — the summary is literally the entry's own rendered line.

    Args:
        count: How many candidates were offered.

    Returns:
        The count, keyed by a literal written here (§2's second clause).
    """
    return Observation(metrics={"noticed": count})


def _matters_decided(report: MattersPassReport) -> Observation:
    """Read one matters-pass run onto its own ``OPERATION`` trace (ADR-0119 §8).

    Code-owned counts only: no story id and nothing of any summary (ADR-0004 §5).

    Args:
        report: What the run found and decided.

    Returns:
        The run's counters, keyed by literals written here (§2's second clause).
    """
    return Observation(
        metrics={
            "flags": report.flags,
            "waiting": report.waiting,
            "left_by_rule": report.left_by_rule,
            "decided": report.decided,
            "left_after_refusal": report.left_after_refusal,
            "refused": report.refused,
            "raced": report.raced,
            "exhausted": report.exhausted,
        }
    )


def _stories_tidied(report: ScheduledTidyUpReport) -> Observation:
    """Read one scheduled tidy-up run onto its own ``OPERATION`` trace (ADR-0119 §8).

    Code-owned counts only: no story id and nothing of any summary (ADR-0004 §5).

    Args:
        report: What the run found and tidied.

    Returns:
        The run's counters, keyed by literals written here (§2's second clause).
    """
    return Observation(
        metrics={
            "due": report.due,
            "tidied": report.tidied,
            "written": report.written,
            "not_written": report.not_written,
            "passed_over": report.passed_over,
            "exhausted": report.exhausted,
        }
    )


def _observed(outcome: RunOutcome) -> Observation:
    """Read one observer run onto its own ``OPERATION`` trace (ADR-0119 §8).

    Code-owned counts only: no episode id, no claim and nothing of any memory (ADR-0004
    §5, ADR-0329 §15:7).

    Args:
        outcome: What the run did.

    Returns:
        The run's counters, keyed by literals written here (§2's second clause).
    """
    return Observation(
        metrics={
            "busy": outcome.busy,
            "processed": outcome.processed,
            "skipped": outcome.skipped,
            "waiting": outcome.waiting,
            "stuck": outcome.stuck,
            "held": outcome.held,
        }
    )


def _ruled(count: int) -> Observation:
    """Read one reconsideration run onto its own ``OPERATION`` trace (ADR-0119 §8).

    Args:
        count: How many held records were re-ruled.

    Returns:
        The count, keyed by a literal written here (§2's second clause).
    """
    return Observation(metrics={"reconsidered": count})


async def _as_tuple[T](page: Awaitable[list[T]]) -> tuple[T, ...]:
    """Materialise a store's page as the tuple the contract returns.

    Args:
        page: The store call.

    Returns:
        Its rows, as a tuple — ADR-0085 §3b's rule that every enumeration on the
        surface returns one, so no caller can mutate a page it was handed.
    """
    return tuple(await page)


async def _ordered_decisions(
    read: Awaitable[list[PermissionDecision]],
) -> tuple[PermissionDecision, ...]:
    """Await one audit-trail read and put ADR-0186 §2's total order on what it returned.

    **The sort is owed here rather than assumed from the store**, and that is
    ADR-0186 §2's own clause: ``AuditTrail.export`` "states no order and this ADR
    adds none to it; an implementation relaying a store read that arrives unordered
    owes the sort, over a list it has already materialised". Both shipped trails
    happen to promise ``recent``'s order for ``export`` too, in their own
    docstrings — so an engine that wrote ``tuple(await trail.export())`` would pass
    every test driven through either of them and be wrong the day a conforming trail
    returned insertion order, taking §2's prefix guarantee with it.

    Applied to the **listing** as well, though ``AuditTrail.recent``'s contract does
    fix the order: one helper for both is what makes the two answers comparable by
    construction rather than by two implementations agreeing, and re-sorting a
    conforming page changes nothing about which rows it holds.

    **Two sorts rather than one reversed key**, as ``FakeAssistantEngine`` and
    ``SqliteAuditTrail`` already do it: the order is ``decided_at`` descending with
    ties broken by ``id`` *ascending*, and ``reverse=True`` over a compound key
    reverses **both** halves — which puts ``d-2`` above ``d-1`` at one instant, the
    opposite of what ADR-0021 §4 states. Python's sort is stable, so sorting by the
    tie-break first and the primary key second composes them correctly.

    Args:
        read: The trail read to await — ``recent`` or ``export``.

    Returns:
        Its rows, as the tuple ADR-0085 §3b requires, in §2's total order.
    """
    by_id = sorted(await read, key=lambda decision: decision.id)
    return tuple(sorted(by_id, key=lambda decision: decision.decided_at, reverse=True))


async def _ordered_invocations(
    read: Awaitable[list[RecordedInvocation]],
) -> tuple[RecordedInvocation, ...]:
    """Await one invocation read and put ADR-0192 §4's total order on what it returned.

    :func:`_ordered_decisions`' shape one row kind over, and the sort is owed here
    for that function's reason: §4 states the order as "guaranteed by the engine
    operation, over a list it has materialised", so an engine writing
    ``tuple(await trail.export_invocations())`` would be relaying a promise the
    *store* happens to make today rather than keeping one this contract states.

    **The key lives one level down.** ``recorded_at`` and ``id`` are the row's, on
    :attr:`RecordedInvocation.invocation`, and the joined value carries neither at
    its top level — the join adds the tool, the capability and the egress boolean
    and restates nothing (ADR-0192 §2). Sorting on anything the join added would
    order two rows of one attempt by a fact about the *decision*.

    **Two sorts rather than one reversed key**, exactly as :func:`_ordered_decisions`
    does it: the order is ``recorded_at`` descending with ties broken by ``id``
    *ascending*, and ``reverse=True`` over a compound key reverses **both** halves.
    Python's sort is stable, so sorting by the tie-break first and the primary key
    second composes them correctly.

    Args:
        read: The trail read to await — ``recent_invocations`` or
            ``export_invocations``.

    Returns:
        Its rows, as the tuple ADR-0085 §3b requires, in §4's total order.
    """
    by_id = sorted(await read, key=lambda row: row.invocation.id)
    return tuple(sorted(by_id, key=lambda row: row.invocation.recorded_at, reverse=True))


async def _newest_recorded_first(
    read: Awaitable[list[SourceReadRecord]],
) -> tuple[SourceReadRecord, ...]:
    """Await ``SourceReadTrail.export`` and put the listing's order on what it returned.

    **A reversal and never a sort**, which is the whole of how this differs from
    :func:`_ordered_decisions` — and the difference is the store contract's, not a
    preference. ``AuditTrail.export`` states *no* order, so that helper owes a sort;
    ``SourceReadTrail.export`` states one, "every record the store holds, **in
    recording order**", and ``SourceReadTrail.recent`` states its reverse,
    "newest-recorded first … never by ``checked_at``, and no implementation derives
    the order by comparing ``checked_at`` values" (ADR-0185 §6). So the export
    arrives oldest-first and this hands it back newest-first, which is what makes
    ADR-0186 §2's prefix property hold across the pair.

    **Sorting these rows is not merely unnecessary, it is unavailable.** A
    ``SourceReadRecord`` carries no sequence number; its ``id`` is caller-minted and
    unordered; and its ``checked_at`` is caller-supplied, so a sort keyed on it
    would answer differently after a backwards clock correction — the same hazard
    that made ADR-0185 §6 key the store's own prune on recording order rather than
    on that instant. Recording order is knowable here **only** because the store's
    contract states it.

    Applied to the **export** alone: ``recent`` already promises this order, so
    :meth:`Engine.recent_reads` relays it untouched. Reversing a page that is
    already newest-first would be exactly wrong, where re-sorting a conforming
    audit page is merely redundant — which is why there is no single helper for
    both reads here as there is for the decision pair.

    Args:
        read: The ``export`` call to await.

    Returns:
        Its rows, as the tuple ADR-0085 §3b requires, newest-recorded first.
    """
    return tuple(reversed(await read))


async def _written_preferences(
    store: NotificationStore, preferences: NotificationPreferences
) -> NotificationPreferences:
    """Write the standing settings and read back what the store now holds.

    Reading back rather than echoing the argument: what a client renders after a
    write must be what the store will rule against, and a store free to normalise
    what it was handed would otherwise have the two silently disagree.

    Args:
        store: Where the settings live.
        preferences: What to hold from now on.

    Returns:
        The settings in force.
    """
    await store.set_preferences(preferences)
    return await store.preferences()


def conversation_summary(conversation: Conversation) -> ConversationSummary:
    """Project one stored conversation into the summary a person reads (ADR-0074 §2)."""
    return ConversationSummary(
        id=conversation.id,
        started_at=conversation.started_at,
        last_active_at=conversation.last_active_at,
        last_turn_at=conversation.last_turn_at,
    )


@dataclass(slots=True, kw_only=True)
class _ActivationPass:
    """What every channel activation's working set holds, whatever its channel (#2598).

    ADR-0280 §3's working set, the part true of every activation: its deadline, its
    audience posture, what this deployment wired for the phases every activation
    takes, and those phases' decisions. ADR-0281's recall decision lives here and on
    no subclass, as the phases after it will. ``text`` is the activation's input, each
    subclass answering it from what it holds.

    Attributes:
        deadline: The pass's deadline on the running loop's clock.
        supply: The pass's audience posture — the object the understanding stage's
            windows and recall filter by (ADR-0276 §4, ADR-0281 §4).
        understanding_wired: The deployment wired the understanding stage.
        recall_wired: The deployment wired the recall stage.
        understood: How many inputs the latest understanding stage covered: those the
            activation held when it began (ADR-0332 §3:9); 0 before it first ran. An
            input a merge brought is covered by what brought it (ADR-0349 §7:9).
        recalled: Recall's decision and the records it kept; never persisted — the
            decision is carried on the activation's state for capture (ADR-0281 §6).
        windows: The windows stage's decision, the episode window held as ids
            (ADR-0282 §3); written by that stage alone.
        understanding_fetch: What the understanding phase fetched by id and what came
            back missing (ADR-0282 §2); written by that phase alone, never persisted.
        story_links_wired: The deployment wired the story-links stage (ADR-0300 §6).
        understanding: The understanding version the stage recorded on the activation's
            state, where it recorded one; written by the understanding stage alone.
        story_candidates: The candidate stories the understanding phase assembled
            (ADR-0300 §6:1-§6:4), with what it fetched for them and what came back
            missing; written by that phase alone, never persisted (§12:3).
        story_links: The story-links stage's decision (§6:10); written by that stage
            alone, never persisted (§12:3).
        phases: The phases' part of the working set, where the pass runs them on a
            test hub (ADR-0309 §2:6, §3:2): each round's planning, authorizing and
            acting decisions, the digests and the held results. ``None`` on every
            pass the phases do not plan, which no phase rule answers on.
        activation: The admitted activation's state, which holds the inputs a merge
            brought (ADR-0349 §7:7, §7:21) and the takeover decisions (§10:4); ``None``
            for a pass no channel admitted, which holds its trigger's input alone and
            decides no takeover.
    """

    deadline: float
    supply: TurnSupply
    #: Each version a pass no channel admitted named activations under: it decides no
    #: takeover, so the stage records it here, and the rule does not answer again.
    undecidable: set[int] = field(default_factory=set)
    understanding_wired: bool
    recall_wired: bool
    story_links_wired: bool = False
    understood: int = 0
    recalled: Recalled | None = None
    windows: Windows | None = None
    understanding_fetch: Fetched | None = None
    understanding: ActivationUnderstanding | None = None
    story_candidates: Candidates | None = None
    story_links: StoryLinksDecision | None = None
    phases: PhaseWorking | None = None
    activation: ActivationState | None = None

    def __post_init__(self) -> None:
        """Hand the phases the one way their waits move this pass's deadline (§7:28)."""
        if self.phases is not None:
            self.phases.move_deadline = self.move_deadline

    def move_deadline(self, seconds: float) -> None:
        """Move the pass's deadline later by ``seconds`` (ADR-0349 §7:28)."""
        self.deadline += max(seconds, 0.0)

    @property
    def text(self) -> str:
        """The activation's input, exactly as the pass holds it."""
        raise NotImplementedError

    @property
    def inputs_held(self) -> int:
        """How many inputs the activation holds: its trigger's, and each joined (§3:9)."""
        return 1 if self.activation is None else self.activation.inputs_held

    @property
    def understanding_decided(self) -> bool:
        """An understanding decision covers every input held (ADR-0332 §3:9).

        An input a merge brought is covered by the version that named its activation or
        by the meaning its offer carried (ADR-0349 §7:9).
        """
        merged = 0 if self.activation is None else self.activation.merge_covered
        return self.understood + merged >= self.inputs_held

    @property
    def understanding_version(self) -> int | None:
        """The latest recorded understanding's version, or ``None`` before the first."""
        return None if self.understanding is None else self.understanding.version

    @property
    def takeover_undecided(self) -> bool:
        """The latest understanding names an activation, undecided for it (ADR-0349 §10:8)."""
        understanding = self.understanding
        return (
            understanding is not None
            and bool(understanding.continues)
            and (self.activation is None or understanding.version not in self.activation.takeovers)
            and understanding.version not in self.undecidable
        )

    @property
    def windows_decided(self) -> bool:
        """The windows stage recorded the pass's windows (ADR-0282 §3)."""
        return self.windows is not None

    @property
    def recall_decided(self) -> bool:
        """Recall made its decision, a failed or timed-out one included."""
        return self.recalled is not None

    @property
    def understanding_recorded(self) -> bool:
        """The understanding outcome is a recorded version (ADR-0300 §6:11)."""
        return self.understanding is not None

    @property
    def story_links_decided(self) -> bool:
        """The story-links stage made its decision, a failed one included (§6:10)."""
        return self.story_links is not None

    @property
    def deadline_passed(self) -> bool:
        """The pass's deadline has passed, on the running loop's clock."""
        return self.deadline <= asyncio.get_running_loop().time()


@dataclass(slots=True)
class _TurnPass(_ActivationPass):
    """ADR-0280 §3's working set for one conversation turn, which the phases plan.

    What the pass was handed — the input the chat's reader took in, the conversation
    it names and the window it came in with — and, once the conversation stage has
    begun it, the resolved input. The rules read only these (§4), through
    :class:`~ai_assistant.orchestration.controller.PassFacts`; a decision only the
    retired path made is absent by construction (ADR-0309 §2:6).
    """

    utterance: str
    requested: str | None
    context: ChannelContext
    #: The chat's window, which the chat's reader brought this input in with
    #: (ADR-0293 §6:4).
    transcript: TranscriptWindow
    input: ResolvedChannelInput | None = None

    @property
    def text(self) -> str:
        """The utterance."""
        return self.utterance

    @property
    def conversation_turn(self) -> bool:
        """Always: this is a conversation turn's working set."""
        return True

    @property
    def informational_event(self) -> bool:
        """Never: this is a conversation turn's working set."""
        return False

    @property
    def conversation_resolved(self) -> bool:
        """The conversation has been begun and the input resolved against it."""
        return self.input is not None


@dataclass(slots=True)
class _EventPass(_ActivationPass):
    """ADR-0280 §3's working set for one informational event, which the phases plan.

    The event's resolved input beside what every activation holds. Its audience
    posture is bounded (ADR-0276 §4). Every conversation-turn decision is absent by
    construction.
    """

    input: ResolvedChannelInput

    @property
    def text(self) -> str:
        """The event's text."""
        return self.input.text

    @property
    def conversation_turn(self) -> bool:
        """Never: this is an event's working set."""
        return False

    @property
    def informational_event(self) -> bool:
        """Always: this is an event's working set."""
        return True

    @property
    def conversation_resolved(self) -> bool:
        """Never: an event resolves no conversation."""
        return False


@dataclass(slots=True)
class _TaskPass(_EventPass):
    """ADR-0280 §3's working set for an activation a scheduled task started (ADR-0350 §6).

    An event's shape, its channel window the schedule's place window, the task's lineage
    (§6:5), with the episodes its input links to: its task's parent's and those of the
    tasks its task waited on, which the episode window shows wherever they are frozen.
    """

    linked: tuple[str, ...] = ()

    @property
    def informational_event(self) -> bool:
        """Never: a scheduled task's activation is no event's."""
        return False


def _taken_channels(state: ActivationState) -> tuple[ChannelIdentity, ...]:
    """The places inputs ``state`` took by a take came from, in the order taken (§7:3)."""
    took = {one.activation_id for one in state.took}
    return tuple(dict.fromkeys(one.channel for one in state.joined if one.taken_over_from in took))


def _resolved_turn(working: _TurnPass) -> ResolvedChannelInput:
    """The turn's resolved input, which every stage after the first reads.

    Raises:
        RuntimeError: If no conversation was resolved, which the rules make impossible.
    """
    if working.input is None:  # pragma: no cover — `conversation_unresolved` runs first
        msg = "a turn's stages run after its conversation is resolved (ADR-0280 §4)"
        raise RuntimeError(msg)
    return working.input


def _turn_expired(working: _ActivationPass) -> Exception | None:
    """ADR-0280 §5: the understanding stage is not entered past the pass's deadline.

    A turn's, and an event's that the phases run, whose deadline is classified as a
    turn's (ADR-0313 §4:5).

    Checked before the stage reads the conversation's history, so an expired pass does
    no I/O for it. The error is the one the stage's own pre-check raised (ADR-0276 §6).
    """
    if working.deadline <= asyncio.get_running_loop().time():
        return ModelTimeoutError(_UNDERSTANDING_EXPIRED)
    return None


def _recall_expired(working: _ActivationPass) -> Exception | None:
    """ADR-0281 §5: the activation's deadline, a classified model timeout.

    Every pass the phases plan, an event's included, classifies its deadline as a
    turn's (ADR-0313 §4:5). ``None`` while there is time.
    """
    if not working.deadline_passed:
        return None
    return ModelTimeoutError(_RECALL_EXPIRED)


def _takeover_expired(working: _ActivationPass) -> Exception | None:
    """ADR-0280 §5: the takeover stage is not entered past the pass's deadline.

    A pass whose time is up takes nothing over: it would stop the other activation and
    then end itself (ADR-0332 §4:6). Classified as each pass kind classifies its expiry,
    as recall's is; ``None`` while there is time.
    """
    if not working.deadline_passed:
        return None
    return ModelTimeoutError(_TAKEOVER_EXPIRED)


def _windows_expired(working: _ActivationPass) -> Exception | None:
    """ADR-0282 §3: the windows stage is not entered past the pass's deadline.

    Classified as each pass kind classifies its deadline, as recall's is. ``None``
    while there is time.
    """
    if not working.deadline_passed:
        return None
    return ModelTimeoutError(_WINDOWS_EXPIRED)


def _wired_phases(  # noqa: PLR0913 — the path, the two wirings it needs beside it, the three seams it is handed, and the person model
    phases: PhasePath | None,
    *,
    understanding: bool,
    chat_reader: bool,
    append: Callable[[], Awaitable[None]],
    spawn: Callable[[Coroutine[None, None, None]], None],
    closing: Callable[[], bool],
    person_blocks: PersonBlocks | None = None,
) -> PhasePath | None:
    """The phases, wired beside understanding and the chat's reader.

    Planning's first round runs once understanding has recorded (ADR-0307 §8:6), and
    the phases plan every activation: the input the chat's reader takes in, and an
    event ``receive`` admits (ADR-0309 §2:6, ADR-0313 §4:3). Their recorders extend the
    episode through ``append``, and a tidy-up call nobody waits on starts through
    ``spawn`` unless ``closing`` says shutdown has begun (§7:2).

    Where a person-model store is wired, through the person block's assembly, the phases
    are attached to it, so planning is offered the person model's three calls
    (ADR-0338 §8:4); where none is, nothing is attached and none is offered (§11:2).

    An engine built without them runs no activation: no reader, and an event refused
    at admission. That is a suite holding the medium alone, or a surface no activation
    reaches.

    Raises:
        ConfigurationError: If the path is given without understanding or the reader,
            or the reader is on without the path, which every activation it starts
            runs through.
    """
    if phases is None:
        if chat_reader:
            msg = (
                "the chat's reader runs every activation through the phases, so it is "
                "wired only beside them (ADR-0309 §2:6)"
            )
            raise ConfigurationError(msg)
        return None
    if not understanding or not chat_reader:
        msg = (
            "the phases plan after understanding, for an input the chat's reader takes "
            "in, so they are wired only beside both (ADR-0309 §2:6, ADR-0307 §8:6)"
        )
        raise ConfigurationError(msg)
    phases.attach(append, spawn=spawn, closing=closing)
    if person_blocks is not None:
        phases.attach_person_model(person_blocks)
    return phases


def _check_story_wiring(  # noqa: PLR0913 — one flag per piece wired
    *,
    candidates: bool,
    links: bool,
    understanding: bool,
    matters_pass: bool,
    scheduled_tidy_up: bool,
    stories: bool,
) -> None:
    """ADR-0300 §6's two pieces are wired together or not at all, and only beside understanding.

    And §9:3's matters pass, and ADR-0358 §4's scheduled tidy-up, only beside the story
    store whose records they decide and tidy.

    Raises:
        ConfigurationError: If one is wired without the other — links proposed against
            no candidates, or candidates whose links nothing records — or either without
            the understanding stage whose links they are; or the matters pass or the
            scheduled tidy-up without the story store.
    """
    if matters_pass and not stories:
        msg = (
            "the matters pass decides flags on the story store's records, so it is wired "
            "only beside that store (ADR-0300 §9:3)"
        )
        raise ConfigurationError(msg)
    if scheduled_tidy_up and not stories:
        msg = (
            "the scheduled tidy-up tidies the story store's stories, so it is wired only "
            "beside that store (ADR-0358 §4)"
        )
        raise ConfigurationError(msg)
    if candidates != links:
        msg = (
            "the story candidates and the story-links stage are wired together or not "
            "at all (ADR-0300 §6)"
        )
        raise ConfigurationError(msg)
    if links and not understanding:
        msg = "the story-links stage records understanding's links, and needs it (ADR-0300 §6)"
        raise ConfigurationError(msg)


def _story_summary_bound(notes: int) -> int:
    """ADR-0303 §10:2's bound on the story summary view's notes, refused below one.

    Raises:
        ConfigurationError: If ``notes`` is below 1, a view that could list no note.
    """
    if notes < 1:
        msg = "the story summary view lists at least one note (ADR-0303 §10:2)"
        raise ConfigurationError(msg)
    return notes


def _story_links_expired(working: _ActivationPass) -> Exception | None:
    """ADR-0300 §6:13 under ADR-0281 §5: the story-links stage's deadline is the pass's.

    Classified as each pass kind classifies its deadline, as recall's is. ``None``
    while there is time.
    """
    if not working.deadline_passed:
        return None
    return ModelTimeoutError(_STORY_LINKS_EXPIRED)


#: What a recall decision makes of its stage's entry (ADR-0281 §5).
_RECALL_STAGE_OUTCOMES: Final = {
    RecallOutcome.FOUND: StageOutcome.DONE,
    RecallOutcome.NOTHING_FOUND: StageOutcome.DONE,
    RecallOutcome.FAILED: StageOutcome.FAILED,
    RecallOutcome.TIMED_OUT: StageOutcome.TIMED_OUT,
}


#: What :class:`ActivationStoppedError` says, from every site that raises it.
_STOPPED_MESSAGE: Final = "the activation was stopped before it finished (ADR-0297 §4)"


def _stopped_failure(
    state: ActivationState | None, failure: BaseException | None
) -> BaseException | None:
    """What a call awaiting ``state``'s pass is answered with, once it has ended.

    ADR-0297 §4: a call awaiting a stopped pass raises :class:`ActivationStoppedError`
    in place of what the pass would otherwise return or raise. A cancellation still
    propagates as itself, and a pass no stop reached is answered as it ended.

    **A defect the stop takes the place of is logged here** (#2927), by its class and
    frames (:func:`_log_if_defect`): past this point it survives only as the stop's
    cause, which the event path answers with *stopped* and the chat's path ends on
    silently, so nothing after it would tell a bug apart from the stop.
    """
    if (
        state is None
        or not state.stopped
        or isinstance(failure, asyncio.CancelledError | ActivationStoppedError)
    ):
        return failure
    if failure is not None:
        _log_if_defect("stopped_activation_failed", failure, state=state, step="activation")
    stopped = ActivationStoppedError(_STOPPED_MESSAGE)
    stopped.__cause__ = failure
    return stopped


def _answered[T](
    value: T | None,
    failure: BaseException | None,
    *,
    state: ActivationState | None,
    unfinished: Callable[[ActivationEnding], T] | None,
    check: Callable[[T], None],
) -> T:
    """What a call awaiting an activation is answered with, once it has frozen.

    Its value, or its failure raised; where ``unfinished`` is given, an event the phases
    run (ADR-0313 §4:5), a failure other than a cancellation is answered with the result
    ``unfinished`` builds, reading *stopped* where the stop mark is set and *couldn't
    finish* otherwise.

    **The result it builds is held to the output bound** (ADR-0085 §8c) by ``check``,
    the call's own measure with its capture receipt reserved: the freeze measures only
    a value the work returned, and this one is built after it. One too large raises
    ``OversizedValueError`` in its place, as every result the bound refuses does; and a
    failure that already is the output bound's refusal raises as itself, since the
    result built in its place would name the same channel.

    Raises:
        BaseException: ``failure``, where it is not answered with a result.
        OversizedValueError: If the result built in its place is too large to return.
    """
    if (
        unfinished is not None
        and isinstance(failure, Exception)
        and not isinstance(failure, OversizedValueError)
    ):
        # #2904: answered like any failure, a defect is still told apart in the log.
        _log_if_defect("event_activation_failed", failure, state=state, step="event")
        stopped = state is not None and state.stopped
        answer = unfinished(
            ActivationEnding.STOPPED if stopped else ActivationEnding.COULDNT_FINISH
        )
        check(answer)
        return answer
    if failure is not None:
        raise failure
    return cast("T", value)


def _log_if_defect(
    event: str, failure: BaseException, *, state: ActivationState | None, step: str
) -> bool:
    """Log ``failure`` as ``event`` at error level where it is a programming defect (#2904).

    An activation that cannot finish is answered the same whatever ended it (ADR-0313
    §4:5, ADR-0293 §9:1), so a ``ValueError`` from a bug would read as an expected
    ending. The rule is :func:`~ai_assistant.orchestration.defects.is_defect`'s,
    with the reader's having marked nothing counted as expected too. The line names
    the stage whose failure ended the pass, or ``step`` where none did.

    Returns:
        Whether ``failure`` was a defect, and so was logged.
    """
    if isinstance(failure, _NothingTakenInError) or not is_defect(failure):
        return False
    failed = failing_stage(state)
    log_defect(
        event,
        failure,
        stage=step if failed is None else failed.value,
        activation_id=None if state is None else state.activation_id,
    )
    return True


def _log_chat_failure(
    failure: Exception,
    *,
    state: ActivationState,
    marked: bool,
    reader: str = "chat",
) -> None:
    """Log how a reader's activation failed: a defect at error level (#2904).

    Under the line it always was, by whether the activation marked anything: a defect
    at error level, by its class and frames alone (:func:`_log_if_defect`), and an
    expected failure at the warning it always was. ``reader`` names the reader: the
    hub chat's, or the Telegram line's (ADR-0323 §2:2).
    """
    event = f"{reader}_activation_failed" if marked else f"{reader}_input_not_taken_in"
    step = f"{reader}_reader"
    if not _log_if_defect(event, failure, state=state, step=step):
        _log.warning(event, stage=step, exc_info=True)


_EMPTY_CHANNEL_CONTEXT = ChannelContext()


def _check_chat_waits(start_wait: timedelta, lapse: timedelta, cap: timedelta) -> None:
    """ADR-0332 §6:1-§6:3: both waits strictly positive, the cap no shorter than either.

    Raises:
        ConfigurationError: If they are not.
    """
    if start_wait <= timedelta(0) or lapse <= timedelta(0) or cap < max(start_wait, lapse):
        msg = (
            "chat_start_wait and chat_composing_lapse are strictly positive, and "
            "chat_composing_cap no shorter than either (ADR-0332 §6:1-§6:3)"
        )
        raise ConfigurationError(msg)


def _ruling_policy(
    policy: NotificationPolicy | None,
    policy_for: PolicyForZone | None,
    person_blocks: PersonBlocks | None,
) -> RulingPolicy | None:
    """The pick each reconsideration's policy comes from (ADR-0338 §3:6).

    The owner's zone where their profile sets one, read from the store the person block
    reads, and the hub's policy otherwise; ``None`` where no policy is wired.

    Args:
        policy: The policy over ``Settings.timezone``, or ``None``.
        policy_for: Builds the policy for a person's zone, or ``None``.
        person_blocks: The person block's assembly, whose store the zone is read from.

    Returns:
        The pick, or ``None`` where there is no policy to hand over.

    Raises:
        ConfigurationError: If a factory is wired with no policy beside it.
    """
    if policy is None:
        if policy_for is not None:
            msg = (
                "a policy for a person's zone is wired only beside the hub's policy: with "
                "no notification store and policy there is nothing to rule (ADR-0130 §3, "
                "ADR-0338 §3:6)"
            )
            raise ConfigurationError(msg)
        return None
    return RulingPolicy(
        default=policy,
        policy_for=policy_for,
        people=None if person_blocks is None else person_blocks.store,
    )


@dataclass(frozen=True, slots=True)
class _OccurrencePush:
    """What a push of one due occurrence states, read before its pushed mark (§7:5).

    Attributes:
        zone: The person's zone, which the occurrence's input is told in (ADR-0340 §6:1).
        due_at: The instant the occurrence pushed was due: the pending one's, or, for a
            rule that missed more than one, the latest missed (ADR-0340 §4:8).
        second_try: Whether it is pushed again as a second try (ADR-0350 §8:6).
        rule: For a rule's occurrence first pushed, what the plan store writes with the
            mark (ADR-0340 §9:3); ``None`` for every other push.
        skipped: How many occurrences the push records skipped (ADR-0340 §7:1).
    """

    zone: ZoneInfo
    due_at: datetime | None
    second_try: bool = False
    rule: RulePush | None = None
    skipped: int = 0


class Engine:
    """The concrete façade an interface adapter drives (ADR-0042 §1).

    Composes the engine's collaborators behind its surface and one shutdown path. It
    is handed them by the composition root, the one layer licensed to construct
    concretes (ADR-0042 §2).
    """

    def __init__(  # noqa: C901, PLR0913, PLR0915 — one parameter per injected collaborator plus its knobs, and one assignment or wiring check per parameter
        self,
        *,
        plans: PlanStore,
        trail: AuditTrail,
        spend: SpendLedger,
        reads: SourceReadTrail,
        memory: MemoryStore,
        traces: TraceRetention,
        trace_sink: TraceSink,
        trace_retention: timedelta | None,
        conversations: ConversationLifecycle,
        grant_operations: GrantOperations,
        connection_operations: ConnectionOperations,
        upcoming: UpcomingEventStage | None = None,
        notifications: NotificationStore | None = None,
        notification_policy: NotificationPolicy | None = None,
        notification_policy_for: PolicyForZone | None = None,
        notification_outbox: DeliveryOutbox | None = None,
        understanding: UnderstandingStage | None = None,
        understanding_version_limit: int | None = None,
        windows: WindowsStage | None = None,
        recall: RecallStage | None = None,
        stage_record_limit: int = DEFAULT_STAGE_RECORD_LIMIT,
        held_input_limit: int = DEFAULT_HELD_INPUT_LIMIT,
        in_progress_limit: int = DEFAULT_IN_PROGRESS_LIMIT,
        stories: StoryStore | None = None,
        story_summary_notes: int = DEFAULT_STORY_SUMMARY_VIEW_NOTES,
        story_candidates: StoryCandidates | None = None,
        story_links: StoryLinksStage | None = None,
        matters_pass: MattersPass | None = None,
        scheduled_tidy_up: ScheduledTidyUp | None = None,
        transcriber: SpeechTranscriber | None = None,
        synthesizer: SpeechSynthesizer | None = None,
        speakable_attested_sources: frozenset[str] = frozenset(),
        max_spoken_audio_bytes: int = DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
        max_notification_budget: timedelta = _DEFAULT_MAX_NOTIFICATION_BUDGET,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
        activation_id_factory: Callable[[], str] = _uuid,
        now: Clock = _utcnow,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        drain_timeout: timedelta | None = None,
        chat_reader: bool = True,
        chat_turn_budget: timedelta = CHAT_TURN_BUDGET,
        chat_start_wait: timedelta = DEFAULT_CHAT_START_WAIT,
        chat_composing_lapse: timedelta = DEFAULT_CHAT_COMPOSING_LAPSE,
        chat_composing_cap: timedelta = DEFAULT_CHAT_COMPOSING_CAP,
        phases: PhasePath | None = None,
        diagnostics: DiagnosticSink | None = None,
        diagnostic_retention: DiagnosticRetention | None = None,
        diagnostic_window: timedelta | None = None,
        telegram: TelegramLineSeams | None = None,
        observer: Observer | None = None,
        person_blocks: PersonBlocks | None = None,
        task_scheduler: TaskSchedulerSeams | None = None,
        approvals: ApprovalsSeams | None = None,
    ) -> None:
        """Wire the façade from injected collaborators.

        Args:
            plans: Durable planning state — the same instance the phases record
                into (a composition-root single-instance obligation, ADR-0042 §2).
                The façade records an activation's stop through it and reads it for
                a story's standing; a façade wired to a *second* store would record
                stops no reader of the first could see.
            trail: The audit trail — the same instance the phases' seams record
                into (a composition-root single-instance obligation of the same
                shape as ``plans``; ADR-0052 §1). The façade reads it **query-only**
                for the decision and invocation listings and exports, and records
                nothing; authoring rulings stays with the seams that rule
                (ADR-0042 §6). A façade wired to a *second* trail would answer from
                a store nothing writes to.
            spend: The spend ledger — the **same object** ``trail`` is, wired
                through its ``SpendLedger`` face (ADR-0194 §5). One holder satisfies
                that Protocol, ``SpendGate`` and ADR-0192's ledger seam, because all
                three read the same rows and two keyed by them could disagree about
                a total. It is the ledger face and **never** the gate: an adapter
                able to call the admission has acquired the ability to spend a
                budget, which is ADR-0029 §1's argument one seam over.
            reads: The source-read trail — the **same instance** the one driver left,
                the upcoming-event stage, records into (a composition-root
                single-instance obligation of the same shape as ``plans`` and ``trail``;
                ADR-0185 §4). The façade reads it **query-only**, for
                :meth:`recent_reads` and :meth:`export_reads`, and records nothing:
                authoring a row stays the driver's, on the seam that gated the read
                (ADR-0185 §5).

                **This is the wide seam's only holder**, which is the arrangement
                ADR-0185 §4 designed and §12 left this surface to complete.
                ``SourceReadTrail`` deliberately does not inherit
                ``SourceReadRecorder``, and the driver is annotated with the narrow
                one — so a driver cannot *name* ``recent`` or ``export``, and
                ADR-0093 §5's forbidden cursor stays out of a sensor's reach. That
                narrowing is what makes this parameter necessary rather than
                convenient: there is no collaborator the façade already holds that
                could answer these two.

                A façade wired to a *second* trail would answer a user's history
                from a store nothing writes to — which is worse than an error, since
                an empty trail is a truthful answer about a store that was never
                read from, and this one would be indistinguishable from it.
            memory: Long-term memory — the same instance the phases recall from and
                the writer behind them persists to (a composition-root
                single-instance obligation of the same shape as ``plans`` and
                ``trail``; ADR-0028 §4). The façade reads it for the inspection
                surface (:meth:`beliefs`, :meth:`belief`) and deletes through it
                (:meth:`forget`), because ADR-0042 §6 forbids an adapter reaching
                memory itself and ADR-0072 §7 forbids re-filtering ``export`` above
                the store. Wired to a *second* store, a listing would show beliefs
                the assistant does not use and ``forget`` would destroy nothing the
                user was shown.
            traces: The trace store's **deletion seam** — a
                :class:`~ai_assistant.core.protocols.TraceRetention` and never a
                ``TraceStore``, because ADR-0119 §7 gives the pipeline the purge and
                withholds the walk: "no component of the request pipeline… holds a
                seam carrying the walk, and none reads a trace back". The engine is
                the *only* holder of this capability, which is ADR-0083 §8's
                placement of the retention purge behind a maintenance operation
                reaching the seventh database (ADR-0119 §10) rather than a second
                sweeping mechanism.

                **Required with no default**, like ``conversations`` and its two
                siblings, and for the reason §7 gives the emitting seam: an
                optional collaborator defaults to unwired, and an unwired sweep is
                a horizon an operator can set and nothing applies — indistinguishable
                from a store with nothing to reclaim.
            trace_sink: The trace store's **append** seam, and a *second, separate*
                narrowing of the very object ``traces`` narrows (ADR-0119 §7): a
                :class:`~ai_assistant.core.protocols.TraceSink` the engine emits
                its own ``OPERATION`` trace through (§8), never a ``TraceStore``,
                so the engine can write telemetry and still cannot walk it. Two
                parameters rather than one because the capabilities are two —
                "``TraceStore`` structurally satisfies both narrow Protocols… and
                the composition root hands each collaborator exactly the seam it is
                entitled to" — and a single parameter typed to the union of them
                would be the wide seam §7 withholds, reintroduced by the back door.

                **Required with no default**, which §7 makes a clause: "every
                emitting site takes a ``TraceSink`` as a required constructor
                argument with no default. A composition that omits it does not
                type-check." An optional sink defaults to unwired, and an unwired
                emitter is indistinguishable from a system in which nothing
                happened.
            trace_retention: The trace horizon, the value
                :data:`~ai_assistant.core.config.Settings.trace_retention` carries
                (ADR-0119 §10). ``None`` means "keep forever": the sweep is
                **switched off** rather than called with a floor, exactly as
                ``ConversationLifecycle``'s ``retention`` switches its reclaim off.

                **Required with no default** for that field's own reason (ADR-0074
                §7): a seam with no default cannot inherit one, and the single place
                a retention default is decided is ``core.config.Settings``. A
                ``None`` default here would ship unbounded trace growth while
                looking like it followed the ADR.
            conversations: The capture/lifecycle stage (ADR-0074 §9) — the one
                layer that holds both durable stores, and therefore the owner of
                every sequence spanning them. It must be wired to the *same*
                ``MemoryStore`` passed above, another composition-root obligation
                of the same shape: a stage over a second store would write episodes
                no retrieval could see and destroy nothing the user was shown.
                Required rather than optional, deliberately — an engine that could
                be built without it is an engine that can silently record nothing,
                which is the one failure ADR-0074 §9 item 6 asks to be *reported*.
            grant_operations: The four grant operations (ADR-0102 §1, §7) — the
                **only** object in the system holding a
                :class:`~ai_assistant.core.protocols.SourceGrantStore` (ADR-0097
                §3, §9), which is why it is injected rather than assembled here.
                The façade delegates ``grantable_sources``, ``grant``, ``revoke``
                and ``recent_grants`` to it, keeping this class's own job the
                argument validation, the size measurement and the drain-tracking
                every other method on the surface gets.

                **Required, where ``upcoming`` below is optional, and the
                asymmetry is the Protocol.** These four are ``AssistantEngine``
                methods and the shared conformance suite runs against this class,
                so an engine that could be built without them is one whose surface
                is conditionally present — which is what ADR-0102 §7's "no
                production path may build an engine with the store unopened" is
                aimed at. Its sibling stage ``conversations`` is required for the
                same reason.

                **Spelled ``grant_operations`` and not ``grants``** because
                ``grants`` already means a
                :class:`~ai_assistant.core.protocols.SourceGrants` on every driver
                in this package, and ADR-0102 §2 records that reusing a word for a
                different type one constructor over is how two things come to be
                confused at a glance.
            connection_operations: The six connection operations (ADR-0151 §1,
                §10, ADR-0325 §5:1) — the **only** object in this package holding a
                :class:`~ai_assistant.core.protocols.ConnectionProvisioner`. The
                façade delegates ``connect_account``, ``reprovision_account``,
                ``connect_keyless_account``, ``disconnect_account``,
                ``connected_accounts`` and ``recent_connection_acts`` to it, keeping
                this class's own job the argument validation, the size measurement
                and the drain tracking.

                **Required, on ``grant_operations``' argument exactly** — these
                six are ``AssistantEngine`` methods and the shared conformance
                suite runs against this class, so an engine that could be built
                without them is one whose surface is conditionally present. It is
                also the shape #684 taught: ``build_engine`` once took a ``grants``
                parameter its one production caller never filled, and the answer
                was that an engine "either has a grant seam or does not build".

                **Holding it is not holding a keyring face** (ADR-0149 §8, ADR-0151
                §10). This class names five members that take and return `core`
                types; it cannot name ``set``, ``delete`` or ``get``, and no
                annotation on it mentions
                :class:`~ai_assistant.core.protocols.Secrets` or
                :class:`~ai_assistant.core.protocols.SecretStore` — so ADR-0125 §8's
                fourth clause stays true of `orchestration` word for word.
            upcoming: ADR-0132's upcoming-event producer, or ``None`` where this
                deployment configured no calendar source. **Its own reader
                instance, and not the facet's** (ADR-0132 §3): the two consumers
                read at their own cadence and neither derives its answer from the
                other's reading, and ADR-0093 §7's one-outstanding-worker
                reservation is per instance, so a shared reader would let one
                consumer's read suppress the other's.

                **It holds the notification seam this engine does not hand it.**
                The stage is given a ``NotificationWriter`` by the composition
                root — over the *same* store ``notifications`` names, or a ruled
                notification would be unreadable through the surfaces the user has
                (ADR-0028 §4) — because ADR-0130 §1 puts the seam with the producer
                and this façade is not one.

                **Optional, where the stages above are required, and the asymmetry
                is ADR-0093 §7 rather than laxity.** Every reader ships **disabled
                by default**, "and the reason is that nothing may read a user's
                personal files because a default said so" — so an engine with no
                reader is not a half-built engine, it is the default deployment.
                What is *not* optional is what :meth:`notice_upcoming_events` does
                about it: it refuses rather than reporting an empty success,
                because a job that reports health while doing nothing is the
                failure mode this corpus keeps naming (ADR-0022 §4a).
            notifications: The durable home of held notifications and the user's
                standing settings (ADR-0130 §9), or ``None`` where this deployment
                wires none — which every deployment does today, the ADR ratifying
                the contract surface ahead of a store to serve it. The five
                ``AssistantEngine`` methods behind it refuse with
                :class:`~ai_assistant.core.errors.ConfigurationError` in that
                state, on :meth:`notice_upcoming_events`'s shape: "no store is wired" and "no
                notifications are held" are different facts, and answering an
                empty page would report the second while the first is true.
            notification_outbox: ADR-0131 §3's durable delivery queue, or ``None``
                where a deployment composes none — the CLI's in-process engine
                serves no poll, so it needs no outbox, and ``next_notification``
                refuses legibly rather than answering "nothing is waiting". It is
                held as ``orchestration``'s own
                :class:`~ai_assistant.orchestration.delivery.DeliveryOutbox`
                rather than as ``core``'s ``NotificationOutbox``, because §3b
                gives the latter "exactly one method" and that one is the
                *producer's*; see that module for why the seam is local.
            understanding: ADR-0276's understanding stage, holding the model seam, or
                ``None`` on a deployment
                that wires none — where no pass enters a stage, and every capture that
                reaches the point it would have run records ``not_reached``. The
                composition root always wires it.
            understanding_version_limit: ``UNDERSTANDING_VERSION_LIMIT``, ADR-0276 §7's
                bound on the versions one processing record retains. Required, and at
                least 2, wherever ``understanding`` is wired.
            windows: ADR-0282's windows stage, holding the composition root's episode
                selector. Required wherever ``understanding`` is wired, since the
                windows are assembled before recall and understanding (§3).
            recall: ADR-0281's recall stage, holding the memory store, the threshold
                set for the wired embedder, the item limit and the budget, or
                ``None``. Recall runs only where ``understanding`` is wired too
                (§2), since understanding is what reads what it keeps.
            stage_record_limit: ``STAGE_RECORD_LIMIT``, ADR-0280 §6's bound on the
                entries one stage record retains; at least 2, so the first entry and
                the end entry are both kept.
            held_input_limit: ``Settings.held_input_limit`` (ADR-0349 §9:2): the most
                inputs one activation holds, its own with every one it absorbed or took;
                at least 1, and 1 turns absorbing and taking off. Defaults to the
                setting's own default.
            in_progress_limit: ``Settings.in_progress_limit`` (§9:3): the most entries
                understanding's in-progress section shows; at least 1. Defaults to the
                setting's own default.
            stories: ADR-0289 §1's story store, which the nine story methods read and
                write and nothing else here touches — or ``None`` where this deployment
                wired none, in which case each of those methods raises
                ``ConfigurationError`` rather than answering as though no story existed.
                The stages that read and write stories hold their own reference to the
                same store (ADR-0300 §6), so the engine surface's own use is unchanged.
            story_summary_notes: How many of a story's notes :meth:`story_summary` lists,
                newest first, before it counts the rest (ADR-0303 §10:2) — the
                composition root's ``STORY_SUMMARY_VIEW_NOTES``. At least 1.
            story_candidates: ADR-0300 §6's assembler of understanding's candidate
                stories, which the understanding phase runs before the stage renders —
                or ``None``, and then no stories section is rendered. Wired together
                with ``story_links`` or not at all, and only beside understanding.
            story_links: ADR-0300 §6's story-links stage, which records the latest
                recorded understanding's links in the story store — or ``None``, and
                then the ``story_links_unrecorded`` rule never answers.
            matters_pass: ADR-0300 §9:3's matters pass, which
                :meth:`decide_story_flags` runs — or ``None``, and then that operation
                refuses. Only beside ``stories``, the store it reads and writes.
            scheduled_tidy_up: ADR-0358 §4's scheduled tidy-up, over the one tidy-up
                planning's call runs, which :meth:`tidy_stories` runs — or ``None``,
                and then that operation refuses. Only beside ``stories``.
            transcriber: The speech-recognition seam (ADR-0200 §1, §2), already
                wrapped in whatever deadline decorator the composition root wired
                (ADR-0118 §2), or ``None`` on a deployment with no speech engines.
                Held for voice's own design (ADR-0313 §3:7): no member transcribes
                through it since ``converse_spoken`` retired (§3:1). Held here and
                nowhere else: no adapter in ``interfaces/`` calls either speech
                Protocol (ADR-0200 §2).
            synthesizer: The speech-synthesis seam, its sibling, which
                ``next_notification`` renders through (ADR-0206). Wired or unwired
                **together** with ``transcriber``: half a pipeline is a deployment
                nobody chose, so the constructor refuses it.
            speakable_attested_sources: The ``Attestation.reported_by`` identities
                ADR-0199 §3 places as **speakable** on a channel of unbounded
                audience — the calendar source ADR-0093 §7 configures, and nothing
                else. It is the composition root's to supply because that is the only
                layer that knows which reader was built and what identity it carries
                (ADR-0190 §7's minted discriminator included), and because
                ``orchestration`` may not import ``readers`` (golden rule 1). Empty
                by default, which withholds every attested record rather than
                guessing at a name — ADR-0199 §3's fail-closed direction.
            max_spoken_audio_bytes: ``Settings.hub_max_spoken_audio_bytes`` (ADR-0200
                §6), in bytes of **decoded** audio: the bound a notification's
                rendering is held to (ADR-0206 §6). It bounded a spoken turn's
                recording too until ``converse_spoken`` retired (ADR-0313 §3:1).
            max_notification_budget: ADR-0131 §5a's
                ``hub_max_notification_budget``, the ceiling a poll's ``budget``
                is refused above. Not nullable, for §5a's reason.
            notification_policy: The deterministic ruling of ADR-0130 §4 and §5,
                wired **together with** ``notifications`` or not at all. §3 puts
                the ruling inside the store's critical section, so this façade
                only ever hands it over — it never rules anything itself, and a
                policy without a store would have nothing to rule about. Its zone
                is ``Settings.timezone``, the hub's default.
            notification_policy_for: Builds the policy whose quiet windows are read
                in a person's zone (ADR-0338 §3:6), or ``None``. With it and
                ``person_blocks`` both wired, each reconsideration is handed the
                policy of the owner's zone where their profile sets one, read just
                before it rules (:class:`~ai_assistant.orchestration.notifications.RulingPolicy`);
                with either ``None``, every one is handed ``notification_policy``.
            closers: The resources the façade owns, as async close callables, in
                the order :meth:`aclose` must run them. The composition root hands
                these over so the façade is the defined owner that releases every
                connection on shutdown (ADR-0042 §2). Empty when the façade owns
                nothing (its collaborators are all in-memory).
            activation_id_factory: Supplies independent UUID4 activation identifiers.
            now: The clock :meth:`purge_expired` measures ``trace_retention`` back
                from, and the only reading this façade takes — every other instant
                on this surface is stamped by the stage that owns the write.
                Injectable so a sweep is deterministic
                (``CONTRIBUTING``, "Determinism"), and guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
                reading is this class's own failure rather than a horizon quietly
                displaced.
            max_payload_bytes: The contract limit ADR-0085 §8c declares, in bytes:
                ``hub_max_frame_bytes`` less the 512-byte envelope reserve, applied
                to the whole serialised payload of every call and every result. It
                is a **constructor argument rather than a read of ``Settings``**
                because ``hub_max_frame_bytes`` arrives with the hub (ADR-0084 §3)
                and ADR-0085 §12 records that the surface ADR adds no setting; the
                composition root passes ``settings.hub_max_frame_bytes - 512`` when
                it exists, and until then every engine gets the value derived from
                ADR-0084 §3's own 16 MiB default. A conformance test sets it small
                so the boundary is cheap to reach.

                **ADR-0084 §4 makes this the contract's and not the transport's**,
                enforced by every implementation and in both directions, so a client
                is never silently less capable than the engine it stands in for.
            drain_timeout: Phase A's budget in :meth:`_drain_and_close` — how long
                tracked in-flight work is given to finish **on its own** before the
                remainder is cancelled and awaited (ADR-0083 §4). The composition
                root passes ``Settings.shutdown_drain_seconds``.

                ``None``, the default, means **phase A is unbounded**: the drain
                waits and never cancels, which is exactly what this façade did
                before ADR-0083 and is what a test constructing an ``Engine``
                directly keeps getting. The default is *not* thirty seconds
                because that would silently change the shutdown of every caller
                that never asked for a budget; production gets the budget by going
                through the composition root, which is where deployment values
                belong.
            chat_reader: Whether the chat's reader takes in the messages written
                into conversations (ADR-0293 §6). ``True``, the default, is every
                deployment's: a written message starts an activation and its reply
                is written back. ``False`` leaves the medium without its reader, so a
                written message is recorded and waits — for a suite that holds the
                medium alone to the surface's contract.
            telegram: The Telegram line's bot, records, channel and bounds, where the
                line's two settings are set (ADR-0323 §3:2-§3:3); ``None``, the
                default, is a deployment with no line, where nothing of it starts. Its
                reader is the line's long-running task: :meth:`start` starts it, as
                the hub chat's reader takes in what waits, and :meth:`aclose` stops
                it before the drain (§2:2). It runs every activation through the
                phases, so it is refused without them.
            chat_turn_budget: The budget each activation the reader starts is given
                (:data:`~ai_assistant.orchestration.chat.CHAT_TURN_BUDGET`); the
                reader has no caller to hand it one (ADR-0029 §4).
            chat_start_wait: ``Settings.chat_start_wait`` (ADR-0332 §5:1, §6:1): how
                long the chat's reader waits after the latest message of a conversation
                where nothing is running before it takes them in. Strictly positive;
                defaults to the setting's own default.
            chat_composing_lapse: ``Settings.chat_composing_lapse`` (§5:6, §6:2): how
                long one composing signal stays live. Strictly positive.
            chat_composing_cap: ``Settings.chat_composing_cap`` (§5:2, §6:3): the longest
                a start wait lasts after the first waiting message; no shorter than
                either of the two above.
            phases: The phases, which the composition root always builds (ADR-0309
                §2:6). Every activation — each the chat's reader starts and each event
                ``receive`` admits — runs the controller's one table,
                :data:`~ai_assistant.orchestration.controller.ACTIVATION_RULES`, over
                its stages, and the phases write its messages. ``None`` runs no
                activation, so it is refused beside the reader and an event is refused
                at admission.
            diagnostics: The diagnostic record's write seam (ADR-0314 §4:4), which
                the controller of every pass writes its step entries through; ``None``
                where ``Settings.diagnostic_record`` is false. The engine itself writes
                nothing through it: it hands it on to each pass's controller, with the
                activation the pass runs.
            diagnostic_retention: The diagnostic record's deletion seam, swept in
                :meth:`_purge_expired` beside the trace store whatever
                ``diagnostic_record`` says (ADR-0314 §7:2-§7:3). Given together with
                ``diagnostic_window``; ``None`` for both, the default, sweeps no record,
                which is a directly built engine's and never the composition root's.
            diagnostic_window: ``Settings.diagnostic_retention``, the window the sweep
                measures back from the engine's clock (§7:1).
            observer: ADR-0329's observer, memory's one writer, or ``None``. Wired, a
                run starts each time an activation's episode is frozen, without the
                activation waiting on it, and :meth:`observe_episodes` runs it for the
                scheduler's row (§7:6); ``None`` starts nothing, and
                :meth:`observe_episodes` refuses.
            person_blocks: The person block's assembly over the person-model store
                (ADR-0338 §7:1), or ``None``, the default, where no store is wired: then
                no activation is given a block, and nothing of the person model reaches
                understanding or planning. Wired, an activation that is a person's is
                given one, assembled once before understanding (§2:2-§2:4), and the
                phases are attached to it, so planning is offered ``set_profile``, ``pin``
                and ``unpin`` (§8:4); with none, they are not offered.
            task_scheduler: The Task Scheduler's settings (ADR-0350 §12:5), or ``None``,
                the default, for an engine with no Task Scheduler. Wired, its sensor is
                the engine's long-running task, started with the hub and stopped with it
                (§7:1); and planning is offered spawn, cancel and the list pull (§4:1). A
                stop still stops only the activation it names (ADR-0352 §2:1). It is
                refused without the phases.
            approvals: The Approvals channel's seams (ADR-0361 §3), or ``None``, the
                default, for an engine with no Approvals channel. Wired, its sensor is the
                engine's long-running task, started with the hub and stopped with it
                (§3:4); planning is offered ``request_approval`` and ``run_approved``
                (§2, §5:2); and each request answered or expired starts an activation of
                its own, offered to the work that asked where it still runs (§6). It is
                refused without the phases.

        Raises:
            TypeError: If ``max_spoken_audio_bytes`` or ``max_payload_bytes`` is
                not an **exact** ``int`` (:func:`_check_positive_int`, which carries
                the reasoning). A ``bool`` is the named case (it is an ``int``
                subclass and a flag is not a count), and a ``float`` like ``1.5`` is
                refused rather than compared. On these two *bounds* the refusal is
                what keeps them able to bind at
                all: ``float("nan")`` compares ``False`` against every ``>``, so an
                engine built with one would admit a recording of any length and
                return a rendering of any length while reporting health, and one
                built with it as the contract limit would measure every argument and
                every result against a ceiling nothing can exceed.
            ValueError: If either is not positive, or only one of
                ``diagnostic_retention`` and ``diagnostic_window`` is given.
        """
        _check_diagnostic_sweep(diagnostic_retention, diagnostic_window)
        # ADR-0200 §6's ceiling, guarded as an exact positive integer. ``Settings``
        # refuses a non-integer or a non-positive value at load, but this is a
        # *constructor* argument and a composition root is not the only caller —
        # and the failure mode here is silent rather than loud: ``nan`` compares
        # ``False`` against every ``>``, so an engine built with one would admit a
        # recording of any length and return a rendering of any length while reporting
        # health. A bound that cannot bind is not a weaker bound but an absent one.
        _check_positive_int(max_spoken_audio_bytes, name="max_spoken_audio_bytes")
        # ADR-0085 §8c's contract limit, guarded on the same terms and for the same
        # reason, one surface wider. ``Settings`` refuses a bad ``hub_max_frame_bytes``
        # at load and the composition root derives this from it, but no shipped path is
        # the only path: this is a constructor argument on a class tests and future
        # roots build directly. A limit that cannot bind fails *open* silently, and it
        # fails open across the whole promoted surface — every argument check and every
        # result check on this façade measures against this one number, so ``nan`` here
        # is not a laxer contract limit but no contract limit at all (#1686).
        _check_positive_int(max_payload_bytes, name="max_payload_bytes")
        self._plans = plans
        # ADR-0329 §7:6, §16:6: the observer, and the one run a frozen episode starts in
        # the background — never a second while it runs, and once more after it where an
        # episode froze in the meantime.
        self._observer = observer
        self._person_blocks = person_blocks
        self._observing: asyncio.Task[None] | None = None
        self._observe_again = False
        self._trail = trail
        self._spend = spend
        self._reads = reads
        self._memory = memory
        self._traces = traces
        self._trace_retention = trace_retention
        self._diagnostics = diagnostics
        self._diagnostic_retention = diagnostic_retention
        self._diagnostic_window = diagnostic_window
        self._clock = checked_clock(now, owner="Engine")
        # The one emitter, built here rather than injected: ADR-0119 §8 puts the
        # envelope at `_tracked`, so its lifetime is this engine's and nothing
        # else may hold it. It is given the *guarded* clock above, so the trace's
        # instant and the purge's horizon are read through one seam (ADR-0026 §7).
        self._operation_traces = OperationTraces(sink=trace_sink, now=self._clock)
        self._conversations = conversations
        #: ADR-0298 §5's membership rows, read over the same chat space the gated
        #: operations act on; each passes the hub's own machine without a read.
        self._device_checks = DeviceChecks(conversations)
        #: Every activation this engine is running, from before its admission to the
        #: end of its finalization: what a conversation's current state reads its
        #: "working…" from (ADR-0293 §8:2), whether or not its episode survives.
        self._running: list[ActivationScope] = []
        #: Per conversation, how many activations started from it have ended and how
        #: many times episodes on its place were forgotten: with :attr:`_running`, the
        #: engine's account the change stream pushes a conversation's current state
        #: from (ADR-0296 §4:9).
        self._activation_turns: dict[str, int] = {}
        self._activation_coordinator = ActivationCoordinator(
            writer=conversations.activation_writer,
            register=self._register_capture,
            register_safety=self._register_capture_safety,
            now=self._clock,
            payload_limit=max_payload_bytes,
        )
        self._grants = grant_operations
        self._connections = connection_operations
        self._upcoming = upcoming
        if (notifications is None) != (notification_policy is None):
            msg = (
                "a notification store and a notification policy are wired together or "
                "not at all: §3 puts the ruling inside the store's critical section, so "
                "a store with no policy can rule nothing and a policy with no store has "
                "nothing to rule about (ADR-0130 §3)"
            )
            raise ConfigurationError(msg)
        self._notifications = notifications
        self._notification_policy = notification_policy
        self._notification_policies = _ruling_policy(
            notification_policy, notification_policy_for, person_blocks
        )
        self._notification_outbox = notification_outbox
        #: Whether this engine has already closed the open episodes a dead process
        #: left (ADR-0286 §7). Guarded because ``start`` is also the scheduler's
        #: recurring sweep, and a close on every call would freeze an episode this
        #: process holds open.
        self._open_episodes_closed = False
        #: Serialises the check-close-set above: a bare flag is not a guard across an
        #: ``await``, so two overlapping ``start`` calls would both read ``False``.
        self._open_episodes_lock = asyncio.Lock()
        #: Whether this engine has already voided the delivery leases it inherited
        #: (ADR-0131 §3). Held here rather than in the outbox because the engine is
        #: what the hub starts: instance lock → one hub process → one composition
        #: root → one engine → one recovery. An outbox guarding itself would be
        #: guarding per object, and a second object over the same database in the
        #: same live process would still void a lease a device is holding.
        self._leases_recovered = False
        #: Serialises the check-recover-set that reads the flag above, so two
        #: overlapping ``start`` calls cannot both pass it. Its own lock, because
        #: coupling two unrelated startup exclusions would make each one's reasoning
        #: the other's problem.
        self._lease_recovery_lock = asyncio.Lock()
        if max_notification_budget <= timedelta(0):
            msg = (
                f"max_notification_budget must be positive, got {max_notification_budget!r}: a "
                f"hub serving delivery with no budget bound has the failure the clause naming "
                f"it exists to prevent, so 'off' is not an available value (ADR-0131 §5a)"
            )
            raise ConfigurationError(msg)
        self._max_notification_budget = max_notification_budget
        if (transcriber is None) != (synthesizer is None):
            msg = (
                "a spoken turn needs both speech seams or neither: half a pipeline can "
                "transcribe an utterance and never say the answer, which is a deployment "
                "nobody chose. Wire a SpeechTranscriber and a SpeechSynthesizer together, "
                "or leave both unwired (ADR-0200 §1, §2)"
            )
            raise ConfigurationError(msg)
        # ADR-0276's understanding stage and §7's version bound, both from the
        # composition root. The bound is required wherever the stage is wired, and a
        # bound that cannot keep version 1 beside the latest is refused here rather
        # than at the first capture that would need it.
        if understanding is not None and (
            understanding_version_limit is None or understanding_version_limit < 2  # noqa: PLR2004 — version 1 and the latest
        ):
            msg = (
                "an understanding stage needs a version bound of at least 2, so that "
                "version 1 and the latest are both kept (ADR-0276 §7)"
            )
            raise ConfigurationError(msg)
        if understanding is not None and windows is None:
            msg = (
                "an understanding stage needs the windows stage, which assembles its "
                "windows before recall (ADR-0282 §3)"
            )
            raise ConfigurationError(msg)
        _check_story_wiring(
            candidates=story_candidates is not None,
            links=story_links is not None,
            understanding=understanding is not None,
            matters_pass=matters_pass is not None,
            scheduled_tidy_up=scheduled_tidy_up is not None,
            stories=stories is not None,
        )
        self._understanding = understanding
        self._understanding_version_limit = understanding_version_limit or 2
        self._windows = windows
        self._recall = recall
        self._story_candidates = story_candidates
        self._story_links = story_links
        self._story_summary_notes = _story_summary_bound(story_summary_notes)
        self._matters_pass = matters_pass
        self._scheduled_tidy_up = scheduled_tidy_up
        if stage_record_limit < 2:  # noqa: PLR2004 — the first entry and the end entry
            msg = "a stage record keeps its first entry and its end entry (ADR-0280 §6)"
            raise ConfigurationError(msg)
        self._stage_record_limit = stage_record_limit
        if held_input_limit < 1 or in_progress_limit < 1:
            msg = "held_input_limit and in_progress_limit are each at least 1 (ADR-0349 §9)"
            raise ConfigurationError(msg)
        # ADR-0349 §5-§7: what crosses the activations this engine runs, over its own
        # account of them; the stop call runs the Task Manager's stop through it (§4:7).
        self._matters = Matters(
            running=lambda: (one.state for one in self._running if one.state is not None),
            plans=plans,
            memory=memory,
            stop=self._stop,
            held_input_limit=held_input_limit,
            in_progress_limit=in_progress_limit,
            set_up=self._still_live,
        )
        self._admissions = 0
        self._stories = stories
        self._transcriber = transcriber
        self._synthesizer = synthesizer
        self._speakable_attested_sources = frozenset(speakable_attested_sources)
        self._max_spoken_audio_bytes = max_spoken_audio_bytes
        self._closers = tuple(closers)
        self._activation_id_factory = activation_id_factory
        self._max_payload_bytes = max_payload_bytes
        self._drain_timeout = drain_timeout
        self._inflight: set[asyncio.Task[Any]] = set()
        self._capture_safety: set[asyncio.Task[None]] = set()
        self._closing = False
        self._shutdown: asyncio.Task[None] | None = None
        self._drain_phase = DrainPhase.NOT_RUN
        # ADR-0293 §6, §10: the chat's spokes in the hub, over the chat space the acts
        # in the medium relay to.
        self._chat_turn_budget = chat_turn_budget
        _check_chat_waits(chat_start_wait, chat_composing_lapse, chat_composing_cap)
        self._chat_reader = (
            ChatReader(
                conversations=conversations.chat_space,
                activate=self._read_in,
                spawn=self._spawn_read,
                closing=lambda: self._closing,
                mint=self._chat_activation_id,
                # ADR-0303 §7:1: where the phases write messages, an assistant message
                # links to the activation that wrote it, by its effect record.
                written=None if phases is None else phases.written,
                # ADR-0332 §5: a message where nothing runs waits a moment first.
                # ADR-0350 §9:1: a message a task's activation wrote links to it too.
                writers=self._task_writers,
                # ADR-0349 §7:12: what the reader holds in a start wait, an older
                # activation's act waits for.
                hold=self._matters.hold,
                start_wait=chat_start_wait,
                composing_lapse=chat_composing_lapse,
                composing_cap=chat_composing_cap,
            )
            if chat_reader
            else None
        )
        # ADR-0309 §2:6: the phases, which plan every activation. Their stages follow
        # understanding, so they are wired only beside it, and the reader only beside them.
        self._phases = _wired_phases(
            phases,
            understanding=understanding is not None,
            chat_reader=chat_reader,
            append=self._episode_appended,
            # ADR-0307 §7:2: a tidy-up call nobody waits on is work this engine tracks,
            # as a chat read is, so its shutdown drains it; none starts once it closes.
            spawn=self._spawn_read,
            closing=lambda: self._closing,
            person_blocks=person_blocks,
        )
        if self._phases is not None:
            # ADR-0349 §4:6, §6:1, §7:20: planning's stop call, its findings look-up and
            # its answer to an offer, and the waits acting and planning hold (§7:12,
            # §7:25), over what crosses this engine's activations.
            self._phases.attach_matters(self._matters)
        # ADR-0323 §2:2: the Telegram line's spoke in the hub, its reader and its writer,
        # wired only beside the phases, which plan every activation it starts.
        self._telegram_writer: TelegramWriter | None = None
        self._telegram_reader: TelegramReader | None = None
        self._telegram_started = False
        if telegram is not None:
            if self._phases is None:
                msg = (
                    "the Telegram line runs every activation through the phases, so it "
                    "is wired only beside them (ADR-0309 §2:6, ADR-0323 §15)"
                )
                raise ConfigurationError(msg)
            self._telegram_writer = TelegramWriter(
                client=telegram.client,
                intake=telegram.intake,
                channel=telegram.channel,
                send_bound=telegram.send_bound,
            )
            self._telegram_reader = TelegramReader(
                seams=telegram,
                writer=self._telegram_writer,
                memory=memory,
                activate=self._line_read_in,
                # ADR-0332 §8, ADR-0349 §4:3: the line's `/stop` stops each activation
                # running from its chat, each by the one stop.
                stop=self._stop_line,
                closing=lambda: self._closing,
                mint=self._chat_activation_id,
                # ADR-0323 §4:13, §10: the window's messages, and a quoted one, link
                # to the activation that wrote them, by their effect records.
                written=self._phases.written_in,
                # ADR-0350 §9:1: and so do the messages a task's activation wrote here.
                elsewhere=self._schedule_episodes,
                # ADR-0349 §7:12: what the reader holds in a start wait, an older
                # activation's act waits for.
                hold=self._matters.hold,
            )
        # ADR-0350 §7, §10: the Task Scheduler's sensor and its Task Manager, wired only
        # beside the phases, which plan every activation a task starts.
        self._telegram_seams = telegram
        self._task_manager: TaskManager | None = None
        self._task_sensor: TaskSchedulerSensor | None = None
        self._place_lists: PlaceLists | None = None
        self._task_started = False
        self._task_zones = PersonZones(default=ZoneInfo("UTC"))
        self._lateness_grace = timedelta(0)
        #: ADR-0350 §9:10: each id an occurrence is being pushed to and not yet admitted,
        #: with whether a stop named it meanwhile, which refuses its admission.
        self._pushed: dict[str, bool] = {}
        #: Each activation the Task Scheduler started, from its admission until its
        #: occurrence's outcome is written (§7:6).
        self._admitted: set[str] = set()
        #: Each such activation's outcome, by its id, where the store failed to take it
        #: when the activation ended: written again at the sensor's next look (§7:6).
        self._unwritten: dict[str, OccurrenceState] = {}
        if task_scheduler is not None:
            self._wire_task_scheduler(task_scheduler, plans=plans, memory=memory)
        # ADR-0361 §3:4, §6: the Approvals channel's sensor, wired only beside the phases.
        self._approvals_sensor: ApprovalsSensor | None = None
        self._approvals_started = False
        #: ADR-0361 §5:6-§5:7: each approval's activation, by its id, with the request
        #: whose outcome it was pushed, until the work holding its input has ended.
        self._approval_inputs: dict[str, ApprovalRequest] = {}
        #: Each id an outcome is being pushed to and not yet admitted.
        self._approval_pushing: set[str] = set()
        if approvals is not None:
            self._wire_approvals(approvals, plans=plans, memory=memory)
        # ADR-0298 §7: the engine's half of the change stream, over the same chat
        # space and the same account of what runs as ``conversation`` reads.
        self._change_stream = ChangeStream(
            chat=conversations.chat_space,
            running=self._activity,
            state_of=lambda conversation_id, running: self._conversations.state(
                conversation_id, running=running
            ),
            closing=lambda: self._closing,
            tracked=self._stream_read,
            max_payload_bytes=max_payload_bytes,
        )

    @property
    def drain_phase(self) -> DrainPhase:
        """Which phase of ADR-0083 §4's drain this engine's shutdown ended in.

        :data:`DrainPhase.NOT_RUN` until :meth:`aclose` reaches the drain. Read by
        the hub once ``aclose`` has returned, so its completion event can say
        whether phase A was enough or the budget was spent and work cancelled
        (#559) — the distinction an operator cannot otherwise make, because both
        look identical from outside: a process that has not exited yet.

        Exposed as a **read** rather than as ``aclose``'s return value on purpose:
        ``aclose`` is memoised and every caller awaits the same shielded task
        (ADR-0042 §2), so a return value would have to be duplicated to every
        caller of an idempotent method whose contract is "everything is closed".
        """
        return self._drain_phase

    async def start(self) -> None:
        """Close what a dead process left open, then finish the sweeps (ADR-0286 §7, ADR-0076).

        **No plan step is recovered here.** ADR-0014 §4's startup scan resolved the
        steps the old path's runner left ``RUNNING``, and nothing writes one since
        that path was deleted (ADR-0309 §5). The phases claim their effects through
        the plan store's effect records and the invoker's ledger, and a claimed
        record given no outcome is never resolved by guessing (ADR-0306 §5:6), so
        no scan resolves one at startup.

        ADR-0074 §8 says the reclaim runs "by the deleting call, **at engine
        start**, and later by the hub's scheduler" — this is that middle case, and
        it is the reason ADR-0076 exists at all: until a stamped conversation could
        be *enumerated*, a process that died mid-deletion left episodes no later
        run could find and an index that outlived its grace indefinitely.

        Two sweeps, in the order that matters. The **deletion** sweep first,
        because it carries out something the user already asked for; then the
        **retention reclaim**, which asks for nothing and destroys nothing.

        **Then ADR-0131 §3b's reconciliation, and this is the position that clause
        requires**: it "reconciles at startup, running to completion before it
        serves any poll". The hub calls this at step 4 of its startup and begins
        accepting at step 6, so "before any poll" is a fact about the listener
        rather than a promise this method makes. It runs last of the three because
        it is the only one that reaches a second store, and because a hub whose
        conversation sweeps failed has a larger problem than an unreconciled
        outbox. Skipped where no outbox is wired, which is the CLI's in-process
        engine: it serves no poll, so there is nothing to reconcile before.

        **Ahead of the reconciliation, and only on the first call, the delivery
        leases this hub inherited are voided** (ADR-0131 §3). That is a separate
        step from the reconciliation because it is the one part of startup that is
        *not* repeatable — see :meth:`_recover_leases_once`.

        Idempotent, and safe to call more than once: both sweeps are re-runnable by
        construction, every drop is re-checked under the store's own
        per-conversation exclusion, the lease recovery is guarded to the first call,
        and the reconciliation is idempotent by ADR-0131 §3's key rule, every path
        keying on the candidate's own ``candidate_key``.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the conversation index cannot be read or
                written. A sweep that swallowed a store fault to keep running would
                report success over work it never did, so it aborts loudly — an id
                that is merely *gone* is a no-op and does not abort it.
            MemoryStoreError: If an episode a deletion must destroy could not be, or
                an episode a dead process left open could not be closed (ADR-0286 §7).
            NotificationOutboxError: If the outbox or the records it reconciles
                against cannot be read or written.
        """
        self._reject_if_closing()
        return await self._tracked(self._start(), "start")

    async def _start(self) -> None:
        """Close what a dead process left open, then sweep, then reconcile.

        **ADR-0286 §7's close runs first, on the first call only, and before the
        deletion sweep** (:meth:`_close_open_episodes_once`): an episode a dead process
        left open is frozen ``interrupted`` / ``hub_stopped`` before anything sweeps
        or reads its conversation.
        """
        await self._close_open_episodes_once()
        await self._conversations.sweep_deletions()
        await self._conversations.reclaim()
        # ADR-0293 §6:9: after a restart, the messages never taken in are taken in as
        # usual — once the dead process's open episodes are closed, so a message an
        # interrupted activation took in stays taken in. A restart writes nothing (§9:2).
        if self._chat_reader is not None:
            await self._chat_reader.notice_awaiting()
        # ADR-0323 §2:2, §5:10: the line's reader starts once the dead process's open
        # episodes are closed, so the activation a restart cut off reads *interrupted*
        # when the reader looks for it, once per engine.
        if self._telegram_reader is not None and not self._telegram_started:
            self._telegram_started = True
            self._spawn_read(self._telegram_reader.run())
        # ADR-0350 §7:1, §8:1: the Task Scheduler's sensor starts once the dead process's
        # open episodes are closed, and settles what a restart cut off before it pushes.
        if self._task_sensor is not None and not self._task_started:
            self._task_started = True
            self._spawn_read(self._task_sensor.run())
        # ADR-0361 §3:4, §3:7: the Approvals channel's sensor, after the same close, so an
        # approval's activation a restart cut off reads as admitted.
        if self._approvals_sensor is not None and not self._approvals_started:
            self._approvals_started = True
            self._spawn_read(self._approvals_sensor.run())
        if self._notification_outbox is not None:
            await self._recover_leases_once()
            await self._notification_outbox.reconcile()

    async def _close_open_episodes_once(self) -> None:
        """Close the episodes a dead process left open, once per engine (ADR-0286 §7).

        On the first call of :meth:`start`, guarded to that call, and before the
        deletion sweep (§7:2). Every open episode the store
        holds that no capture of this process holds is closed ``interrupted`` /
        ``hub_stopped``; an engine that admitted an activation before its first
        ``start`` passes over that activation's episode, and a later ``start`` closes
        nothing. **The flag is set only after the close returns**, so a store failure
        — which propagates from ``start`` as the sweeps' failures do (§7:4) — leaves
        the next call to finish it.
        """
        async with self._open_episodes_lock:
            if self._open_episodes_closed:
                return
            await self._conversations.activation_writer.close_open(
                stage_limit=self._stage_record_limit, payload_limit=self._max_payload_bytes
            )
            self._open_episodes_closed = True

    async def _recover_leases_once(self) -> None:
        """Void the delivery leases a previous hub process left behind (ADR-0131 §3).

        **Once per engine, and that is what makes it once per restart.** §3
        authorises voiding because "an entry still leased at startup is one whose
        holder is definitionally gone" — true of a lease the *previous* process
        granted, false of one this process granted a moment ago. `start` promises it
        is safe to call more than once, so an unguarded recovery on a second call
        would take a live lease from the device holding it and let a second device
        claim the same entry: one entry outstanding to two devices, which §3 forbids
        outright.

        **The guard lives here rather than in the outbox** because §3 says a restart
        voids every lease and says nothing about who detects a restart. An outbox
        that guarded itself would be guarding per *object*, and two outbox objects
        over one database in one live process would each recover. The engine is what
        the hub starts, so the ownership chain that ends here — instance lock → one
        hub process → one composition root → one engine — is the closest thing the
        ratified texts give this decision. It is not airtight: two engines built over
        one data directory in one process would each recover, which the composition
        root does not do and only a test can reach today (#969).

        **The check, the recovery and the flag are one critical section**, because a
        bare flag is not a guard across an ``await``. Two overlapping ``start`` calls
        both read ``False``; the first recovers and returns, a poll then leases an
        entry, and the second resumes its already-started recovery and voids that
        live lease — one entry claimable by a second device, which is the very thing
        this guard exists to prevent, reached through the guard itself. An earlier
        draft argued the window was unreachable because the hub starts the engine at
        step 4 and accepts at step 6, so no poll can interleave. That is a fact about
        ``service/hub.py``, not about this class: ``start`` is public, documents only
        that it is safe to call more than once, and says nothing that excludes
        overlap. Adversarial review found it on the tenth round. The lock costs
        nothing and makes the argument unnecessary rather than load-bearing.
        """
        if self._notification_outbox is None:
            return
        async with self._lease_recovery_lock:
            if self._leases_recovered:
                return
            await self._notification_outbox.recover_leases()
            self._leases_recovered = True

    async def purge_expired(self) -> PurgeReport:
        """Physically reclaim what the stores swept on a horizon owe.

        The **maintenance surface** ADR-0083 §8 says this façade grows: "new
        *concrete* surface on a class in ``orchestration``, not ``core`` contract
        surface". Its only caller is the hub's scheduler (ADR-0083 §7), which holds
        an ``Engine`` and nothing else — no concrete store, no subsystem import —
        so it is a client of the same façade the CLI is a client of, which is what
        makes ADR-0076 §5's "a scheduler is a second caller of the same read"
        literally true rather than approximately.

        **One operation over every swept store, deliberately**: never a sweeping
        mechanism per store, which is why ``tests/app/test_composition.py``'s sweep
        guard names *this* method's body as the one place a sweep may be called
        (ADR-0083 §11). ADR-0119 §10 applies that to the seventh database rather
        than re-deciding it: "the trace purge becomes the third call behind that
        same operation. The scheduler's job table does not change, no job acquires
        new store surface".

        **Correctness does not depend on the memory sweep running.** The memory
        store excludes what is past its deadline at *read* time — ADR-0007 §2 ("This
        holds regardless of whether ``purge_expired`` has run, so the privacy
        guarantee does not depend on a background job") — so a missed or late sweep
        is never a correctness bug.

        **The trace sweep is the exception, and it is a disk-space one.** ADR-0119
        §10 enforces that horizon "by deletion only… there is no read-time retention
        filter", because a Tier 2 horizon is "a disk-space policy over data that
        identifies nobody" rather than a privacy guarantee. So an unrun trace sweep
        leaves rows a walk still returns — and costs no privacy, because §2 keeps
        every trace free of the content it is about.

        **A horizon of ``None`` means the trace sweep does not run at all** (§10):
        "keep forever" is not a floor to pass, and :attr:`PurgeReport.traces` says
        ``None`` rather than ``0`` so that "off" is legible next to "found nothing".
        A horizon *longer than the calendar* is a different case with the same
        outcome: it saturates and deletes nothing rather than failing the whole
        operation every tick (:func:`_horizon`).

        Tracked like every other public method, so shutdown drains it before
        closing the connections it is writing through (ADR-0042 §2). The order is
        memory, then traces, and nothing depends on it: no sweep reads another's
        rows.

        Returns:
            How many rows each store reclaimed, and ``None`` for the traces where
            the horizon is "keep forever".

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8), which is what
                :data:`ENGINE_SHUTTING_DOWN` exists for.
            MemoryStoreError: If the memory store could not be swept. The later
                sweeps do **not** run in that case: nothing sequences them, so the
                next tick simply re-runs them all, and swallowing the first failure
                to reach the rest would report a sweep that half happened.
            TraceStoreError: If the trace store could not be swept, or the clock the
                horizon is measured back from returned a non-conforming reading
                (ADR-0026 §4, :meth:`_now`). The store failure *does* reach the
                caller, unlike an emission failure: ADR-0119 §5 subordinates the
                instrument to the work being observed, and a sweep is not the work
                being observed — "a purge that silently did nothing would let a
                store grow without bound behind a horizon an operator believes is
                enforced".
            DiagnosticRecordError: If the diagnostic record's files could not be
                listed or deleted (ADR-0314 §7:2), which reaches the caller for the
                trace sweep's reason: the window is the record's forgetting, and a
                sweep that silently did nothing would keep what it exists to delete.
        """
        self._reject_if_closing()
        return await self._tracked(self._purge_expired(), "purge_expired", _purged)

    async def _purge_expired(self) -> PurgeReport:
        """Sweep every store — **the only place any purge is called**.

        ADR-0083 §11 pins that claim mechanically rather than by convention: the
        composition-root guard scans the whole package for a call to ``purge``,
        ``purge_expired`` or ``purge_before`` by those bare attribute names,
        receiver-blind, and requires the set it finds to be *exactly* the calls in
        this method (plus the canonical fakes' own delegations, which implement a
        seam rather than schedule a sweep). A sweep added anywhere else — under a
        different name, over a different store, by a second timer — still fails it.
        ADR-0119 §10 extends that instruction to the trace store by name, so the
        third name joined the scan with the third call.

        The horizon is computed here and not held: ``trace_retention`` is a
        duration, and the instant it means is only ever *this* sweep's. It
        saturates rather than overflowing, because the arithmetic runs on
        configuration this system accepts (:func:`_horizon`).
        """
        records = await self._memory.purge_expired()
        traces = (
            None
            if self._trace_retention is None
            else await self._traces.purge_before(_horizon(self._now(), self._trace_retention))
        )
        held = None if self._notifications is None else await self._notifications.purge()
        # ADR-0314 §7:2-§7:3: the diagnostic record's window, swept here beside the
        # trace store and whatever `diagnostic_record` says now, so a file written
        # while it was on is still deleted after it is turned off.
        diagnostics = (
            None
            if self._diagnostic_retention is None or self._diagnostic_window is None
            else await self._diagnostic_retention.purge_before(
                _horizon(self._now(), self._diagnostic_window)
            )
        )
        return PurgeReport(
            records=records,
            traces=traces,
            notifications=held,
            diagnostics=diagnostics,
        )

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error of the sweep that read it.

        ADR-0026 §4: ``core`` raises a bare ``ValueError`` because it cannot know
        what its caller will do with the failure, and "each subsystem translates at
        its own boundary". `orchestration` has no error of its own, so a seam here
        borrows "the error of the stage that read the clock" — expiry raises
        ``MemoryStoreError``, and this reading exists only to place the trace
        horizon, so it raises
        ``TraceStoreError``. Untranslated, a mis-wired clock would reach the hub's
        scheduler as a raw ``ValueError`` from an operation whose failures are
        otherwise all ``AssistantError``.

        **Only ``ClockReadingError``**, never bare ``ValueError``: ADR-0026 §2
        keeps the clock's *invocation* outside the guard, so a provider that is
        simply down must reach the caller with its own type and cause intact. A
        boundary catching ``ValueError`` cannot tell the two apart and would report
        a bad reading for a broken clock.

        Raises:
            TraceStoreError: If the reading is naive, indeterminate, or outside the
                localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise TraceStoreError(str(exc)) from exc

    async def notice_upcoming_events(self) -> int:
        """Notice what is about to start, and offer a candidate for each (ADR-0132).

        The **maintenance surface**'s fourth scheduled operation, and ADR-0132 §1's
        own shape: "a stage in ``orchestration`` driven by a public operation on the
        concrete engine, which is in turn driven by a job on ADR-0083 §7's
        scheduler whose body is that bound method and which holds no store, no
        reader and no subsystem import". §8 already settled that a maintenance
        surface belongs "on a class in ``orchestration``, not ``core`` contract
        surface", so this is not a member of ``AssistantEngine``: no client asks for
        it and no interface adapter may drive it.

        **Takes no argument, deliberately**: the reader is given its own source and
        its own bound, so a caller able to widen the read is a caller able to defeat
        the bound. It is also what makes this a
        legal ``JobBody``.

        **The engine concludes nothing itself.** It delegates to
        :class:`~ai_assistant.orchestration.upcoming.UpcomingEventStage`, which
        gates the read on a live ``NOTIFY`` grant (ADR-0133 §5), walks the
        reading's per-occurrence proposals, and offers what falls inside the lead
        window through ADR-0130 §3's seam. The disposition is that seam's and the
        policy's; nothing here selects, ranks or influences one (ADR-0132 §8).

        **Independent of any other read of the calendar** (ADR-0132 §3). It has its
        own reader instance, its own interval and its own grant scope, so its read
        waits on and derives nothing from another's.

        Tracked like every other public method, so shutdown drains the offer it is
        in the middle of before closing the stores it is writing through
        (ADR-0042 §2).

        Returns:
            How many candidates were offered. **Zero is a successful pass** over a
            calendar with nothing starting soon, and no caller may read it as a
            failure (ADR-0093 §8). It is not a count of interruptions: what became
            of each candidate is ADR-0130 §5's ruling and is deliberately not
            reported here.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8).
            ConfigurationError: If this engine was built with no producer stage,
                which means exactly one thing: no configured source. Refusing is
                the point — an empty count would be indistinguishable from a quiet
                calendar, so a deployment whose stage failed to wire would look
                healthy forever while noticing nothing (ADR-0022 §4a).
            SourceNotGrantedError: If no live ``NOTIFY`` grant covers the source at
                the moment of the read, or if one is revoked while the read is in
                flight (ADR-0132 §2, ADR-0133 §5). Distinct from the error above:
                that one is a deployment that cannot ask, this one is a user who
                has not said yes. **No other grant substitutes** — ADR-0133 §2
                rules the uses independent, so a live ``INGEST`` grant on this
                calendar does not authorise this read.
            GrantError: If the grant store could not answer. Propagated rather than
                converted, so a store fault stays distinguishable from a refusal
                (ADR-0097 §5a).
            ReaderError: If the read could not complete because of its source.
                Nothing is offered from a failed read, the process is never taken
                down, and the scheduler retries at the next due instant
                (ADR-0132 §9).
            NotificationStoreError: If the notification store could not rule or
                record. A run that fails partway leaves what it offered offered and
                claims nothing about what it did not (ADR-0132 §5).
            NotificationOutboxError: If a ruled interruption could not be handed to
                the delivery seam (ADR-0131 §3b).
        """
        self._reject_if_closing()
        if self._upcoming is None:
            msg = (
                "no upcoming-event producer is wired, so there is nothing to notice; it "
                "needs a configured source (ASSISTANT_CALENDAR_READER_PATH, ADR-0132 §4). "
                "Configuration says where a source is; a grant says whether it may be "
                "read for this use, and neither stands in for the other"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._upcoming.notice(), "notice_upcoming_events", _noticed)

    async def tidy_stories(self) -> ScheduledTidyUpReport:
        """Tidy the stories that have changed enough or gone quiet, one bounded run (ADR-0358 §4).

        The **maintenance surface**'s scheduled tidy-up, on :meth:`decide_story_flags`'s
        shape: concrete surface on this class and not ``AssistantEngine``'s, which gains
        nothing (§4:8), taking no argument so it is a legal ``JobBody``, and driven by
        the scheduler's ``scheduled_tidy_up`` row at ``consolidation_interval``, the row
        just before the matters pass's (§4:1), so the flags its tidy-ups raise are
        decided in the same tick.

        **The engine tidies nothing itself.** It delegates to
        :class:`~ai_assistant.orchestration.story_tidy_up.ScheduledTidyUp`, which runs
        the one tidy-up planning's call runs (§4:5). A scheduled tidy-up is background
        maintenance of the assistant's own records, not an action under ADR-0292
        §12:1-§12:2 (§4:7): planning does not choose it, authorizing does not check it,
        and it runs directly on no channel, starting no activation, recording no
        episode and telling nobody.

        Tracked like every other public method, so shutdown drains the write it is in
        the middle of before closing the stores it writes through (ADR-0042 §2).

        Returns:
            What the run found and tidied. Every count zero is a **successful** run
            over a store with no story due.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8).
            ConfigurationError: If this engine was built with no scheduled tidy-up,
                for :meth:`decide_story_flags`'s reason: an empty report would be
                indistinguishable from a store with no story due (ADR-0022 §4a).
            StoryStoreError: If the story store could not be read while finding what
                is due. A tidy-up's own failure is its outcome, never raised.
        """
        self._reject_if_closing()
        if self._scheduled_tidy_up is None:
            msg = (
                "no scheduled tidy-up is wired, so there is no story to tidy; it needs the "
                "story tidy-up and the story store (ADR-0358 §4)"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._scheduled_tidy_up.run(), "tidy_stories", _stories_tidied)

    async def decide_story_flags(self) -> MattersPassReport:
        """Decide the flags on the stories, one bounded run (ADR-0300 §9:3, ADR-0302 §5).

        The **maintenance surface**'s scheduled run of the matters pass, on
        :meth:`notice_upcoming_events`'s shape: concrete surface on this class and not
        ``AssistantEngine``'s (ADR-0083 §8, ADR-0302 §4:6's *"AssistantEngine gains
        nothing"*), taking no argument so it is a legal ``JobBody``, and driven by the
        scheduler's ``matters_pass`` row at ``consolidation_interval``, the schedule of
        the background memory work §9:3 names, which outlived the consolidation stage
        (ADR-0328 §14:3).

        **The engine decides nothing itself.** It delegates to
        :class:`~ai_assistant.orchestration.matters_pass.MattersPass`, which writes
        each decision through the story store with the actor ``matters_pass``. Its
        changes are background maintenance, not actions under ADR-0292 §12:1-§12:2,
        in the scope ADR-0300's header gives.

        Tracked like every other public method, so shutdown drains the write it is in
        the middle of before closing the stores it writes through (ADR-0042 §2).

        Returns:
            What the run found and decided. Every count zero is a **successful** pass
            over a store with no undecided flag.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8).
            ConfigurationError: If this engine was built with no matters pass, for
                :meth:`notice_upcoming_events`'s reason: an empty report would be
                indistinguishable from a store with no flag on it (ADR-0022 §4a).
            StoryStoreError: If the story store could not be read or written. What
                the run wrote before it stands, each decision in its own transaction.
            MemoryStoreError: If the memory store could not be read.
            ModelError: Propagated unwrapped from the provider (ADR-0013 §5).
        """
        self._reject_if_closing()
        if self._matters_pass is None:
            msg = (
                "no matters pass is wired, so there is no flag to decide; it needs a "
                "model provider, the story store and the memory store (ADR-0300 §9:3)"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._matters_pass.run(), "decide_story_flags", _matters_decided)

    async def observe_episodes(self) -> RunOutcome:
        """Run the observer once over the episodes due (ADR-0329 §7:6, §16).

        The **maintenance surface**'s scheduled run of the observer, on
        :meth:`decide_story_flags`'s shape: concrete surface on this class and not
        ``AssistantEngine``'s (ADR-0083 §8), taking no argument so it is a legal
        ``JobBody``, and driven by the scheduler's ``observer`` row at
        ``observer_interval``, so that an episode waiting for a retry or the budget is
        not held for the next activation (§7:6). A run is also started, untraced and
        not awaited by anyone, each time an activation's episode is frozen.

        **One run at a time** (§16:6): asked for while a run — this row's or the one a
        frozen episode started — is going, it does not start and answers busy.

        Tracked like every other public method, so shutdown drains the write it is in
        the middle of before closing the stores it writes through (ADR-0042 §2).

        Returns:
            What the run did, in counts.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8).
            ConfigurationError: If this engine was built with no observer, for
                :meth:`notice_upcoming_events`'s reason: an empty run would be
                indistinguishable from a hub with no episode due (ADR-0022 §4a).
            MemoryStoreError: If the queue's episodes cannot be enumerated.
            PlanningError: If the queue's observation records cannot be read.
        """
        self._reject_if_closing()
        if self._observer is None:
            msg = (
                "no observer is wired, so there is no episode to observe; it needs its two "
                "model routes, the memory, plan and story stores and the write stage "
                "(ADR-0329 §15:1)"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._observer.run(), "observe_episodes", _observed)

    def _observe_soon(self) -> None:
        """Start a run once an activation's episode is frozen, nobody waiting on it (§7:6).

        In a context of its own, as a chat read is (:meth:`_spawn_read`), so the
        activation that froze is not the run's, and tracked like every other task here
        so :meth:`aclose` drains it (ADR-0042 §2). While a run started this way is going,
        a further freeze starts no second one (§16:6): it asks the running one to go
        round once more, so an episode its freeze pushed out of the window is not left
        for the scheduler's row.
        """
        if self._observer is None or self._closing:
            return
        if self._observing is not None and not self._observing.done():
            self._observe_again = True
            return
        self._observe_again = False
        task = asyncio.get_running_loop().create_task(
            self._observing_runs(self._observer), context=contextvars.Context()
        )
        self._observing = task
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _observing_runs(self, observer: Observer) -> None:
        """Run the observer, and again while a freeze asked for another during the run.

        A failure is the run's alone and is logged by its class (ADR-0004 §5): nobody
        waits on this task, the episodes it left wait for the next run (§16:4, §16:9),
        and an activation is never answered by it.
        """
        while True:
            self._observe_again = False
            try:
                await observer.run()
            except Exception as exc:
                _log.warning("observer_run_failed", stage="freeze", error_class=type(exc).__name__)
            if not self._observe_again or self._closing:
                return

    async def receive(
        self,
        input: ChannelInput,  # noqa: A002 — channel contract parameter
        *,
        reply: SpokenReply | None,
        timeout: timedelta,  # noqa: ASYNC109 — caller's operation budget
    ) -> ChannelResult:
        """Receive one channel input under its declared policy (ADR-0274 §4).

        Every conversational combination is refused before processing: a typed message
        is written into a conversation (ADR-0293 §11), and spoken conversation retired
        at the cutover (ADR-0313 §3:2). An event with text and no reply is the one
        combination ``receive`` admits (§4:1).

        **An event returns how its activation ended** (ADR-0313 §4:4). It runs through
        the phases as one activation whose place takes no message, its ``timeout`` the
        activation's budget, and one that cannot finish or is stopped returns its result
        rather than raising (§4:3, §4:5).
        """
        return await self._receive(
            input, reply=reply, timeout=timeout, projection=ChannelProjection("receive")
        )

    async def _receive(
        self,
        input: ChannelInput,  # noqa: A002 — channel contract parameter
        *,
        reply: WholeTextReply | SpokenReply | None,
        timeout: timedelta,  # noqa: ASYNC109 — operation budget
        projection: ChannelProjection,
    ) -> ChannelResult:
        self._reject_if_closing()
        accepted, capability = snapshot(input, reply)
        if projection.method == "receive":
            check_payload(
                {"input": accepted, "reply": capability, "timeout": timeout},
                max_bytes=self._max_payload_bytes,
                subject="the arguments to receive()",
            )
        event = isinstance(accepted.target, ChannelIdentity) and (
            accepted.target.channel_type == "informational_event"
        )
        if not event:
            # ADR-0313 §4:1: an event is the one combination `receive` admits, and
            # `snapshot` has already refused every other. A conversation's input is a
            # message written into it, which the chat's reader takes in (ADR-0293 §11).
            msg = (
                "unsupported channel input and reply combination: an event with text "
                "and no reply is the one receive admits (ADR-0313 §4:1)"
            )
            raise ValueError(msg)
        if self._phases is None:
            # ADR-0309 §2:6, ADR-0313 §4:3: an event runs through the phases, and the
            # event-summary stage runs no more.
            raise ConfigurationError("informational event processing is not wired")
        deadline = asyncio.get_running_loop().time() + timeout.total_seconds()
        state = admit_channel(
            accepted,
            capability,
            clock=self._now,
            id_factory=self._activation_id_factory,
            stage_limit=self._stage_record_limit,
        )
        projection = replace(projection, capture_report=state.reserved_report)
        target = accepted.target
        assert isinstance(target, ChannelIdentity)  # noqa: S101 — an event's target, checked above

        # ADR-0313 §4:5: an event the phases run that cannot finish, or is stopped, is a
        # result reading how it ended, never a raise.
        def unfinished(ended: ActivationEnding) -> ChannelResult:
            return ChannelResult(
                channel=target,
                capture=UNCAPTURED,
                result=InformationalEventResult(ended=ended),
            )

        task = self._activation_task(
            ActivationScope(state),
            # An event's budget is the deadline itself, read at admission (ADR-0274 §7,
            # ADR-0313 §4:5).
            lambda: self._dispatch_channel(
                accepted,
                capability,
                timeout=timeout,
                projection=projection,
                deadline=deadline,
            ),
            seam=projection.method,
            check_output=lambda result: check_payload(
                projection.terminal(result),
                max_bytes=self._max_payload_bytes,
                subject=f"the result of {projection.method}()",
            ),
            deadline=deadline,
            unfinished=unfinished,
        )
        result, report = await task
        assert report is not None  # noqa: S101 — channel admission always creates state
        return captured_result(result, report)

    async def _dispatch_channel(
        self,
        input: ChannelInput,  # noqa: A002 — channel contract parameter
        reply: ReplyCapability | None,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — operation budget
        projection: ChannelProjection,
        deadline: float,
    ) -> ChannelResult:
        """Run an admitted event through the phases (ADR-0313 §4:3).

        Admission refuses every other combination (ADR-0313 §3:1, ADR-0293 §11), so an
        event is all that reaches here; its budget is ``deadline``, read at admission.
        """
        del reply, timeout
        target = input.target
        assert isinstance(target, ChannelIdentity)  # noqa: S101 — admission refuses every other target
        assert target.channel_type == "informational_event"  # noqa: S101 — as above
        assert isinstance(input.payload, TextChannelPayload)  # noqa: S101 — narrowed by validated channel dispatch
        resolved = ResolvedChannelInput(
            target, input.payload.text, input.payload.modality, input.context
        )
        return await self._phases_event(resolved, deadline=deadline, projection=projection)

    async def _episode_admitted(self, state: ActivationState, deadline: float | None) -> None:
        """Write the open episode at admission, inside the call's deadline where it has one.

        An admission write the deadline cuts short is dropped rather than raised
        (:meth:`_activation_task`).
        """
        if deadline is None:
            await self._activation_coordinator.admit(state)
            return
        try:
            async with asyncio.timeout_at(deadline):
                await self._activation_coordinator.admit(state)
        except TimeoutError:
            return

    async def _episode_appended(self) -> None:
        """Extend this worker's open episode as a stage ends (ADR-0286 §3, §9).

        A pass no channel admitted — an internal call — has no episode to extend.

        **It runs inside the pass's own deadline** (§3:8): a turn's or an event's
        append is bounded by the deadline its stages run under, and one the deadline
        cuts short is dropped rather than raised, so it neither fails processing nor
        takes the stage's place in the record. The stage after it meets the deadline
        itself, and is classified as that pass kind classifies its expiry. What the
        cut-off append would have added the next write carries, the freeze at the
        latest: the writer's account already holds a write whose outcome it does not
        know, and a delete it started runs on through its drain.
        """
        state = active_state()
        if state is None:
            return
        working = state.working
        if not isinstance(working, _ActivationPass):
            await self._activation_coordinator.append(state)
            return
        try:
            async with asyncio.timeout_at(working.deadline):
                await self._activation_coordinator.append(state)
        except TimeoutError:
            return

    async def _stage_appended(self) -> None:
        """A stage ended: extend the open episode (ADR-0286 §3), and wake the waits.

        What another activation waits for may have changed with the stage (ADR-0349
        §7:12, §7:15, §7:25): its understanding, its takeover decision, or its end.
        """
        await self._episode_appended()
        self._matters.changed()

    async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
        """Stop one running activation: its mark, then its stop record (ADR-0297 §3, §5).

        **The mark is set first, in one synchronous step with the test of whether the
        activation has ended** (:meth:`ActivationState.stop`), and only then is the
        stop record written. Every end entry is appended in a synchronous step of its
        own on this one event loop, so either the mark lands first and the pass's end
        entry is the stop's, or the end entry landed first and the activation is
        answered ``ALREADY_ENDED`` with nothing written. The running activations are
        the ones this engine holds in process (§3:1, ADR-0255 §4:4): there is no
        cross-process signal, no queue and no lease.

        **No task is cancelled** (§4): the pass ends before its next stage, the store
        refuses every later claim made under it, and a stage already running runs to
        its own end under its own deadlines.

        Where the engine holds no running activation by that id, an episode at its
        address, ``activation:<activation_id>`` (ADR-0283 §2), says it ran and ended —
        a restart's close included (ADR-0286 §7) — and nothing standing there says
        nothing ran that the hub still knows of. Neither writes anything.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``activation_id`` is not an identifier.
            PlanningError: If the stop record cannot be written. The mark stays set
                (§3:7), and a repeated stop while the activation still runs writes the
                record again.
            MemoryStoreError: If the episode cannot be read.
        """
        self._reject_if_closing()
        named = identifier(activation_id, name="activation_id")
        check_arguments("stop_activation", max_bytes=self._max_payload_bytes, activation_id=named)
        return await self._tracked(self._stop(named), "stop_activation", checked=True)

    async def _stop(self, activation_id: str) -> ActivationStop:
        """The two writes of :meth:`stop_activation`, in their order (ADR-0297 §3).

        Everything up to the mark runs before the first ``await``: the running
        activation is found and its mark set in the one synchronous step that tests
        whether it has ended.

        ADR-0352 §2:1-§2:2: it stops exactly the activation it names and nothing below
        it. It cancels no scheduled task, stops no other activation and writes no
        cascade record: what the activation set up stays until a cancel or a stop names
        it, and the store refuses a spawn of the stopped activation's on its stop record
        (ADR-0350 §3:3).
        """
        running = self._running_state(activation_id)
        if running is not None:
            if not running.stop():
                return ActivationStop.ALREADY_ENDED
            # §3:4: only once the mark is set is the record written.
            await self._plans.record_stop(activation_id)
            return ActivationStop.STOPPED
        if self._task_manager is not None and await self._stop_pushed(activation_id):
            return ActivationStop.STOPPED
        episode = await self._memory.get(f"activation:{activation_id}")
        return (
            ActivationStop.NO_SUCH_ACTIVATION if episode is None else ActivationStop.ALREADY_ENDED
        )

    def _running_state(self, activation_id: str) -> ActivationState | None:
        """The running activation by that id, where this engine holds one."""
        return next(
            (
                one.state
                for one in self._running
                if one.state is not None and one.state.activation_id == activation_id
            ),
            None,
        )

    async def _stop_pushed(self, activation_id: str) -> bool:
        """Stop an activation the Task Scheduler pushed and has not admitted (ADR-0350 §9:10).

        Its stop record is written, so admission refuses it, and the sensor's admission
        reads the mark set here first, so nothing starts. Nothing below it is reached
        (ADR-0352 §2:1).

        An activation that was admitted is not one of these, though its occurrence may
        still read pushed while its outcome is written: it ran, so a stop naming it once
        it has ended changes nothing (ADR-0295 §1:6), and this writes nothing for it.

        Returns:
            Whether an occurrence was pushed to it, not yet admitted.
        """
        pending = activation_id in self._pushed
        if not pending and (
            activation_id in self._admitted
            or activation_id in self._unwritten
            or await self._memory.get(f"activation:{activation_id}") is not None
        ):
            return False
        if pending:
            self._pushed[activation_id] = True
        pushed = await self._plans.stop_pushed_activation(activation_id)
        return pending or pushed

    async def _still_live(
        self,
        activation_id: str,
        /,
        *,
        person: str,
        viewer: str | None,
        supply: TurnSupply | None,
    ) -> StillLive | None:
        """What ``activation_id`` set up that is still live (ADR-0352 §3:1-§3:6).

        The Task Manager's read, for the stop call's result; ``None`` where no Task
        Scheduler is wired, so nothing was set up.
        """
        manager = self._task_manager
        if manager is None:
            return None
        return await manager.still_live(activation_id, person=person, viewer=viewer, supply=supply)

    def _starting(self, activation_id: str) -> bool:
        """Whether an occurrence was pushed to ``activation_id``, to start it (ADR-0352 §3:4).

        Pushed and not yet admitted, and no stop has named it meanwhile, which refuses
        its admission (ADR-0350 §9:10).
        """
        return self._pushed.get(activation_id) is False

    async def episodes(
        self,
        *,
        channel: ChannelIdentity | None = None,
        status: ProcessingStatus | None = None,
        cursor: NonBlankEncodableText | None = None,
        limit: int = 50,
    ) -> EpisodePage:
        """Read live episode summaries in descending capture order (ADR-0275)."""
        self._reject_if_closing()
        selected_channel, selected_status, _ = check_list(channel, status, cursor, limit)
        check_arguments(
            "episodes",
            max_bytes=self._max_payload_bytes,
            channel=selected_channel,
            status=selected_status,
            cursor=cursor,
            limit=limit,
        )
        return await self._tracked(
            self._episode_page(
                channel=selected_channel, status=selected_status, cursor=cursor, limit=limit
            ),
            "episodes",
        )

    async def episode_chunk(
        self,
        episode_id: EncodableText,
        *,
        version: NonBlankEncodableText | None = None,
        offset: int = 0,
        max_bytes: int = 65536,
    ) -> EpisodeChunk | None:
        """Read canonical episode bytes, preserving the exact address (ADR-0275)."""
        self._reject_if_closing()
        check_detail(episode_id, version, offset, max_bytes)
        arguments = {"episode_id": episode_id, "offset": offset, "max_bytes": max_bytes}
        if version is not None:
            arguments["version"] = version
        check_payload(
            arguments,
            max_bytes=self._max_payload_bytes,
            subject="the arguments to episode_chunk()",
        )
        return await self._tracked(
            self._episode_detail(
                episode_id=episode_id, version=version, offset=offset, max_bytes=max_bytes
            ),
            "episode_chunk",
        )

    async def _episode_page(
        self,
        *,
        channel: ChannelIdentity | None,
        status: ProcessingStatus | None,
        cursor: str | None,
        limit: int,
    ) -> EpisodePage:
        page = await self._memory.episodes(
            channel=channel, status=status, cursor=cursor, limit=limit
        )
        return fit_page(page, channel=channel, status=status, max_bytes=self._max_payload_bytes)

    async def _episode_detail(
        self,
        *,
        episode_id: str,
        version: str | None,
        offset: int,
        max_bytes: int,
    ) -> EpisodeChunk | None:
        chunk = await self._memory.episode_chunk(
            episode_id, version=version, offset=offset, max_bytes=max_bytes
        )
        return fit_chunk(chunk, max_bytes=self._max_payload_bytes)

    # --- stories (ADR-0289 §4) ---------------------------------------------
    #
    # **Nine methods over the story store, and nothing else here reads it.** Every
    # write carries the actor ``owner`` and no triggering activation. A create or a
    # link naming an activation first reads each one's record through
    # ``MemoryStore.get_many`` and is refused ``unknown_activation`` where none is
    # there; a merge or a split checks no activation. The shared logic is
    # `orchestration/stories.py`, which the canonical fake engine calls too.

    def _story_store(self) -> StoryStore:
        """The wired story store, or the refusal a deployment with none earns.

        Raises:
            ConfigurationError: If this engine was built with no story store.
        """
        if self._stories is None:
            msg = "no story store is wired into this engine (ADR-0289 §1)"
            raise ConfigurationError(msg)
        return self._stories

    async def create_story(self, members: Sequence[StoryMember]) -> StoryOutcome:
        """Create a story holding ``members``, as the owner (ADR-0289 §§3-4)."""
        self._reject_if_closing()
        named = story_members(members)
        check_arguments("create_story", max_bytes=self._max_payload_bytes, members=named)
        stories = self._story_store()
        return await self._tracked(
            self._linked_story(stories, None, named), "create_story", checked=True
        )

    async def link_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Add ``members`` to a story, as the owner (ADR-0289 §§3-4)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        named = story_members(members)
        check_arguments(
            "link_story", max_bytes=self._max_payload_bytes, story_id=target, members=named
        )
        stories = self._story_store()
        return await self._tracked(
            self._linked_story(stories, target, named), "link_story", checked=True
        )

    async def _linked_story(
        self, stories: StoryStore, story_id: str | None, members: tuple[StoryMember, ...]
    ) -> StoryOutcome:
        """Check each activation member's record, then create or link (ADR-0289 §4)."""
        if members and (refusal := await unknown_activation(self._memory, members)):
            return StoryOutcome(refusal=refusal)
        if story_id is None:
            return await stories.create(members, actor=StoryActor.OWNER)
        return await stories.link(story_id, members, actor=StoryActor.OWNER)

    async def unlink_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Remove ``members`` from a story, as the owner (ADR-0289 §§3-4)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        named = story_members(members)
        check_arguments(
            "unlink_story", max_bytes=self._max_payload_bytes, story_id=target, members=named
        )
        stories = self._story_store()
        return await self._tracked(
            stories.unlink(target, named, actor=StoryActor.OWNER), "unlink_story", checked=True
        )

    async def merge_stories(self, story_id: Identifier, into: Identifier) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into``, as the owner (ADR-0289 §§3-4)."""
        self._reject_if_closing()
        absorbed = identifier(story_id, name="story_id")
        target = identifier(into, name="into")
        check_arguments(
            "merge_stories", max_bytes=self._max_payload_bytes, story_id=absorbed, into=target
        )
        stories = self._story_store()
        return await self._tracked(
            stories.merge(absorbed, target, actor=StoryActor.OWNER), "merge_stories", checked=True
        )

    async def split_story(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Split ``members`` off a story into a new one, as the owner (ADR-0289 §§3-4).

        The notes named go with them, as ADR-0303 §6 and §10:1 state.
        """
        self._reject_if_closing()
        source = identifier(story_id, name="story_id")
        named = story_members(members)
        going = story_note_ids(notes)
        check_arguments(
            "split_story",
            max_bytes=self._max_payload_bytes,
            story_id=source,
            members=named,
            notes=going,
        )
        stories = self._story_store()
        return await self._tracked(
            stories.split(source, named, actor=StoryActor.OWNER, notes=going),
            "split_story",
            checked=True,
        )

    async def story(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryView | None:
        """Read a page of a story's members, resolved (ADR-0289 §4)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        check_story_page(cursor, limit)
        check_arguments(
            "story", max_bytes=self._max_payload_bytes, story_id=target, cursor=cursor, limit=limit
        )
        stories = self._story_store()

        async def read(size: int) -> StoryView | None:
            return await resolved_view(stories, self._memory, target, cursor=cursor, limit=size)

        return await self._tracked(
            fitted(read, limit, max_bytes=self._max_payload_bytes, subject="the result of story()"),
            "story",
        )

    async def story_log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, oldest first (ADR-0289 §4)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        check_story_page(cursor, limit)
        check_arguments(
            "story_log",
            max_bytes=self._max_payload_bytes,
            story_id=target,
            cursor=cursor,
            limit=limit,
        )
        stories = self._story_store()

        async def read(size: int) -> StoryLogPage | None:
            return await stories.log(target, cursor=cursor, limit=size)

        return await self._tracked(
            fitted(
                read, limit, max_bytes=self._max_payload_bytes, subject="the result of story_log()"
            ),
            "story_log",
        )

    async def stories(
        self, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryPage:
        """Read a page of every story, newest first (ADR-0289 §4)."""
        self._reject_if_closing()
        check_story_page(cursor, limit)
        check_arguments("stories", max_bytes=self._max_payload_bytes, cursor=cursor, limit=limit)
        stories = self._story_store()

        async def read(size: int) -> StoryPage:
            return await stories.stories(cursor=cursor, limit=size)

        page = await self._tracked(
            fitted(
                read, limit, max_bytes=self._max_payload_bytes, subject="the result of stories()"
            ),
            "stories",
        )
        if page is None:  # pragma: no cover — the listing always answers a page
            msg = "the story listing answered no page"
            raise StoryStoreError(msg)
        return page

    async def activation_stories(self, activation_id: Identifier) -> tuple[StoryHeader, ...]:
        """Read the stories an activation belongs to directly, newest first (ADR-0289 §4)."""
        self._reject_if_closing()
        named = identifier(activation_id, name="activation_id")
        check_arguments(
            "activation_stories", max_bytes=self._max_payload_bytes, activation_id=named
        )
        stories = self._story_store()
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=named)
        return await self._tracked(stories.stories_of(member), "activation_stories", checked=True)

    # --- the story commands (ADR-0300 §8) -----------------------------------
    #
    # Four more over the same store, the reads for the owner as reader and the writes
    # as the owner. The shared logic is `orchestration/stories.py`'s summary read and
    # `orchestration/story_standing.py`'s standing, which the canonical fake engine
    # calls too.

    async def story_summary(self, story_id: Identifier) -> StorySummaryView | None:
        """Read a story's summary as the owner is shown it (ADR-0303 §10:2, ADR-0304 §4)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        check_arguments("story_summary", max_bytes=self._max_payload_bytes, story_id=target)
        stories = self._story_store()
        return await self._tracked(
            owner_summary(stories, target, notes=self._story_summary_notes),
            "story_summary",
            checked=True,
        )

    async def story_standing(self, story_id: Identifier) -> StoryStanding | None:
        """Read where a story's matter stands, worked out for the owner (ADR-0300 §8:1).

        What was done is read from the plan store's effect records (ADR-0306 §6).
        """
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        check_arguments("story_standing", max_bytes=self._max_payload_bytes, story_id=target)
        stories = self._story_store()
        return await self._tracked(
            standing_of(stories, self._memory, target, reader=OWNER_READER, plans=self._plans),
            "story_standing",
            checked=True,
        )

    async def add_story_note(self, story_id: Identifier, text: str) -> StoryNoteOutcome:
        """Add a note to a story, written by the owner (ADR-0300 §8:3)."""
        self._reject_if_closing()
        target = identifier(story_id, name="story_id")
        written = story_note_text(text)
        check_arguments(
            "add_story_note", max_bytes=self._max_payload_bytes, story_id=target, text=written
        )
        stories = self._story_store()
        return await self._tracked(
            stories.append_note(target, written, author=StoryNoteAuthor.OWNER),
            "add_story_note",
            checked=True,
        )

    async def move_story_members(
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember] = (),
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Move activation members, notes, or both, as the owner (ADR-0300 §3:14).

        The notes named go with them, as ADR-0303 §6 and §10:1 state, or on their
        own where no member is named (ADR-0304 §9).
        """
        self._reject_if_closing()
        source = identifier(story_id, name="story_id")
        target = identifier(to, name="to")
        named = story_move_members(source, target, members)
        going = story_note_ids(notes)
        check_arguments(
            "move_story_members",
            max_bytes=self._max_payload_bytes,
            story_id=source,
            to=target,
            members=named,
            notes=going,
        )
        stories = self._story_store()
        return await self._tracked(
            stories.move(source, target, named, actor=StoryActor.OWNER, notes=going),
            "move_story_members",
            checked=True,
        )

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """Enumerate the memories the assistant holds right now (ADR-0073 §1, ADR-0328 §11:2).

        The read half of "the user can read the assistant's beliefs about them".
        It relays the filters to
        :meth:`~ai_assistant.core.protocols.MemoryStore.list_beliefs`, which lists
        memories alone unless a caller names the episodic kind (ADR-0328 §11:2,
        ADR-0074 §6), and projects a memory through
        :func:`~ai_assistant.core.types.belief_summary` (ADR-0328 §15:1) and an episode
        through :func:`~ai_assistant.core.types.episode_summary`.

        Everything about *what* comes back is the store's ratified contract, not
        this façade's: live beliefs only (a retired record is history, reachable
        through ``export``, and by id through the store's history read, ADR-0342
        §4:3), newest revision first with ``id`` breaking ties,
        and a page that is full whenever enough matching records exist. Offset
        paging over a store that is being written to may skip or repeat a record,
        which ADR-0073 §2 names and accepts.

        **No total count is offered** (ADR-0073 §7): "is there more" is answered by
        asking for the next page, and a total would be a second query against a
        Tier 1 store for a UI nobody has designed.

        Both filters are **materialised before the awaiting task is created**, so a
        caller that mutates the sequence it passed cannot change which page it gets:
        the store's own input-observation clause (ADR-0065) binds what the store
        reads, and this keeps the relay through :meth:`_tracked` — which defers the
        first read of these arguments until the task runs — honest on its own terms.

        Args:
            bands: If given, restrict the listing to these belief bands. ``None``
                means every band; an **empty sequence selects nothing**.
            kinds: If given, restrict it to these kinds, same convention, except
                that ``None`` means memories alone. The two compose by conjunction.
            limit: How many beliefs the page holds at most. Bounded by default,
                because an unbounded read of a Tier 1 store by default is a shape
                worth not offering (ADR-0021 §4).
            offset: How many beliefs of the ordered, filtered sequence to skip.

        Returns:
            The page, in the store's specified order. Empty when nothing matches.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``limit`` or ``offset`` falls outside ``0 <= value <
                2**63``, as the store refuses rather than clamps (ADR-0073 §2). Not
                an :class:`~ai_assistant.core.errors.AssistantError`, so an adapter
                that lets a user supply either must refuse an out-of-range value at
                its own parse boundary rather than at this one.
            MemoryStoreError: If memory cannot be read.
        """
        self._reject_if_closing()
        # Materialised here, before the first await, so a caller that mutates the
        # sequence it passed cannot change which page it gets (ADR-0085 §3d).
        snapshot_bands = None if bands is None else tuple(bands)
        snapshot_kinds = None if kinds is None else tuple(kinds)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "beliefs",
            max_bytes=self._max_payload_bytes,
            bands=snapshot_bands,
            kinds=snapshot_kinds,
            limit=limit,
            offset=offset,
        )

        return await self._tracked(
            self._beliefs(bands=snapshot_bands, kinds=snapshot_kinds, limit=limit, offset=offset),
            "beliefs",
            checked=True,
        )

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read the one memory ``record_id`` names, or ``None`` (ADR-0073 §5, ADR-0328 §15:2).

        The single-belief read the deletion ceremony needs: a person cannot consent
        to destroying something they were not shown, so :meth:`forget` is preceded by
        this (ADR-0042 §4, ADR-0052 §4, applied to the other irreversible thing this
        system does on a user's word).

        Backed by :meth:`~ai_assistant.core.protocols.MemoryStore.get` and therefore
        **live-only**, like everything else on this surface. So an id naming a
        *retired* record does not resolve here and ``None`` comes back — the surface
        declines what it cannot display rather than destroying it (ADR-0073 §5).
        ``MemoryStore.delete`` still reaches any record by id and is unchanged, so no
        data right is lost; what is missing is a surface for retiring history, which
        belongs with the deferred history view (ADR-0073 §3, §10).

        Args:
            record_id: The id the user named, taken as opaque.

        An id naming an episode reads as its view
        (:func:`~ai_assistant.core.types.episode_view`), so the ceremony shows an
        episode before :meth:`forget` destroys it, exactly as it shows a memory
        (ADR-0074 §6).

        Returns:
            The memory's single view, or ``None`` when no live memory has that id.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If memory cannot be read.
        """
        self._reject_if_closing()
        named = identifier(record_id, name="record_id")
        check_arguments("belief", max_bytes=self._max_payload_bytes, record_id=named)
        return await self._tracked(self._belief(named), "belief", checked=True)

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy the record ``record_id`` names (ADR-0073 §5; ADR-0007 §1).

        "Kill any of them", relayed to
        :meth:`~ai_assistant.core.protocols.MemoryStore.delete`, with the record read
        first only to learn whether it is an episode whose conversation's current state
        an open change stream must send again (ADR-0296 §4:9) — a read whose failure
        never prevents the deletion.
        The **contract does not change and the store grows no band-conditional
        refusal**: ADR-0004 §6 gives the user an unconditional right to delete their
        data, and a store that refused because of the band it had itself assigned
        would make that right conditional on its own classification. The asymmetry
        between the bands is real (destroying an assertion is unrecoverable;
        destroying a derived or attested belief loses the belief and not its origin)
        and it belongs in **what the user is told before they answer**, which is the
        adapter's ceremony, not in what the store will do.

        This destroys rather than retires. A *correction* keeps the prior record —
        it is retired, stays on disk and stays in ``export`` — and runs through the
        policy (``learn``, ADR-0022); this leaves nothing anywhere. That contrast,
        **kept versus destroyed**, is what a surface offering both must convey, and
        it is why inspection adds no second correction path and no edit-in-place
        (ADR-0073 §6).

        **The show and the delete are two calls.** A write landing between them is
        destroyed without having been shown, and this is named rather than closed
        (ADR-0073 §5): a conditional delete would be the compare-and-swap ADR-0046
        §5 deferred for want of a second concurrent writer, and a confirmation prompt
        is not that writer. What the window admits is bounded in practice — an id is
        an idempotency key, and of the two rulings that write over a conflict
        ``SUPERSEDE`` mints a fresh id while ``REINFORCE`` folds the same belief — so
        the reachable case is that the user is shown belief X and destroys a
        strengthened X. The consent an adapter collects is therefore consent to
        forget **the belief that id names**, not a guarantee that the bytes destroyed
        are the bytes rendered, and an adapter must not claim otherwise.

        **A capture in flight at the id is told first, in the same call** (ADR-0286
        §8:1, as ADR-0287 §4 keeps it): its next write writes nothing and deletes the
        episode, so a record this call destroys is not written back after it.

        Args:
            record_id: The id the user named, taken as opaque.

        Returns:
            ``True`` if a record was destroyed, ``False`` if no record had that id —
            which the adapter renders and maps to an exit code (ADR-0073 §7).

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If memory cannot be written.
        """
        self._reject_if_closing()
        named = identifier(record_id, name="record_id")
        check_arguments("forget", max_bytes=self._max_payload_bytes, record_id=named)
        return await self._tracked(self._forgotten(named), "forget", checked=True)

    async def _forgotten(self, record_id: str) -> bool:
        """Mark any capture in flight at the id, then destroy the record (ADR-0286 §8:1).

        ADR-0287 §4: the mark and the deletion are the whole of a forget. The mark
        makes that capture's next write delete the episode rather than write it back
        (§8:2), and it reads no store.
        """
        self._conversations.activation_writer.forgetting(record_id)
        # ADR-0296 §4:9: an episode is read into its conversation's current state, so
        # the conversation it names is counted once it is destroyed, and an open change
        # stream sends that state again. Only a live episode is read into the state, and
        # only a live record is returned here, so nothing else needs counting. The read
        # never stands between the user and the deletion (ADR-0073 §5): a record that
        # cannot be read is still destroyed, and the stream's sweep sends its
        # conversation's state instead.
        try:
            conversation = episode_conversation(await self._memory.get(record_id))
        except MemoryStoreError:
            conversation = None
        try:
            return await self._memory.delete(record_id)
        finally:
            if conversation is not None:
                self._count_change(conversation)

    async def pending_candidates(self) -> tuple[PendingCandidate, ...]:
        """The candidates the observer has not yet processed (ADR-0329 §18:2).

        Lane 3's reading, not a second one, walked over every episode:
        :func:`~ai_assistant.orchestration.candidates.held_candidates` joins each
        unsettled episode's recorded ``remember`` calls to the effect records that show
        them done (§3:3), adds the candidates recorded under an approval, which the
        panel has no question to show in, and leaves out an episode the observer has
        settled (§16:2).

        Returns:
            The pending candidates, the most recent episode's first.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If the episodes cannot be read.
            PlanningError: If the plan store cannot be read.
        """
        self._reject_if_closing()
        return await self._tracked(self._pending_candidates(), "pending_candidates", checked=True)

    async def _pending_candidates(self) -> tuple[PendingCandidate, ...]:
        return await held_candidates(self._memory, self._plans)

    # --- the person model, for the panels (ADR-0338 §8:1-§8:3) -------------
    #
    # Each of the eight validates its arguments locally, then refuses on a hub that keeps no
    # person model (``person_blocks`` not wired: ``Settings.person_model`` off, §11:2),
    # then runs :mod:`~ai_assistant.orchestration.person_panel` over the person block's
    # assembly, tracked and measured as every member is. The canonical fake answers them
    # from the same module, so the two cannot read the slot two ways.

    async def person_model(
        self,
        person_id: NonBlankEncodableText,
        *,
        lists: Sequence[PersonModelList] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> PersonModelView | None:
        """Read one person's model, as the About you panel shows it (ADR-0338 §8:1).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``person_id`` is blank or unwritable, or a page argument is
                out of range.
            TypeError: If a page argument is not an integer.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the person-model store cannot be read.
            MemoryStoreError: If the memory store cannot be read.
        """
        self._reject_if_closing()
        named = non_blank_text(person_id, name="person_id")
        selected = person_model_lists(lists)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "person_model",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            lists=selected,
            limit=limit,
            offset=offset,
        )
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.person_model_view(
                blocks,
                named,
                limit=limit,
                offset=offset,
                lists=None if selected is None else frozenset(selected),
            ),
            "person_model",
            checked=True,
        )

    async def profile_changes(
        self,
        person_id: NonBlankEncodableText,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[ProfileChange, ...]:
        """One page of a person's change log, the most recent first (ADR-0338 §3:5).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``person_id`` is blank or unwritable, or a page argument is
                out of range.
            TypeError: If a page argument is not an integer.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the person-model store cannot be read.
        """
        self._reject_if_closing()
        named = non_blank_text(person_id, name="person_id")
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "profile_changes",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            limit=limit,
            offset=offset,
        )
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.profile_changes(blocks, named, limit=limit, offset=offset),
            "profile_changes",
            checked=True,
        )

    async def set_profile_field(
        self,
        person_id: NonBlankEncodableText,
        *,
        field: ProfileField,
        value: EncodableText | None = None,
    ) -> PersonModelEdit:
        """Set or clear one of a person's fields, on the panel (ADR-0338 §3, §8:2).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an argument is malformed.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the store cannot be read or written.
        """
        self._reject_if_closing()
        named = non_blank_text(person_id, name="person_id")
        which = profile_field(field)
        held = profile_value(value)
        check_arguments(
            "set_profile_field",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            field=which,
            value=held,
        )
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.set_profile_field(blocks, named, which, held),
            "set_profile_field",
            checked=True,
        )

    async def pin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Pin a memory, on the beliefs panel, through the one checked pin (ADR-0338 §4:2).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
        """
        named, memory = self._person_ids("pin_memory", person_id, memory_id=memory_id)
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.pin_memory(blocks, named, memory), "pin_memory", checked=True
        )

    async def unpin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Unpin a memory, erasing nothing, through the one unpin (ADR-0338 §4:7).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
        """
        named, memory = self._person_ids("unpin_memory", person_id, memory_id=memory_id)
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.unpin_memory(blocks, named, memory), "unpin_memory", checked=True
        )

    async def remove_style_mark(
        self, person_id: NonBlankEncodableText, *, mark_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Remove a style mark, on the panel (ADR-0338 §5:3).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the store cannot be read or written.
        """
        named, mark = self._person_ids("remove_style_mark", person_id, mark_id=mark_id)
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.remove_style_mark(blocks, named, mark), "remove_style_mark", checked=True
        )

    async def accept_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Accept a pending suggestion, on the panel (ADR-0338 §8:8, §9:2, §9:5).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the person-model store cannot be read or written.
            MemoryStoreError: If the memory store cannot be read.
        """
        named, suggestion = self._person_ids(
            "accept_person_suggestion", person_id, suggestion_id=suggestion_id
        )
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.accept_suggestion(blocks, named, suggestion),
            "accept_person_suggestion",
            checked=True,
        )

    async def dismiss_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Dismiss a pending suggestion, on the panel (ADR-0338 §9:2, §12).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            PersonModelOffError: If no person-model store is wired.
            PersonModelStoreError: If the store cannot be read or written.
        """
        named, suggestion = self._person_ids(
            "dismiss_person_suggestion", person_id, suggestion_id=suggestion_id
        )
        blocks = person_panel.wired(self._person_blocks)
        return await self._tracked(
            person_panel.dismiss_suggestion(blocks, named, suggestion),
            "dismiss_person_suggestion",
            checked=True,
        )

    def _person_ids(self, method: str, person_id: str, **record: str) -> tuple[str, str]:
        """A person-model write's two ids, validated verbatim and measured (ADR-0338 §10:4).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an id is blank or unwritable.
            OversizedValueError: If the arguments exceed the limit.
        """
        self._reject_if_closing()
        named = non_blank_text(person_id, name="person_id")
        ((name, value),) = record.items()
        other = non_blank_text(value, name=name)
        check_arguments(method, max_bytes=self._max_payload_bytes, person_id=named, **{name: other})
        return named, other

    async def guard(self, record_id: Identifier) -> Placement | None:
        """Keep the record ``record_id`` names for the owner alone (ADR-0217 §7).

        The narrowing half of the owner's act after the fact. What it writes and
        when it declines to write are :meth:`_place_once`'s, which is the whole of
        §3's precedence for both directions in one place — the two members differ in
        exactly one argument, and writing the rule twice is how the widening
        direction acquires a clause the narrowing one does not have.

        Args:
            record_id: The record's id, taken as opaque.

        Returns:
            The placement the record carries after the act, or ``None`` where the id
            named nothing live.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If memory cannot be read or written, including where
                §7's two-attempt bound was exhausted.
        """
        self._reject_if_closing()
        named = identifier(record_id, name="record_id")
        check_arguments("guard", max_bytes=self._max_payload_bytes, record_id=named)
        return await self._tracked(self._place(named, PlacementReach.OWNER), "guard", checked=True)

    async def unguard(self, record_id: Identifier) -> Placement | None:
        """Let the record ``record_id`` names be spoken to anyone again (ADR-0217 §7).

        The widening half, and the one the conditional write below exists for: a
        stale ``unguard`` writing reach ``ANYONE`` over a ``DERIVED`` placement that
        landed since the read is the in-place clearing ADR-0204 §5's closing
        prohibition forbids, and it is a disclosure rather than a lost merge.

        Args:
            record_id: The record's id, taken as opaque.

        Returns:
            The placement the record carries after the act — reach ``OWNER``, setter
            ``DERIVED``, unchanged, where §3 refuses the widening — or ``None`` where
            the id named nothing live.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If memory cannot be read or written, including where
                §7's two-attempt bound was exhausted.
        """
        self._reject_if_closing()
        named = identifier(record_id, name="record_id")
        check_arguments("unguard", max_bytes=self._max_payload_bytes, record_id=named)
        return await self._tracked(
            self._place(named, PlacementReach.ANYONE), "unguard", checked=True
        )

    async def _place(self, record_id: str, reach: PlacementReach) -> Placement | None:
        """One act's read-modify-write, re-run once if the store moved under it.

        **Two attempts in all** (ADR-0217 §7), written as two statements rather than
        as a loop so the bound is the code rather than a constant the code consults
        — the shape ``memory/ingest.py``'s conditional fold already takes for
        ADR-0219 §5's bound. A second refusal propagates as the
        ``MemoryStoreError`` it is: the caller is told the store would not take the
        write, and is never handed a placement no record carries. Raised from inside
        the first refusal's handler, so the traceback names both.

        **The re-run is the whole decision and never a re-submission.** The record
        is read again and §3's precedence is applied to the value it *now* carries,
        so a ``DERIVED`` narrowing that landed in the window is found and the
        widening is refused on the ordinary ground. Resubmitting the payload
        computed over the rejected snapshot would be the lost update wearing a
        conditional write's clothes.

        **Livelock is refused rather than made improbable** (§7). An act that cannot
        land while another writer rewrites the same record in a tight loop is a
        failure the caller can see, and the bound is safe because both acts are
        idempotent: a caller that meant it repeats it.
        """
        try:
            return await self._place_once(record_id, reach)
        except MemoryStoreStaleError:
            # Nothing was written — ADR-0219 §3's all-or-nothing — so there is no
            # partial state to unwind before the decision runs again.
            return await self._place_once(record_id, reach)

    async def _place_once(self, record_id: str, reach: PlacementReach) -> Placement | None:
        """Decide ADR-0217 §3's precedence over the record as read, and write once.

        **The read is in the call that writes**, never one read earlier (§7): the act
        follows the stored value and not the one a rendered list or a confirmation
        card showed, so a ``guard`` offered against a ``PROPOSED`` placement and
        performed on a record the derivation has since placed ``DERIVED`` leaves
        ``DERIVED`` and writes nothing.

        Two refusals and nothing else, both returning the placement the record
        already carries rather than raising:

        - **the setter is ``DERIVED``.** §3's closing clause is not lifted by an act
          in either direction. Widening is the case that clause is about; narrowing
          is refused for a different reason and with the same effect — §3's total
          order puts ``DERIVED`` above ``OWNER_ACT`` at the same reach, so a
          ``guard`` here would write a setter *weaker* than the one that in fact
          made the narrowing, which no implementation may record;
        - **the act would change neither the reach nor the setter.** This is what
          makes both operations idempotent in the strict sense: nothing is written,
          so the instant does not move and the second call returns exactly what the
          first returned.

        Everything else writes, including the two cases a reader is most likely to
        expect to be no-ops: a ``guard`` on reach ``OWNER`` with setter ``PROPOSED``
        writes, because it changes the setter from one the owner may lift to one §3
        calls final; and an ``unguard`` on the default placement writes, because it
        records reach ``ANYONE`` as an **act** — which is what makes the record an
        ineligible side against a later proposal in §3's fold, rather than a
        placement a model may narrow by duplication.
        """
        record = await self._memory.get(record_id)
        if record is None:
            return None
        standing = record.placement
        if standing.set_by is PlacementSetter.DERIVED:
            return standing
        if standing.reach is reach and standing.set_by is PlacementSetter.OWNER_ACT:
            return standing
        acted = Placement(reach=reach, set_by=PlacementSetter.OWNER_ACT, set_at=self._placed_at())
        await self._memory.write_atomic(
            [
                MemoryWrite(
                    record=record.model_copy(update={"placement": acted}),
                    mode=MemoryWriteMode.IF_UNCHANGED,
                    expected_revision=record.revision,
                )
            ]
        )
        return acted

    def _placed_at(self) -> datetime:
        """The clock's reading for an act's stamp, as the error of the write it rides.

        :meth:`_now`'s translation one stage over, on ADR-0026 §4's own rule that
        "each subsystem translates at its own boundary" and the reading takes "the
        error of the stage that read the clock". This reading exists only to stamp a
        placement being written to memory, and ADR-0217 §7 declares exactly two
        errors for the acts that carry it, so a non-conforming reading has to arrive
        as one of them or the exhaustive ``Raises`` list is false.

        Raises:
            MemoryStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise MemoryStoreError(str(exc)) from exc

    # --- the notification surface (ADR-0130 §7, §9) ------------------------

    async def notifications(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[HeldNotification, ...]:
        """List the notifications being held for the user, oldest first (§7).

        **The only way a notification reaches anyone through this façade.** §7 is
        unconditional that no notification and no count of notifications is
        injected into a turn's result, into :meth:`converse`, or into any
        response to a request that did not ask for it — ADR-0078 §8's third reach
        applied unchanged, and §11 forbids an implementing lane relaxing it.

        Args:
            limit: Page size, bounded by default (ADR-0073 §2, §8).
            offset: How many ordered rows to skip.

        Returns:
            The page, oldest first, expired records included and rendering as
            expired.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``limit`` or ``offset`` is outside ``[0, 2**63)``.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be read.
        """
        self._reject_if_closing()
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "notifications", max_bytes=self._max_payload_bytes, limit=limit, offset=offset
        )
        store = self._notification_surface()
        return await self._tracked(
            _as_tuple(store.held(limit=limit, offset=offset)), "notifications", checked=True
        )

    async def dismiss_notification(self, notification_id: Identifier) -> bool:
        """Dispose of one notification without destroying it (§7, §9).

        The first of the two acts §6 says a surface rendering an interruption
        should offer in one step. **A dismissal is not a deletion**: the record
        stays readable and stays in the user's export, and what ends is its
        actionability, which frees a slot under the cap at once (ADR-0215 §3).
        Freeing the slot does not free the notification's key: where the
        candidate declared an expiry, the record goes on suppressing that same
        fact until that instant, so dismissing does not invite it back on the
        next tick. Where the candidate declared **no** expiry there is no horizon
        to supply and suppression ends exactly where actionability does
        (ADR-0215 §1; §7 and §8 as ADR-0215 §§1-2 replace them).

        Args:
            notification_id: The notification the user named, taken as opaque.

        Returns:
            Whether an actionable notification was dismissed.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``notification_id`` is blank.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be written.
        """
        self._reject_if_closing()
        named = identifier(notification_id, name="notification_id")
        check_arguments(
            "dismiss_notification",
            max_bytes=self._max_payload_bytes,
            notification_id=named,
        )
        store = self._notification_surface()
        return await self._tracked(
            self._dismiss(store, named), "dismiss_notification", checked=True
        )

    async def _dismiss(self, store: NotificationStore, notification_id: str) -> bool:
        """End the record's actionability, then give up its outbox entry (§3, §3a).

        **A dismissal reaches the outbox, and the seam cannot notice it by
        itself.** ADR-0131 §3 makes an entry departing when its record "has ceased
        to be actionable", and names the two causes the seam can decide locally —
        it gave the entry up, or the candidate expired. An owner's dismissal is
        neither, which is why §3 says the third route "arrives as §3a's withdrawal —
        **the disposing act calls the seam** rather than the seam polling for it".
        Without this call the entry stays selectable and the next poll delivers a
        notification the owner has already dismissed.

        **The withdrawal goes first and performs the dismissal, and dismissing
        here and withdrawing afterwards was the defect.** That order commits the
        record's dismissal and only then reaches the outbox — so a withdrawal that
        fails leaves a non-actionable record beside an unmarked, still selectable
        entry, and the next poll delivers a notification the owner dismissed. The
        withdrawal marks the entry departing *before* it dismisses, so every failure
        along its path leaves an entry no poll can select, and §3b's reconciliation
        finishes it. That is the shape the acknowledgement path already has.

        Falling through to the store is for the ordinary case where the record was
        never offered, so the outbox holds no entry and has nothing to withdraw.
        """
        if self._notification_outbox is not None and await self._notification_outbox.withdraw(
            notification_id
        ):
            return True
        return await store.dismiss(notification_id)

    async def forget_notification(self, notification_id: Identifier) -> bool:
        """Destroy one notification (§9, ADR-0004 §6).

        ADR-0007's data right, unconditional like every other deletion on this
        façade. Beside
        :meth:`dismiss_notification` deliberately: that one ends actionability
        and leaves the record readable, so this is the surface the delete right
        reaches and that one is not.

        Args:
            notification_id: The notification the user named, taken as opaque.

        Returns:
            Whether a notification was destroyed.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``notification_id`` is blank.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be written.
            NotificationOutboxError: If the record's outbox entry could not be
                withdrawn. Nothing is deleted then, which is ADR-0131 §3a's
                ordering holding rather than failing: a record whose entry could
                not be given up may not be destroyed.
        """
        self._reject_if_closing()
        named = identifier(notification_id, name="notification_id")
        check_arguments(
            "forget_notification",
            max_bytes=self._max_payload_bytes,
            notification_id=named,
        )
        store = self._notification_surface()
        return await self._tracked(self._forget(store, named), "forget_notification", checked=True)

    async def _forget(self, store: NotificationStore, notification_id: str) -> bool:
        """Withdraw the record's outbox entry, then destroy the record (§3a).

        **The order is forced and only one of the two is safe.** ADR-0131 §3a: an
        act that deletes an ADR-0130 record "withdraws the record's outbox entry
        **first**, and deletes the record only after the withdrawal has committed.
        No lane may delete a record whose entry it has not already withdrawn."
        Deleting first leaves an entry whose record is gone — not departing, not
        expired, undetectably stale, and delivered on the next poll, after the user
        had deleted the thing it was about. Withdrawing first cannot produce that,
        and the one state a crash between them leaves is an actionable record with
        no entry, which is the incomplete-handoff case §3b's reconciliation repairs.

        **What it does not promise is that a delivery already staged will not
        land** (§3a). A poll can have selected and leased the entry, and the write
        happens after ``next_notification`` returned; closing that window would take
        the prepare/commit boundary this seam is built around not having. The
        guarantee is that no *later* poll selects it.

        An engine with no outbox wired withdraws nothing, which is the CLI's case:
        it serves no poll, so no entry can exist to be delivered.
        """
        if self._notification_outbox is not None:
            await self._notification_outbox.withdraw(notification_id)
        return await store.delete(notification_id)

    async def notification_preferences(self) -> NotificationPreferences:
        """Read the three standing settings that tune proactive contact (§6).

        Answerable from an empty store, which is the point: the tuning surface
        has to work on the first day, with no history, because the ruling on #879
        defers the usage anything could be calibrated from.

        Returns:
            The settings in force, defaulted where the user has set nothing.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be read.
        """
        self._reject_if_closing()
        check_arguments("notification_preferences", max_bytes=self._max_payload_bytes)
        store = self._notification_surface()
        return await self._tracked(store.preferences(), "notification_preferences", checked=True)

    async def set_notification_preferences(
        self, preferences: NotificationPreferences
    ) -> NotificationPreferences:
        """Write the standing settings and re-arm what the change reaches (§6).

        **The write and the re-arming are one atomic act in the store**, and this
        façade adds nothing to it: stamping a due instant routes the user's act
        through §5's one ruling path instead of adding a second, and the
        reconsideration job picks the records up on its next run.

        Args:
            preferences: The settings to hold from now on. The whole value, so
                two concurrent writers cannot each silently drop the other's
                field.

        Returns:
            The settings now in force, as the store holds them.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If two rows name one class, or a quiet window carries a
                timezone or has no readable extent.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be written.
        """
        self._reject_if_closing()
        check_arguments(
            "set_notification_preferences",
            max_bytes=self._max_payload_bytes,
            preferences=preferences,
        )
        store = self._notification_surface()
        return await self._tracked(
            _written_preferences(store, preferences),
            "set_notification_preferences",
            checked=True,
        )

    async def reconsider_notifications(self, *, page: int = DEFAULT_PAGE_SIZE) -> int:
        """Re-rule every held notification that has fallen due (ADR-0130 §5).

        The **maintenance surface** ADR-0083 §8 puts "on a class in
        ``orchestration``, not ``core`` contract surface", and §5 is explicit that
        this is **not** a member of ``AssistantEngine``: no client asks for it and
        no interface adapter may drive it. Its only caller is the hub's scheduler,
        whose job body is this bound method and which holds no store — ADR-0083
        §7's "no job gets new store surface" and §8's "every job is a bound public
        engine method" both hold unchanged.

        **A late run is not a fault.** ``reconsider_at`` is the instant before
        which a record may not be reconsidered, never a deadline by which it must
        have been, on ADR-0083 §7's rule that "a missed or late tick is never a
        correctness bug". A record another writer moved or resolved between the
        page and the re-ruling simply reports nothing to do.

        **One run drains the whole due set**, and ``page`` is a read size rather
        than a run bound. §5 defines this operation over "every record whose
        ``reconsider_at`` has arrived", so a run that stopped at a page would
        leave the fifty-first record held past the instant the user's own act
        made it due — and the user has no way to ask for the rest.

        **``page`` is refused unless it is strictly positive**, which is stricter
        than the page rule on this class's read methods and is the drain's own
        clause: a page of zero reads nothing, so the loop below would exit having
        ruled nothing while this method promises to have ruled everything. A read
        size of zero is not a smaller sweep, it is a silent no-op — the class of
        value ADR-0022 §4a refuses rather than absorbs.

        Args:
            page: How many due records one store read takes. It bounds the read,
                never the run.

        Returns:
            How many records were re-ruled.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``page`` is not an integer in ``(0, 2**63)``.
            ConfigurationError: If no notification store is wired.
            NotificationStoreError: If the store cannot be read or written, or the
                owner's zone could not be read from the person-model store before a
                ruling (ADR-0338 §3:6). That record is not ruled, so its quiet
                window is never read in a zone that is not theirs: it stays due, and
                the next run rules it (ADR-0130 §5).
        """
        self._reject_if_closing()
        positive_page_argument(page, name="page")
        return await self._tracked(self._reconsider(page), "reconsider_notifications", _ruled)

    async def _hand_off(
        self, ruling: NotificationDisposition, candidate: NotificationCandidate
    ) -> None:
        """Give a freshly ruled ``INTERRUPT`` to the outbox, now (ADR-0131 §3b).

        **The live handoff is the primary path, and reconsideration is one of its
        call sites.** §3b: "a hub that committed a disposition, spent its budget
        and simply never called ``offer`` broke no rule here, while a device sat on
        an outstanding long poll receiving nothing", and it names this path
        specifically — "It is also the reconsideration path's answer without a
        second clause — ADR-0130 §5 rules a held record to ``INTERRUPT`` through
        the same writer, so the same handoff runs." Without this call the
        notification the user's own setting change made actionable waits for a
        restart, which is precisely what §3b forbids reconciliation from being:
        "a repair that is also the primary path is a design where the ordinary case
        waits on a restart".

        The handoff belongs here because this path already holds both halves — it
        has just received the disposition and it holds the candidate — so nothing
        needs to be looked up and no scheduler needs to exist.

        **A terminal refusal ends the record**, and the outbox does that itself:
        ``offer`` dismisses on ``TOO_LARGE`` and ``KEY_COLLISION`` (§3b), so no
        refusal leaves an actionable record with no entry. A
        ``NotificationOutboxError`` propagates: no custody transferred, the record
        stays actionable, and the next reconciliation offers it.

        A deployment with no outbox composed hands off nothing, which is the CLI's
        case: it serves no poll, so there is nowhere for a notification to go.

        **The rule itself lives in one place** —
        :func:`~ai_assistant.orchestration.notifications.hand_off`, which
        ADR-0130 §3's concrete write stage calls on the *live* path. §3b binds both
        paths with one clause, and two copies of it are two places for it to drift.
        """
        await hand_off(self._notification_outbox, ruling, candidate)

    async def _reconsider(self, page: int) -> int:
        """Drain the due set, a page at a time.

        **Every due record, not the first page of them** (§5). ``page`` bounds
        how many ids are held in memory at once and how large one store read is;
        it does not bound the run, because a bounded run would leave the 51st
        record of a large sweep held past the instant the user's own act made it
        due — and §5's operation is defined over "every record whose
        ``reconsider_at`` has arrived".

        **The drain terminates, and it does not take the policy's word for it.**
        The argument for progress is that a re-ruling writes a ``reconsider_at``
        strictly later than the instant it ruled at, or none at all, so a record
        re-ruled here leaves the due set. But that is a property of an
        *implementation* of :class:`~ai_assistant.core.protocols.NotificationPolicy`,
        and this loop is the hub's scheduler thread: a policy that returned an
        instant already past would spin it forever, which is a whole assistant
        hung by a contract clause nothing enforces.

        So the loop ends on either of two conditions, and each covers a case the
        other does not. A page that re-rules **nothing** means nothing is left to
        do — that is also what a page of records another writer resolved first
        looks like. And a page holding **no id this run has not already ruled**
        means the store is handing back records this run has dealt with, whatever
        their instants now say.

        **Each ruling is handed the policy of the owner's zone**, read just before it
        (ADR-0338 §3:6, :class:`~ai_assistant.orchestration.notifications.RulingPolicy`),
        so a zone changed mid-drain governs the records ruled after it.

        Args:
            page: How many due records one store read takes.

        Returns:
            How many were re-ruled.
        """
        store = self._notification_surface()
        assert self._notification_policies is not None  # noqa: S101 — wired together (see __init__)
        policies = self._notification_policies
        seen: set[str] = set()
        ruled = 0
        while due := await store.due(limit=page):
            fresh = [record for record in due if record.id not in seen]
            if not fresh:
                break
            before = ruled
            for record in fresh:
                seen.add(record.id)
                ruling = await store.reconsider(record.id, policy=await policies.pick())
                if ruling is not None:
                    ruled += 1
                    await self._hand_off(ruling, record.candidate)
            if ruled == before:
                break
        return ruled

    async def remove_device(self, device_id: str) -> bool:
        """Remove a revoked device from "my devices" and every conversation's devices.

        ADR-0298 §4:10: revoking a device removes it "from 'my devices' and from every
        conversation's devices", and ADR-0296 §3:6 "as an end of every conversation".
        The hub's owner act calls this once the device roster has revoked the device
        (``service.admin``), so the device is already refused before it leaves the
        sets.

        **Maintenance surface, not contract surface**, for :meth:`purge_expired`'s
        reason (ADR-0083 §8): its one caller is the hub, which holds an ``Engine``
        and no concrete store, so it is a method on this class and not on
        :class:`~ai_assistant.core.protocols.AssistantEngine` — no device may revoke
        another over the wire, and roles are given only at the hub (ADR-0298 §4:12).
        It runs as tracked work, so shutdown drains an act that races it.

        One step against "my devices" and every conversation together, each removal
        recorded as the change setting that set would record
        (:meth:`~ai_assistant.core.protocols.ConversationStore.remove_device`), so
        every other device sees it; safe to repeat.

        Args:
            device_id: The revoked device.

        Returns:
            Whether any set named the device.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``device_id`` is blank.
            ConversationStoreError: If the store cannot be written.
        """
        self._reject_if_closing()
        named = identifier(device_id, name="device_id")
        return await self._tracked(
            self._conversations.chat_space.remove_device(named), "remove_device"
        )

    def _notification_surface(self) -> NotificationStore:
        """The wired notification store, or a legible refusal.

        Returns:
            The store.

        Raises:
            ConfigurationError: If none is wired, in :meth:`notice_upcoming_events`'s shape — a
                deployment that has composed no notification store has no held
                notifications, and saying so is different from answering "none".
        """
        if self._notifications is None:
            msg = (
                "no notification store is wired, so there are no held notifications to "
                "read or tune (ADR-0130 §9). The contract surface exists ahead of the "
                "store the composition root will build for it"
            )
            raise ConfigurationError(msg)
        return self._notifications

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """List conversations by last activity, most recent first (ADR-0074 §2).

        The read that lets the hub answer "which conversation?" — because a
        stateless client cannot. Without it, "continue yesterday's conversation"
        would require the *interface* to have kept the id, which is precisely the
        state VISION §Principle 8 forbids an interface to own.

        A conversation the user deleted is absent, by the store's own contract and
        not by anything re-filtered here: the stamp hides it from every read that
        presents a conversation. Nothing on this surface can show one.

        Args:
            limit: Page size, bounded by default at 50 — the figure
                ``AuditTrail.recent`` set and ADR-0073 §2 reused. ``0`` returns an
                empty page.
            offset: How many ordered rows to skip before the page begins. Offset
                paging over a store being written to may skip or repeat a row,
                which ADR-0073 §2 names and accepts: a listing a user re-runs is
                not a transaction.

        Returns:
            The page, activity descending with ``id`` breaking ties.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``limit`` or ``offset`` falls outside ``[0, 2**63)``, as
                the store refuses rather than clamps. Not an ``AssistantError``, so
                an adapter letting a user supply either must refuse an out-of-range
                value at its own parse boundary.
            ConversationStoreError: If the index cannot be read.
        """
        self._reject_if_closing()
        self._check_page("recent_conversations", limit=limit, offset=offset)
        device = current_requesting_device()
        return await self._tracked(
            self._recent_conversations(device, limit=limit, offset=offset),
            "recent_conversations",
            checked=True,
        )

    async def _recent_conversations(
        self, device: RequestingDevice, *, limit: int, offset: int
    ) -> tuple[ConversationSummary, ...]:
        """Relay the listing to the stage and project each record.

        ADR-0298 §5 "Reading many": a device other than the hub's own machine must
        hold a role, and is listed only the conversations it reads, in the same
        order and pages (``ConversationStore.device_conversations``).
        """
        if device.is_hub:
            listed = await self._conversations.recent(limit=limit, offset=offset)
            return tuple(conversation_summary(one) for one in listed)
        await self._device_checks.reading_many(device, "recent_conversations")
        reads = await self._conversations.device_conversations(
            device.device_id, limit=limit, offset=offset
        )
        return tuple(conversation_summary(one.conversation) for one in reads)

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """Read the count and span a deletion is about to destroy (ADR-0074 §8).

        The single-conversation read the deletion ceremony needs: a person cannot
        consent to destroying something they were not shown, and for a conversation
        what a human can judge is its count and span rather than every turn
        (ADR-0073 §5's show-then-confirm, at the unit the user thinks in).

        ``None`` when the id names nothing **or** names a conversation already
        stamped deleted — the surface declines what it cannot display rather than
        taking consent for it.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the index cannot be read.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("conversation", max_bytes=self._max_payload_bytes, conversation_id=named)
        running = list(self._running_conversations().get(named, ()))
        device = current_requesting_device()
        return await self._tracked(
            self._digest(device, named, running=running), "conversation", checked=True
        )

    def _running_conversations(self) -> dict[str, tuple[str | None, ...]]:
        """What this engine runs, per conversation it was started from (ADR-0293 §8:2).

        Each running activation started from a conversation, oldest first, by its id
        — ``None`` for one whose id the factory failed to mint (ADR-0297 §5) — and
        each activation the chat's reader has an input in for, which shows "working…"
        until the message answering it is written, after its own run has ended. Read
        by :meth:`conversation` and by the change stream (ADR-0296 §4:9).
        """
        running: dict[str, list[str | None]] = {}
        for one in self._running:
            if one.state is not None and one.state.conversation_id is not None:
                running.setdefault(one.state.conversation_id, []).append(one.state.activation_id)
        if (reader := self._chat_reader) is not None:
            # ADR-0349 §8:1: several activations may run from one conversation.
            for conversation_id in reader.activity():
                reading = reader.running(conversation_id)
                if not reading:
                    continue
                held = running.setdefault(conversation_id, [])
                held.extend(one for one in reading if one not in held)
        return {conversation_id: tuple(held) for conversation_id, held in running.items()}

    def _count_end(self, scope: ActivationScope) -> None:
        """Count an activation's end against the conversation it was started from.

        ADR-0296 §4:9: an end the change stream can see, even where the activation
        began and ended between two of its readings (:meth:`_activity`).
        """
        if scope.state is not None and (ended := scope.state.conversation_id) is not None:
            self._count_change(ended)

    def _count_change(self, conversation_id: str) -> None:
        """Move the count the change stream reads a conversation's state changes by."""
        self._activation_turns[conversation_id] = self._activation_turns.get(conversation_id, 0) + 1

    async def _forgetting_conversation(self, conversation_id: str) -> bool:
        """Forget the episodes on a conversation's place, then count the change (§4:9).

        Counted however the walk ends, since one that failed part-way may still have
        destroyed the episode the state was read from.
        """
        try:
            return await self._conversations.forget(conversation_id)
        finally:
            self._count_change(conversation_id)

    def _activity(self) -> dict[str, Activity]:
        """What this engine runs per conversation, with a count of its starts and ends.

        The change stream's reading (ADR-0296 §4:9): :meth:`_running_conversations`,
        beside a count that moves when an activation started from the conversation
        ends, or when the chat's reader admits one or writes its reply.
        """
        running = self._running_conversations()
        reader = {} if self._chat_reader is None else self._chat_reader.activity()
        named = running.keys() | self._activation_turns.keys() | reader.keys()
        return {
            conversation_id: Activity(
                turns=self._activation_turns.get(conversation_id, 0)
                + reader.get(conversation_id, (0, None))[0],
                running=running.get(conversation_id, ()),
            )
            for conversation_id in named
        }

    async def _digest(
        self, device: RequestingDevice, conversation_id: str, *, running: Sequence[str | None]
    ) -> ConversationDigest | None:
        """ADR-0298 §5 "Reading one", then the digest."""
        await self._device_checks.reading(device, conversation_id, "conversation")
        return await self._conversations.digest(conversation_id, running=running)

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Forget the episodes on a conversation's place, and leave it (ADR-0293 §2:4).

        Memory-only since ADR-0293 §11:4: every episode on the conversation's place
        is destroyed — an open one told first, so no later write re-creates it (§2:6)
        — whether or not the conversation still stands (§2:5), and the conversation,
        its transcript and its devices are not reached (§5:6). Removing those is
        :meth:`delete_conversation`, and no single operation both deletes and
        forgets (§2:7). Unconditional, like every other deletion on this façade.

        Args:
            conversation_id: The conversation the user named, taken as opaque.

        Returns:
            Whether an episode was forgotten. ``False`` where the place held none.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If an episode could not be read or destroyed. What was
                destroyed stays destroyed, the conversation stands, and a repeat
                finishes the walk.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        return await self._tracked(
            self._forgetting_conversation(named),
            "forget_conversation",
            checked=True,
        )

    # --- the chat space: acts in the medium and its reads (ADR-0293 §11) ---

    async def start_conversation(self) -> ConversationSummary:
        """Start an empty conversation, shown on "my devices" (ADR-0293 §2:1, §3:1).

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the conversation could not be started.
        """
        self._reject_if_closing()
        device = current_requesting_device()
        return await self._tracked(self._started(device), "start_conversation", checked=True)

    async def _started(self, device: RequestingDevice) -> ConversationSummary:
        """ADR-0298 §5 "Starting", then the conversation."""
        await self._device_checks.starting(device)
        return conversation_summary(await self._conversations.start())

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Read "my devices" (ADR-0293 §3:1).

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the set could not be read.
        """
        self._reject_if_closing()
        return await self._tracked(self._conversations.my_devices(), "my_devices", checked=True)

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" (ADR-0293 §3:1, §3:2).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``devices`` is not a set of devices the store accepts.
            ConversationStoreError: If the set could not be written.
        """
        self._reject_if_closing()
        held = checked_chat_devices(devices)
        check_arguments("set_my_devices", max_bytes=self._max_payload_bytes, devices=held)
        check_devices_fit(held, conversation_id=None, max_bytes=self._max_payload_bytes)
        return await self._tracked(
            self._conversations.set_my_devices(held), "set_my_devices", checked=True
        )

    async def set_conversation_devices(
        self, conversation_id: Identifier, *, devices: Sequence[ChatDevice]
    ) -> bool:
        """Choose one conversation's devices (ADR-0293 §3:3).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If the id is blank or ``devices`` is refused.
            UnknownConversationError: If the id names no conversation, or one deleted.
            ConversationStoreError: If the set could not be written.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        held = checked_chat_devices(devices)
        check_arguments(
            "set_conversation_devices",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            devices=held,
        )
        check_devices_fit(held, conversation_id=named, max_bytes=self._max_payload_bytes)
        return await self._tracked(
            self._conversations.set_conversation_devices(named, held),
            "set_conversation_devices",
            checked=True,
        )

    async def write_message(
        self, conversation_id: Identifier, *, message: UserMessage
    ) -> MessageReceipt:
        """Write the user's message into a conversation, answering *received* (§4).

        Recorded and answered here; taking it in is the chat's reader's (§6).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If the id is blank or ``message`` is not a ``UserMessage``.
            UnknownConversationError: If the id names no conversation, or one deleted.
            ConversationStoreError: If the message could not be written.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        sent = user_message(message)
        check_arguments(
            "write_message", max_bytes=self._max_payload_bytes, conversation_id=named, message=sent
        )
        check_message_fits(named, sent, max_bytes=self._max_payload_bytes)
        device = current_requesting_device()
        return await self._tracked(
            self._written(device, named, sent), "write_message", checked=True
        )

    async def _written(
        self, device: RequestingDevice, conversation_id: str, message: UserMessage
    ) -> MessageReceipt:
        """Record the message, then tell the chat's reader it is there (ADR-0293 §6:1).

        The act answers *received* once the conversation has recorded the message and
        starts nothing itself: the reader, told after the record, takes it in — at once,
        or once the activation running from this conversation ends (§6:2, §6:3). A
        repeat is told too, since the message it repeats may still be waiting.

        First, ADR-0298 §2:7 and §5 "Writing": a device other than the hub's own
        machine writes only under its own id, and only as an end for writing. The
        activation the reader starts does not run as this device: the reader's read
        is started in a context of its own (:meth:`_spawn_read`, §2:6).
        """
        await self._device_checks.writing_message(device, conversation_id, message)
        receipt = await self._conversations.write(conversation_id, message)
        if receipt.position is not None and self._chat_reader is not None:
            self._chat_reader.notice(conversation_id)
        return receipt

    async def composing(self, conversation_id: Identifier) -> None:
        """Take the hub chat page's signal that the person is typing (ADR-0332 §5:9).

        It writes nothing into the medium, into any store or into any episode, and
        answers nothing (§5:8). ADR-0298 §5's Writing row comes first (ADR-0332 §5:11).
        The signal then goes to the chat's reader, where it only extends a start wait
        already running for the conversation, and does nothing where none is (§5:7).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If the id is blank.
            DeviceRefusedError: If the requesting device is not one of the
                conversation's ends for writing.
            ConversationStoreError: If the conversation's devices could not be read.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("composing", max_bytes=self._max_payload_bytes, conversation_id=named)
        device = current_requesting_device()
        # Untraced: a signal is written into no store (§5:8), the trace store included,
        # and a page sends one a second while the person types (§5:5).
        await self._tracked(self._composed(device, named), "composing", checked=True, traced=False)

    async def _composed(self, device: RequestingDevice, conversation_id: str) -> None:
        """ADR-0298 §5 "Writing", then the signal to the chat's reader (ADR-0332 §5:7)."""
        await self._device_checks.writing(device, conversation_id, "composing")
        if self._chat_reader is not None:
            self._chat_reader.composing(conversation_id)

    async def delete_message(self, conversation_id: Identifier, *, position: int) -> bool:
        """Delete one message, leaving its marker (ADR-0293 §5:8, §5:12).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If the id is blank or ``position`` is out of range.
            UnknownConversationError: If the id names no conversation, or one deleted.
            ConversationStoreError: If the message could not be deleted.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        at = check_chat_position(position, name="position")
        check_arguments(
            "delete_message", max_bytes=self._max_payload_bytes, conversation_id=named, position=at
        )
        device = current_requesting_device()
        return await self._tracked(
            self._deleted_message(device, named, at), "delete_message", checked=True
        )

    async def _deleted_message(
        self, device: RequestingDevice, conversation_id: str, position: int
    ) -> bool:
        """ADR-0298 §5 "Writing", then the deletion."""
        await self._device_checks.writing(device, conversation_id, "delete_message")
        return await self._conversations.delete_message(conversation_id, position)

    async def delete_conversation(self, conversation_id: Identifier) -> bool:
        """Delete a conversation and its transcript, forgetting nothing (ADR-0293 §2:3).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If the id is blank.
            ConversationStoreError: If the deletion could not be written.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "delete_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        device = current_requesting_device()
        return await self._tracked(
            self._deleted_conversation(device, named), "delete_conversation", checked=True
        )

    async def _deleted_conversation(self, device: RequestingDevice, conversation_id: str) -> bool:
        """ADR-0298 §5 "Writing", then the deletion."""
        await self._device_checks.writing(device, conversation_id, "delete_conversation")
        return await self._conversations.delete(conversation_id)

    async def transcript(
        self,
        conversation_id: Identifier,
        *,
        before: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> TranscriptPage | None:
        """Read a conversation's recent messages, or older ones (ADR-0293 §5:13).

        A page that does not fit the payload limit is shortened from its oldest end.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an argument is out of range.
            ConversationStoreError: If the transcript could not be read.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        below = None if before is None else check_chat_position(before, name="before")
        page_argument(limit, name="limit")
        check_arguments(
            "transcript",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            before=below,
            limit=limit,
        )
        device = current_requesting_device()
        return await self._tracked(
            self._transcript(device, named, before=below, limit=limit),
            "transcript",
            checked=True,
        )

    async def _transcript(
        self, device: RequestingDevice, conversation_id: str, *, before: int | None, limit: int
    ) -> TranscriptPage | None:
        """ADR-0298 §5 "Reading one", then the page, fitted."""
        await self._device_checks.reading(device, conversation_id, "transcript")
        page = await self._conversations.transcript(conversation_id, before=before, limit=limit)
        return fit_transcript(page, max_bytes=self._max_payload_bytes)

    async def chat_changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[Identifier] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ChatChanges:
        """Read every change to the chat space after a cursor (ADR-0293 §5:10, §5:11).

        A page that does not fit the payload limit is shortened from its newest end.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If an argument is out of range.
            ConversationStoreError: If the changes could not be read.
        """
        self._reject_if_closing()
        cursor = check_chat_cursor(after, name="after")
        named = chat_conversation_ids(conversation_ids)
        page_argument(limit, name="limit")
        check_arguments(
            "chat_changes",
            max_bytes=self._max_payload_bytes,
            after=cursor,
            conversation_ids=named,
            limit=limit,
        )
        device = current_requesting_device()
        return await self._tracked(
            self._chat_changes(device, after=cursor, conversation_ids=named, limit=limit),
            "chat_changes",
            checked=True,
        )

    async def _chat_changes(
        self,
        device: RequestingDevice,
        *,
        after: int,
        conversation_ids: tuple[str, ...] | None,
        limit: int,
    ) -> ChatChanges:
        """The page for the hub's own machine, or the device's own (ADR-0298 §5).

        "Reading many": a device other than the hub's own machine must hold a role,
        and reads ``ConversationStore.device_changes`` — the changes it may see, by
        its membership as each change was recorded — restricted to the conversations
        it named as :meth:`ConversationStore.changes` restricts them.
        """
        if device.is_hub:
            page = await self._conversations.changes(
                after=after, conversation_ids=conversation_ids, limit=limit
            )
        else:
            await self._device_checks.reading_many(device, "chat_changes")
            page = await device_changes(
                self._conversations,
                device.device_id,
                after=after,
                conversation_ids=conversation_ids,
                limit=limit,
            )
        return fit_changes(page, max_bytes=self._max_payload_bytes)

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Follow the chat space's change stream from a cursor (ADR-0296 §4, ADR-0298 §7).

        ADR-0298 §5 "Reading many": a device other than the hub's own machine must
        hold a role, checked as the stream's first step, and is sent only what it may
        see (:class:`~ai_assistant.orchestration.change_stream.ChangeStream`). Every
        read the stream makes, its role check included, is tracked for the drain and
        traced by none (:meth:`_stream_read`).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``after`` is outside ``[0, 2**63)``.
            OversizedValueError: If the arguments exceed the contract limit.
        """
        self._reject_if_closing()
        cursor = check_chat_cursor(after, name="after")
        check_arguments("follow_chat", max_bytes=self._max_payload_bytes, after=cursor)
        device = current_requesting_device()
        return self._following(device, cursor)

    async def _following(
        self, device: RequestingDevice, cursor: int
    ) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Check the device's role, then relay its stream."""
        if not device.is_hub:
            await self._stream_read(self._device_checks.reading_many(device, "follow_chat"))
        async with closing_stream(self._change_stream.follow(device, after=cursor)) as chunks:
            async for chunk in chunks:
                yield chunk

    async def _stream_read[T](self, work: Awaitable[T]) -> T:
        """Run one read of an open change stream as a task shutdown drains, untraced.

        A change stream is no one operation: it reads the chat space on an interval for
        as long as its device follows it (ADR-0298 §7), so a trace per read would be a
        trace per interval per open stream, recording no operation anyone asked for.
        Each read is still registered for the drain (ADR-0042 §2), and is not
        shielded: a device that stops following stops the read. Once shutdown has
        begun a read is refused, as every public call is, so none is registered after
        the drain has looked; the stream ends on that refusal.

        Raises:
            RuntimeError: If the engine is shutting down.
        """
        if self._closing and isinstance(work, Coroutine):
            work.close()  # never started, so never awaited
        self._reject_if_closing()
        return await self._track(work, "follow_chat", traced=False)

    # --- the delivery surface (ADR-0131 §1, §4) ----------------------------

    async def next_notification(
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Wait up to ``budget`` for a notification, acknowledging the last one.

        ADR-0131 §1's long poll, from the engine's side. The three steps are
        ordered by §4 rather than by taste — **validate, then acknowledge, then
        select** — and the ordering is what stops two conforming hubs disagreeing
        about a device that sends a valid ``acknowledging`` with an invalid
        ``budget``: one would acknowledge and then refuse, permanently retiring a
        delivery while reporting a failed request, so the device's retry would find
        the notification gone. "Arguments are validated before the acknowledgement
        is applied, before any entry is selected, and before any other outbox state
        changes; a refused request retires nothing, leases nothing and mints
        nothing."

        **The wait is a re-read loop and not a subscription**, which is what keeps
        it correct without durable per-poll state: the outbox's arrival hint saves
        latency and decides nothing, because every answer comes from asking the
        outbox again. A budget of zero therefore does exactly one read, which is
        §4's immediate poll — "the same request with the waiting removed" — rather
        than a case of its own.

        **A fourth step follows the three, and only where the caller asked for one**
        (ADR-0206 §1): the rendering, produced *inside this call*, after the entry
        has been selected and never before. Nothing is pre-rendered at ``offer``, at
        disposition or at reconsideration; nothing is retained between polls; and a
        redelivery of the same entry renders afresh, because a rendering is not a
        property of an entry at all. It goes to no store, index, trail, trace, audit
        trail or log, in either tier (ADR-0200 §8).

        **The ordering rule reaches ``plays`` unchanged** (ADR-0131 §4, ADR-0206 §7).
        A malformed ``plays`` is an argument, so it is refused before the
        acknowledgement is applied, before any entry is selected and before any other
        outbox state changes — and no rendering is attempted on a request whose
        arguments were refused.

        **This method holds no** ``MemoryStore`` **while answering** (ADR-0206 §3). The
        placement is decided from three recorded fields of the candidate the outbox
        handed over, and nothing on this path issues a store query of any kind, resolves
        ``references``, or reads a record — which is what keeps ADR-0204 §3's test where
        ADR-0204 §5 puts it, on the producer, rather than on a delivery that has nothing
        in hand.

        Args:
            acknowledging: The ``delivery_id`` being confirmed, or ``None``.
            plays: The formats the caller can render, in preference order. Empty —
                the default — asks for no rendering, and none is produced: no
                placement is decided, no synthesizer is called, and nothing about
                this poll's behaviour differs from what ADR-0131 §4 fixes.
            budget: How long the hub may hold this request before answering with
                nothing. It bounds the **waiting** and nothing else (ADR-0135 §3), so
                a poll that renders answers later than ``budget`` by construction.

        Returns:
            The delivery to show, or ``None`` where the budget elapsed with
            nothing available.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``acknowledging`` is blank, or ``plays`` names something
                that is not a
                :class:`~ai_assistant.core.types.SpokenAudioFormat`.
            NotificationBudgetError: If ``budget`` is negative or above the
                configured ceiling.
            ConfigurationError: If no delivery outbox is wired.
            NotificationOutboxError: If the outbox cannot be read or written, or
                an acknowledgement's dismissal could not commit.
        """
        self._reject_if_closing()
        named = None if acknowledging is None else identifier(acknowledging, name="acknowledging")
        self._check_budget(budget)
        wanted = self._check_plays(plays)
        check_arguments(
            "next_notification",
            max_bytes=self._max_payload_bytes,
            acknowledging=named,
            plays=wanted,
            budget=budget,
        )
        outbox = self._delivery_surface()
        # **Unshielded, alone on this surface** (ADR-0131 §2a): a poll whose
        # connection has gone must stop and take no entry, so the wire's cancel of
        # its dispatch task has to reach the work. The mutating steps inside are
        # scope-shielded instead — see :meth:`_poll`. The rendering is deliberately
        # *not* shielded either: ADR-0206 §6 makes a cancellation delivered while a
        # synthesis is outstanding neither a withholding nor a degradation, so it
        # propagates and sets no ``spoken_rendering`` at all.
        device = current_requesting_device()
        return await self._tracked(
            self._polled(device, outbox, named, wanted, budget),
            "next_notification",
            checked=True,
            shielded=False,
        )

    async def _polled(
        self,
        device: RequestingDevice,
        outbox: DeliveryOutbox,
        acknowledging: Identifier | None,
        plays: tuple[SpokenAudioFormat, ...],
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """ADR-0298 §5 "Notification poll", before the acknowledgement, then the poll.

        A refused poll acknowledges nothing, leases nothing and mints nothing (§6:1,
        ADR-0131 §4).
        """
        await self._device_checks.polling(device)
        return await self._poll(outbox, acknowledging, plays, budget)

    @staticmethod
    def _check_plays(plays: tuple[SpokenAudioFormat, ...]) -> tuple[SpokenAudioFormat, ...]:
        """Refuse a ``plays`` naming a format that does not exist, and normalise it.

        **An empty one is admitted rather than refused**, unlike the retired
        ``converse_spoken``'s (ADR-0200 §3), and the asymmetry is ADR-0206 §1's: there,
        an empty preference order was a call that could not be answered whatever the
        synthesizer produces; here it is the ordinary state of every caller that cannot
        play audio, and it asks for no rendering rather than for an impossible one.

        **It coerces rather than requiring the member, so the two implementations of
        this contract agree.** Over the wire, ``wire.surface`` derives this argument's
        adapter from the signature and ADR-0087 §7's order — decode, validate into the
        declared type, then measure — turns a member's *value* into the member before
        this method sees it, so a client sending ``"audio/mp4"`` is a conforming
        caller. In-process there is no adapter, so a bare ``str`` arrives as it was
        written; refusing it here would make the in-process engine strictly less
        capable than the client that stands in for it, which is exactly the divergence
        ADR-0084 §4 forbids "in **either** direction". What is refused is what
        validation would refuse either way: a string naming no member at all. Refused
        **before any outbox effect**, which is ADR-0131 §4's ordering reaching ADR-0206
        §7's third clause.

        Args:
            plays: What the caller says it can render.

        Returns:
            The same preference order, with every member normalised to the
            enumeration — so the format handed to the seam is a
            :class:`~ai_assistant.core.types.SpokenAudioFormat` whichever way the
            caller spelled it.

        Raises:
            ValueError: If a member names no format this build declares — including
                an **unhashable** one, whose lookup raises ``TypeError`` inside the
                enumeration before a value comparison is ever reached. That is a
                malformed argument like any other, and the declared refusal is the
                one both implementations and the Protocol document, so it is
                translated rather than allowed to escape undeclared (#1762) — as is
                every other way coercing a member can fail, since each of them is one
                way of saying it is not a format. A member whose ``__repr__`` raises
                is the case that makes the totality load-bearing: the enumeration
                interpolates the value while *constructing* its own ``ValueError``,
                so that object's exception replaces the refusal before any narrower
                clause could see one. This method's own message describes the member
                through :func:`describe_untrusted` for the other half of the same
                promise.
        """
        named: list[SpokenAudioFormat] = []
        for member in plays:
            try:
                named.append(SpokenAudioFormat(member))
            # Every way this can fail is one way of saying "that is not a format", so
            # the translation is total rather than an enumeration of the failures seen
            # so far. ``ValueError`` is the ordinary one; an *unhashable* member raises
            # ``TypeError`` from the lookup that precedes the value comparison (#1762);
            # and a member whose ``__repr__`` raises does so from inside CPython's own
            # ``enum.__new__``, which interpolates it while *constructing* the
            # ``ValueError`` — so there is no ``ValueError`` to catch at all, and a
            # narrower clause would let that object's exception out in place of the
            # refusal the Protocol and both implementations document.
            except Exception:  # a value that cannot be coerced is malformed, however it failed
                readable = ", ".join(sorted(known.value for known in SpokenAudioFormat))
                msg = (
                    f"plays names the formats the caller can render, and "
                    f"{describe_untrusted(member)} is "
                    f"not one of them; this build declares {readable}. A malformed "
                    f"argument is refused before the acknowledgement is applied and "
                    f"before any entry is selected (ADR-0131 §4, ADR-0206 §7)"
                )
                raise ValueError(msg) from None
        return tuple(named)

    def _check_budget(self, budget: timedelta) -> None:
        """Refuse a budget outside ADR-0131 §4's closed range, before any effect.

        **Both ends, and the hub does not silently clamp either.** ``timedelta``
        admits zero and negative values and exceeds no maximum, so without this one
        implementation would return an empty result for a negative budget while
        another handed it to a timeout primitive and raised something undeclared —
        no common conforming behaviour. Zero is admitted rather than refused
        because it is the one out-of-range-looking value that means something: a
        device just opened by the owner wants to know what is waiting *now*.

        Raises:
            NotificationBudgetError: If ``budget`` is outside the range.
        """
        if budget < timedelta(0) or budget > self._max_notification_budget:
            msg = (
                f"budget must be between 0 and {self._max_notification_budget} inclusive, "
                f"got {budget}: the hub does not clamp a budget it cannot honour, because "
                f"accepting one and honouring a shorter one tells the client, by "
                f"acceptance, that its budget was accepted (ADR-0131 §4)"
            )
            raise NotificationBudgetError(msg)

    def _delivery_surface(self) -> DeliveryOutbox:
        """The wired delivery outbox, or a legible refusal.

        Returns:
            The outbox.

        Raises:
            ConfigurationError: If none is wired, in
                :meth:`_notification_surface`'s shape — a deployment that has
                composed no outbox can deliver nothing, and saying so is different
                from answering "nothing is waiting for you".
        """
        if self._notification_outbox is None:
            msg = (
                "no notification outbox is wired, so no notification can be delivered "
                "(ADR-0131 §3). The contract surface exists ahead of the outbox the "
                "composition root will build for it"
            )
            raise ConfigurationError(msg)
        return self._notification_outbox

    async def _poll(
        self,
        outbox: DeliveryOutbox,
        acknowledging: Identifier | None,
        plays: tuple[SpokenAudioFormat, ...],
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Apply the acknowledgement, wait out the budget, then render (ADR-0206 §1).

        The deadline is computed **once**, from this engine's guarded clock, so a
        poll's length is fixed at its start rather than recomputed against a clock
        that may move under it.

        **Measured as elapsed against the span, never as an absolute deadline**
        (ADR-0135 §2): "a poll's remaining wait is its ``budget`` less the time
        elapsed since that poll began", and an implementation "does not compute,
        persist or compare an instant obtained by adding an accepted duration to the
        hub's clock". §1 is what that serves — the budget is honoured whole, and
        neither shortened nor refused because something derived from it will not fit.
        Subtraction never leaves the range a ``timedelta`` can hold.

        **The start is read before the acknowledgement is applied**, so the
        acknowledgement falls inside the budget rather than ahead of it.

        **This runs unshielded, and each mutating step is shielded on its own**
        (ADR-0131 §2a). A poll spends most of its life parked in
        ``wait_for_arrival``, which reads nothing and writes nothing, so a cancel
        there is free — and it is the state a disconnect almost always finds, which
        is why §2a's "cancels the poll and takes no entry" is reachable at all. The
        two steps that *do* mutate — the acknowledgement and the claim — each run
        through :meth:`_uninterruptibly`, so they complete or never start. That is
        the split §2a draws: a close before the selection takes no entry, a close
        during or after it leaves the lease standing.

        """
        started = self._now()
        if acknowledging is not None:
            # Mutating and *pre-selection*, so it takes the same scoped shield the
            # claim does: a cancel arriving mid-retirement would leave the entry
            # dismissed in one store and standing in the other.
            await self._uninterruptibly(outbox.acknowledge(acknowledging))
        while True:
            # Reached **whatever the state of the budget** (ADR-0135 §3): the
            # budget "bounds how long the hub may wait for an entry to become
            # available, and bounds nothing else", so an elapsed one ends the
            # waiting below rather than forbidding this selection.
            #
            # **The one indivisible step, and the only shield this poll needs**
            # (ADR-0131 §2a): selecting an entry, minting its ``delivery_id`` and
            # starting its lease "are one indivisible step… There is no state in
            # which an entry is chosen for a poll and not yet leased." A cancel
            # landing inside it would tear exactly that, so it runs to completion.
            # A cancel arriving *during or after* it therefore leaves the lease
            # standing and the entry returns on expiry — §2a's own second clause,
            # priced there at "one lease, and it is the cost the lease exists to
            # carry".
            delivery = await self._uninterruptibly(outbox.claim())
            if delivery is not None:
                # **The request's own work, and it is not shielded** (ADR-0135 §3,
                # ADR-0206 §7). It runs to completion whatever the state of the
                # budget — a poll that renders answers later than ``budget`` by
                # construction, and an elapsed budget is no ground for degrading —
                # while a *cancellation* still reaches it, which is what makes
                # ADR-0206 §6's cancellation clause true: the lease stands, the
                # entry returns on expiry, and no ``spoken_rendering`` is set.
                return await self._rendered(delivery, plays=plays)
            remaining = budget - _elapsed_since(started, self._now())
            if remaining <= timedelta(0):
                return None
            if not await outbox.wait_for_arrival(remaining):
                # **The wait running out ends the poll, and the deadline alone is
                # not enough to make that true.** A wait is free to return early on
                # an arrival and free to return at once, so a loop that trusted only
                # the clock would re-read, find nothing and ask to wait again — a
                # spin against any positive budget, and an unbounded one wherever
                # the injected clock does not move. The timeout is the one answer
                # the wait can be trusted for, so it is what ends the poll; a wake
                # sends us back for the re-read that correctness actually rests on.
                return None

    async def _rendered(
        self, delivery: NotificationDelivery, *, plays: tuple[SpokenAudioFormat, ...]
    ) -> NotificationDelivery:
        """Speak the summary where ADR-0206 §3 places it, or say why it is unspoken.

        The whole of ADR-0206's rendering, in the order its clauses fall.

        **An empty ``plays`` asks for nothing and gets nothing** (§1). No placement is
        decided, no synthesizer is called, and the delivery is returned exactly as the
        outbox minted it — ``NOT_REQUESTED``, which is
        :class:`~ai_assistant.core.types.NotificationDelivery`'s own default, so a
        caller that cannot play audio meets ADR-0131 §4's poll unchanged.

        **The placement is decided before anything is spent** (§3, §5). A withheld
        candidate calls no synthesizer, and the delivery still travels and is still
        acknowledgeable, with nothing audible marking it — no chime, no tone, no
        spoken notice, and no substitute value of any kind. A withholding is never
        reported as a degradation and is never retried into speech on a later poll,
        because the placement is a property of the candidate and not of the attempt.

        **What is handed to the seam is** ``summary`` **byte for byte** (§4): no
        prefix, no announcement, no salutation, no punctuation added or removed, no
        case folding, no trimming and no second value composed from it. ``detail`` is
        never spoken, on any candidate, under any placement — the page stays strictly
        more informative than the room. It is a
        :data:`~ai_assistant.core.types.NonBlankEncodableText` already, which is
        exactly what ``synthesize`` requires, so nothing here constructs a text at all.

        **The four degradation cases are §6's four and no others**, and in every one
        the delivery travels without the rendering: an empty format intersection,
        discovered *before* the call rather than reported by one and the only one that
        spends nothing; a ``SpeechError`` out of ``synthesize``; a rendering over
        ADR-0200 §6's ``hub_max_spoken_audio_bytes``; and the whole projected delivery
        over ADR-0085 §8c. **An elapsed budget is not among them** (§7) — this stage is
        never handed one and cannot degrade on it — and a synthesis that outlives the
        decorator's own deadline raises ``SpeechTimeoutError``, which is a
        ``SpeechError`` and is the second case.

        **A hub with no synthesizer wired reaches the empty intersection.** ADR-0206 §6
        fixes the four causes; a deployment that composed no speech seams can produce
        no format, so the intersection of ``plays`` with what it can produce is empty
        and this degrades rather than raising. Raising would fail every poll of a
        speech-less hub the moment a caller that *can* play audio asked — losing the
        notification to a deployment choice, which is what ADR-0131 §3's durability and
        §6's "a failure to speak never fails the poll" both refuse.

        **The bound on the synthesis is the composition root's decorator and nothing
        else** (§7). ``synthesize`` is called directly and under no *caller's* budget,
        because this stage has no caller's budget to thread (the spoken turn's helper
        that threaded one left with ``converse_spoken``, ADR-0313 §3:1): ADR-0135 §3
        gives the poll's ``budget`` to the waiting alone.

        **Only ``SpeechError`` is caught** (§6). Every other exception propagates
        unchanged, so a stage that was wholly broken could not report the same
        classified-looking degradation on every call, and a delivered cancellation
        propagates as a cancellation rather than as either outcome.

        Args:
            delivery: What the outbox selected, leased and minted an identifier for.
            plays: The caller's preference order.

        Returns:
            The delivery, carrying the rendering and ``RENDERED``, or carrying none
            and the member naming why.

        Raises:
            Exception: Anything out of ``synthesize`` that is not a ``SpeechError``.
        """
        if not plays:
            return delivery
        if not notification_is_speakable(delivery.notification):
            # Nothing is spent and nothing audible marks it (ADR-0206 §5). The class
            # is logged, never the summary: what a producer wrote is content, and
            # ADR-0199 §2's "no content is read to decide this" is weaker than a rule
            # that also never writes it down.
            _log.info(
                "notification_rendering_withheld",
                producer=delivery.notification.producer,
                notification_class=delivery.notification.notification_class,
            )
            return self._delivery_with(delivery, None, SpokenRendering.WITHHELD)
        rendering = await self._notification_audio(delivery.notification.summary, plays=plays)
        if rendering is None:
            return self._delivery_with(delivery, None, SpokenRendering.DEGRADED)
        spoken = self._delivery_with(delivery, rendering, SpokenRendering.RENDERED)
        try:
            check_payload(
                spoken,
                max_bytes=self._max_payload_bytes,
                subject="the result of next_notification()",
            )
        except OversizedValueError:
            # ADR-0206 §6's fourth case, and it has **no second step**: a delivery
            # carrying no rendering is the value ADR-0131 §4's 256-byte reserve
            # already guarantees fits, so there is nothing further to drop and no
            # re-measurement to make.
            _log.warning("notification_rendering_degraded", reason="over_payload_limit")
            return self._delivery_with(delivery, None, SpokenRendering.DEGRADED)
        return spoken

    async def _notification_audio(
        self, summary: NonBlankEncodableText, *, plays: tuple[SpokenAudioFormat, ...]
    ) -> SpokenAudio | None:
        """Render one summary, or return ``None`` for §6's first three degradations.

        Split from :meth:`_rendered` because the three causes that can be decided
        without the whole delivery in hand are one question — "did the seam give us
        audio we may send?" — and the fourth is a measurement of the value the answer
        goes into. Each of the three is logged with its own reason and none of them
        carries the summary, the seam's message or the audio (ADR-0200 §8).

        Args:
            summary: The candidate's summary, handed to the seam byte for byte.
            plays: The caller's preference order.

        Returns:
            The rendering, or ``None`` where speaking it did not complete.

        Raises:
            Exception: Anything out of ``synthesize`` that is not a ``SpeechError``.
        """
        synthesizer = self._synthesizer
        produces: frozenset[SpokenAudioFormat] = (
            frozenset() if synthesizer is None else synthesizer.formats
        )
        chosen = next((member for member in plays if member in produces), None)
        if synthesizer is None or chosen is None:
            _log.warning("notification_rendering_degraded", reason="no_shared_format")
            return None
        try:
            rendering = await synthesizer.synthesize(summary, format=chosen)
        except SpeechError as exc:
            # The classification is logged; the seam's own message is not, to either
            # tier, on ADR-0200 §8's authorship clause.
            _log.warning(
                "notification_rendering_degraded",
                reason="synthesis_failed",
                failure=classify_speech_failure(exc).value,
            )
            return None
        size = len(rendering.decoded())
        if size > self._max_spoken_audio_bytes:
            _log.warning("notification_rendering_degraded", reason="over_audio_bound", size=size)
            return None
        return rendering

    @staticmethod
    def _delivery_with(
        delivery: NotificationDelivery,
        spoken: SpokenAudio | None,
        rendering: SpokenRendering,
    ) -> NotificationDelivery:
        """Rebuild one delivery around its rendering, through the validator.

        Constructed rather than :meth:`~pydantic.BaseModel.model_copy`-updated, so
        ADR-0206 §6's biconditional is *checked* on every value this path produces
        rather than trusted — ``model_copy`` skips validation, and the one invariant
        worth having here is the one that makes "audio beside a withholding"
        unconstructible.

        Args:
            delivery: What the outbox minted.
            spoken: The rendering, or ``None``.
            rendering: Why it is there or is not.

        Returns:
            The delivery this poll answers with.
        """
        return NotificationDelivery(
            delivery_id=delivery.delivery_id,
            notification=delivery.notification,
            spoken=spoken,
            spoken_rendering=rendering,
        )

    # --- the grant surface (ADR-0102 §1) -----------------------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """Enumerate what the user may grant, with each source's current state.

        Delegated whole to the grant operations (ADR-0102 §7); what this layer adds
        is the drain tracking and the result measurement every read on this surface
        gets. The **one** place a frame size decides whether a source can be granted
        at all is here (ADR-0102 §10): this response carries §6's disclosure, and a
        deployment whose configured path does not fit its configured frame has a
        source it can enumerate nothing about and therefore may not grant, even
        though ``grant``'s own request and result would fit. The blast radius is the
        whole response rather than the one row, because ADR-0085 §8c bounds the
        *payload*; raising ``hub_max_frame_bytes`` is the operator's remedy and the
        only one offered.

        Raises:
            RuntimeError: If the engine is shutting down.
            GrantError: If the grant store cannot be read.
            OversizedValueError: If the enumeration does not fit the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            self._grants.grantable_sources(), "grantable_sources", checked=True
        )

    async def grant(
        self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
    ) -> SourceGrant:
        """Record the user's grant of one source for the uses ``scope`` names.

        **Argument validation happens here and admission happens below**, in that
        order, and neither substitutes for the other (ADR-0102 §4). ``source`` is
        refused blank or unwritable and **normalised by nothing** — the whole point
        of :data:`~ai_assistant.core.types.NonBlankEncodableText` on this argument
        (ADR-0102 §2) — and ``scope`` is materialised before the first ``await`` and
        refused empty, duplicated, or naming ``INGEST`` (ADR-0294 §4). All are local
        refusals before any I/O (ADR-0085 §9), so a wire client refuses exactly what
        this refuses.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``source`` is blank or unwritable, or ``scope`` is empty,
                names a use twice, or names ``INGEST``.
            TypeError: If a ``scope`` member is not a ``GrantScope``.
            UngrantableSourceError: If the validated source is not admissible.
            GrantError: If the store cannot be read or written.
            InvalidGrantError: If the store refused the record.
            OversizedValueError: If the arguments or the record exceed the limit.
        """
        self._reject_if_closing()
        named = non_blank_text(source, name="source")
        uses = grant_scope(scope, name="scope")
        check_arguments("grant", max_bytes=self._max_payload_bytes, source=named, scope=uses)
        return await self._tracked(self._grants.grant(named, scope=uses), "grant", checked=True)

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Withdraw the live grant on one source, or report that there was none.

        **No admission check, deliberately** (ADR-0102 §4): revocation is the user's
        whole remedy under ADR-0097 §6, and a check here would make a grant whose
        reader was later unconfigured permanently unrevokable. Only the argument
        validation above applies.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``source`` is blank or unwritable.
            GrantError: If the store cannot be read or written.
            InvalidGrantError: If the store refused the revoking record.
            OversizedValueError: If the argument or the record exceeds the limit.
        """
        self._reject_if_closing()
        named = non_blank_text(source, name="source")
        check_arguments("revoke", max_bytes=self._max_payload_bytes, source=named)
        return await self._tracked(self._grants.revoke(named), "revoke", checked=True)

    async def recent_grants(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceGrant, ...]:
        """List what the user granted and withdrew, newest first (ADR-0097 §6).

        ``limit`` is refused when it is **not strictly positive**, which is stricter
        than every other paging method on this surface and is ADR-0102 §10's own
        clause: ADR-0085 §9 admits ``[0, 2**63)`` and ``SourceGrantStore.recent``
        requires a positive limit, so ``limit=0`` is well-formed under the surface
        rule and refused by the store — and §9 forbids either implementation from
        being silently more permissive than the other.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            GrantError: If the store cannot be read.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_grants", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            self._grants.recent_grants(limit=limit), "recent_grants", checked=True
        )

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """List every grant the user currently authorises (ADR-0139 §2).

        Delegated whole to the grant operations; what this layer adds is the drain
        tracking and the result measurement, as it does for every other read here.

        **The measurement is the operation's distinguishing property, not
        boilerplate.** ADR-0139 §2 refuses a paged answer — a page of what you
        authorise reads as complete while omitting an authorisation — so a live set
        that does not fit the frame is an ``OversizedValueError`` and no set at
        all. An implementation that returned the store's result unmeasured would
        pass every membership, revocation and corrupt-store case and fail only at a
        size no ordinary test constructs. ``hub_max_frame_bytes`` is the operator's
        remedy and the only one offered, exactly as for ``grantable_sources``; a
        frame too small to list what you authorise still lets you withdraw what you
        know about, because ``revoke``'s request and result are two small values
        (ADR-0102 §10).

        Raises:
            RuntimeError: If the engine is shutting down.
            GrantError: If the grant store cannot be read, or holds two live grants
                for one source.
            OversizedValueError: If the live set does not fit the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(self._grants.standing_grants(), "standing_grants", checked=True)

    # --- the connection surface (ADR-0151 §1) -------------------------------

    async def connect_account(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account under a reference the provisioner mints.

        **Three local refusals before any I/O, in this order** (ADR-0085 §9,
        ADR-0151 §5): the credential is revalidated through ``secret_value``
        because :data:`~ai_assistant.core.types.SecretValue` is an ``Annotated``
        alias whose validator never runs on a directly-constructed ``SecretStr``
        (ADR-0125 §4); the identity is refused blank or unwritable and
        **normalised by nothing**; and it is then refused unusable — oversized,
        carrying a control character or a line break, or **equal to the
        credential's plaintext**. A wire client refuses exactly what this refuses,
        so no such call reaches the hub and no credential is sent for one.

        **The size check measures the identity and not the credential.** ADR-0151
        §11 requires the whole argument payload to fit the configured frame, and
        the credential is part of it — but a payload measurement projects its
        members, and ``project`` has no form for a ``SecretStr`` at all (ADR-0151
        §6), which is exactly the property that stops a redaction being sent as a
        secret. So the credential's own bound is
        :data:`~ai_assistant.core.types.SECRET_VALUE_MAX_BYTES`, enforced by
        ``secret_value`` above, and what is measured here is everything else. The
        hub-side consequence is stated rather than hidden: a maximal credential
        does not fit a 1024-byte frame, and the client is where that call is
        refused, because it is the client that serialises.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``identity`` is blank or unwritable, or ``credential``
                is blank, unencodable or oversized.
            UnusableIdentityError: If ``identity`` is one ADR-0149 §4 does not
                admit. Nothing is written and no credential is sent.
            IncompleteProvisioningError: If the act's first write returned and the
                act did not complete. Carries the minted reference.
            ProvisioningOutcomeUnknownError: If the activation failed rather than
                returning. Carries the reference; the outcome is not known.
            ConnectionStoreError: If the act's first write did not return. Carries
                no reference, and the outcome is not known.
            OversizedValueError: If the arguments or the record exceed the limit.
        """
        self._reject_if_closing()
        secret = secret_value(credential)
        named = non_blank_text(identity, name="identity")
        # **One call, one read of the plaintext** (ADR-0151 §5, §11). §5's exact
        # comparison against the identity and §11's frame measurement need the same
        # value, and `orchestration` holds it once: a second helper would give this
        # package two plaintext-handling sites where §5 obliges one.
        check_provisioning_call(
            "connect_account",
            max_bytes=self._max_payload_bytes,
            identity=named,
            credential=secret,
        )
        return await self._tracked(
            self._connections.connect(identity=named, credential=secret),
            "connect_account",
            checked=True,
            traced=False,
        )

    async def reprovision_account(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under a reference this hub previously returned.

        :meth:`connect_account`'s three local refusals, plus ``reference``, which
        is validated and **normalised** as every id argument on this surface is
        (ADR-0085 §3c): a reference is a minted id no user authors, so the
        strengthening is harmless where nothing was typed, and a client comparing
        values of the same type is what §3c buys. The store then compares it
        exactly (ADR-0151 §3).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``reference`` is blank or unwritable, ``identity`` is
                blank or unwritable, or ``credential`` is blank, unencodable or
                oversized.
            UnusableIdentityError: On :meth:`connect_account`'s terms.
            UnknownConnectionError: If the store holds no entry for ``reference``.
            DisplacedProvisioningError: If another act took the record over.
            IncompleteProvisioningError: On :meth:`connect_account`'s terms.
            ProvisioningOutcomeUnknownError: On :meth:`connect_account`'s terms.
            ResidualCredentialError: If the predecessor-slot deletion failed after
                the activation landed. The act **completed**.
            ConnectionStoreError: On :meth:`connect_account`'s terms.
            OversizedValueError: If the arguments or the record exceed the limit.
        """
        self._reject_if_closing()
        secret = secret_value(credential)
        handle = identifier(reference, name="reference")
        named = non_blank_text(identity, name="identity")
        check_provisioning_call(
            "reprovision_account",
            max_bytes=self._max_payload_bytes,
            identity=named,
            credential=secret,
            reference=handle,
        )
        return await self._tracked(
            self._connections.reprovision(handle, identity=named, credential=secret),
            "reprovision_account",
            checked=True,
            traced=False,
        )

    async def connect_keyless_account(self, *, identity: NonBlankEncodableText) -> ConnectedAccount:
        """Connect a source that needs no credential, under a reference the provisioner mints.

        **Two local refusals before any I/O, in this order** (ADR-0325 §4:3,
        ADR-0085 §9): the identity is refused blank or unwritable and **normalised by
        nothing**, and it is then refused unusable — oversized, or carrying a control
        character or a line break — before the argument is measured against the
        frame. A wire client refuses exactly what this refuses, so no such call
        reaches the hub.

        Untraced, for :meth:`connect_account`'s reason: a trace would put an instant
        on the owner's act through a door ADR-0151 §18 keeps shut.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``identity`` is blank or unwritable.
            UnusableIdentityError: If ``identity`` is one ADR-0149 §4 does not
                admit. Nothing is written.
            ConnectionStoreError: If the act's one write did not return. Carries no
                reference, and the outcome is not known (ADR-0325 §3:6).
            OversizedValueError: If the argument or the record exceeds the limit.
        """
        self._reject_if_closing()
        named = non_blank_text(identity, name="identity")
        check_keyless_call(
            "connect_keyless_account", max_bytes=self._max_payload_bytes, identity=named
        )
        return await self._tracked(
            self._connections.connect_keyless(identity=named),
            "connect_keyless_account",
            checked=True,
            traced=False,
        )

    async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None:
        """Disconnect a reference, or report that there was no live record.

        A ``None`` is **not** a report of a disconnection (ADR-0151 §8): it says
        one thing, that no live record was removed by this call, and it covers
        both a reference the store has never held and one already disconnected.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``reference`` is blank or unwritable.
            ResidualCredentialError: If the removal entry landed and a credential
                deletion did not. The reference **is** disconnected.
            ConnectionStoreError: If the store cannot be read or written.
            OversizedValueError: If the argument or the record exceeds the limit.
        """
        self._reject_if_closing()
        handle = identifier(reference, name="reference")
        check_arguments("disconnect_account", max_bytes=self._max_payload_bytes, reference=handle)
        return await self._tracked(
            self._connections.disconnect(handle), "disconnect_account", checked=True, traced=False
        )

    async def connected_accounts(self) -> tuple[ConnectedAccount, ...]:
        """List every connection that has a live record, pending ones included.

        **The measurement is the operation's distinguishing property, not
        boilerplate**, exactly as for ``standing_grants``. ADR-0151 §9 refuses a
        paged answer — a truncated answer to "what is connected" is a false one
        rather than a partial one — so a live set that does not fit the frame is
        an ``OversizedValueError`` and no set at all. ``hub_max_frame_bytes`` is
        the operator's remedy and the only one offered; a frame too small to list
        what is connected still lets a reference be disconnected, because
        ``disconnect_account``'s request and result are two small values.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
            OversizedValueError: If the live set does not fit the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            self._connections.connected(), "connected_accounts", checked=True, traced=False
        )

    async def recent_connection_acts(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[ConnectionAct, ...]:
        """List what was done to connections, newest first (ADR-0151 §9).

        ``limit`` is refused when it is **not strictly positive**, on
        ``recent_grants``' reason and in every implementation (ADR-0151 §2a), so
        neither is silently more permissive than the other.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            ConnectionStoreError: If the store cannot be read, or holds an entry
                that no longer validates.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_connection_acts", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            self._connections.recent_acts(limit=limit),
            "recent_connection_acts",
            checked=True,
            traced=False,
        )

    # --- the audit trail's two reads (ADR-0186 §1) --------------------------

    async def recent_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """List what the permission layer ruled, newest first (ADR-0186 §1).

        ``limit`` is refused when it is **not strictly positive**, on
        ``recent_grants``' reason and in every implementation (ADR-0186 §3), so
        neither is silently more permissive than the other: ``AuditTrail.recent``
        refuses zero and ADR-0085 §9 would admit it.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            AuditError: If the trail cannot be read.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_decisions", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            _ordered_decisions(self._trail.recent(limit=limit)),
            "recent_decisions",
            checked=True,
        )

    async def export_decisions(self) -> tuple[PermissionDecision, ...]:
        """Return every recorded decision, in ``recent_decisions``' order (ADR-0186 §1).

        Takes no argument and pages nothing: it is the unbounded read ADR-0021 §4
        keeps distinct from the listing, and the surface discharging ADR-0004 §6's
        portability obligation for this store. A trail too large for the frame is an
        ``OversizedValueError`` and no artifact at all — the measurement ``_tracked``
        already applies to every result, which is the whole of what stops a partial
        export being handed back as a complete one.

        Raises:
            RuntimeError: If the engine is shutting down.
            AuditError: If the trail cannot be read.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            _ordered_decisions(self._trail.export()),
            "export_decisions",
            checked=True,
        )

    # --- the read trail's two reads (ADR-0186 §10) -------------------------

    async def recent_reads(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceReadRecord, ...]:
        """List what this system read from a source, newest-recorded first.

        Relays :meth:`SourceReadTrail.recent` **untouched**, which is the whole of
        the implementation: that method already promises this order (ADR-0185 §6),
        and ADR-0186 §10 binds the pair to one order rather than to §2's key. There
        is nothing here to sort — see :func:`_newest_recorded_first` for why sorting
        these rows is unavailable rather than merely unnecessary.

        ``limit`` is refused when it is **not strictly positive**, on
        ``recent_decisions``' reason and in every implementation (ADR-0186 §3, §10).

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            ReadTrailError: If the trail cannot be read.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_reads", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            _as_tuple(self._reads.recent(limit=limit)),
            "recent_reads",
            checked=True,
        )

    async def export_reads(self) -> tuple[SourceReadRecord, ...]:
        """Return every read attempt the trail still holds, in ``recent_reads``' order.

        **Reversed rather than relayed**, because the store's ``export`` is in
        recording order and the listing is its reverse — without that,
        ADR-0186 §2's prefix property would be false across this pair.

        **The horizon, not the history** (ADR-0185 §9, §10): the store prunes
        oldest-first at ``source_read_trail_max_rows``, so this returns every
        attempt still held and no lane reports it as a complete history. A trail too
        large for the frame is an ``OversizedValueError`` and no artifact at all —
        the measurement ``_tracked`` already applies to every result.

        Raises:
            RuntimeError: If the engine is shutting down.
            ReadTrailError: If the trail cannot be read.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            _newest_recorded_first(self._reads.export()),
            "export_reads",
            checked=True,
        )

    # --- the trail's two invocation reads (ADR-0192 §4) --------------------

    async def recent_invocations(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecordedInvocation, ...]:
        """List what this system did on an authorisation, newest first (ADR-0192 §4).

        A **relay** over the trail's joined listing, and it stays one because the
        join is the store's: the tool's identity lives on the decision, and an
        engine reading rows and then reading decisions would have an ``await``
        between the two that a ``clear()`` can land in (ADR-0192 §2).

        ``limit`` is refused when it is **not strictly positive**, on
        ``recent_decisions``' reason and in every implementation (ADR-0192 §4), so
        neither is silently more permissive than the other:
        ``AuditTrail.recent_invocations`` refuses zero and ADR-0085 §9 would admit
        it.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            AuditError: If the trail cannot be read, or holds a row it could not
                pair with the decision that row names.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_invocations", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            _ordered_invocations(self._trail.recent_invocations(limit=limit)),
            "recent_invocations",
            checked=True,
        )

    async def export_invocations(self) -> tuple[RecordedInvocation, ...]:
        """Return every invocation row, in ``recent_invocations``' order (ADR-0192 §4).

        Takes no argument and pages nothing: it is the unbounded read that
        discharges ADR-0004 §6's portability obligation for **this row kind**, which
        ``export_decisions`` does for the decision rows and, after ADR-0192 §2, for
        those alone. A trail too large for the frame is an ``OversizedValueError``
        and no artifact at all — the measurement ``_tracked`` already applies to
        every result, which is the whole of what stops a partial export being handed
        back as a complete one.

        Raises:
            RuntimeError: If the engine is shutting down.
            AuditError: If the trail cannot be read, or holds a row it could not
                pair with the decision that row names.
            OversizedValueError: If the whole trail exceeds the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            _ordered_invocations(self._trail.export_invocations()),
            "export_invocations",
            checked=True,
        )

    # --- what the world has cost (ADR-0194 §6) -----------------------------

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Relay the ledger's two period totals, unchanged (ADR-0194 §6).

        It **relays**: no composition, no reordering and no second source. The
        ledger derives both entries from one reading of the clock and one snapshot
        of the rows, so anything this frame did between two reads of its own would
        be the incoherence ADR-0194 §5 forbids, reintroduced one layer up.

        The engine holds a ``SpendLedger`` and never a ``SpendGate``, so there is no
        route from any adapter to an admission (ADR-0194 §5).

        Raises:
            RuntimeError: If the engine is shutting down.
            SpendUndeterminedError: If the ledger cannot produce the values at all —
                a failed store read or a raising clock. An indeterminate *period* is
                returned rather than raised (ADR-0194 §5).
            OversizedValueError: If the pair exceeds the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(self._spend.spend_totals(), "spend_totals", checked=True)

    async def aclose(self) -> None:
        """Stop accepting work, drain what is in flight, then close owned resources.

        The shutdown path ADR-0042 §2 requires of a long-lived owner. It is
        **ordered, not abrupt**, because the concrete stores are connection-owning
        and each ``close()`` closes its connection directly without serialising
        against an in-flight operation — so nothing below the façade prevents a
        ``close()`` racing a store call still touching the connection; that
        ordering has to be the façade's (ADR-0042 §2).

        So this (a) stops accepting new calls, then (b) drains every tracked
        operation to quiescence before closing — waiting for it to finish on its
        own for ``drain_timeout``, then cancelling what is left and awaiting
        *that* to completion (ADR-0083 §4; :meth:`_drain_and_close`). Both phases
        end in quiescence, which is what ADR-0042 §2 requires; the budget only
        decides whether the remaining work is asked to stop. The tracking is of the underlying
        work itself, not merely the public call: a client cancelling its own call
        mid-call abandons the awaiting coroutine but not the work it started, which
        keeps using the connection a subsequent ``close()`` would shut. Each public
        call therefore runs as a **shielded** task this engine holds a reference to,
        so cancelling the caller leaves the underlying task running and tracked, and
        this drain still awaits it. Only then are the
        owned resources closed, in the order the composition root handed them.

        **The drain-and-close is one memoised task, and every caller awaits it
        shielded.** So cancelling *this* ``aclose`` — not only a public call —
        cannot abandon the closures half-done: the shutdown task keeps running to
        completion, and a subsequent ``aclose`` awaits the same task rather than
        returning early over resources that were never closed (ADR-0042 §2). This
        is what makes ``aclose`` idempotent *and* cancellation-safe; the closers
        run exactly once.
        """
        self._closing = True  # stop accepting new work at once (§2)
        if self._chat_reader is not None:
            # ADR-0332 §5:1: a start wait under way ends now, and takes nothing in.
            self._chat_reader.close()
        if self._telegram_reader is not None:
            # ADR-0323 §11:11: a poll the line holds open ends now, its record unknown;
            # an activation it runs is drained as any other.
            self._telegram_reader.close()
        if self._task_sensor is not None:
            # ADR-0350 §7:1: the sensor stops with the hub; what it admitted is drained.
            self._task_sensor.close()
        if self._approvals_sensor is not None:
            # ADR-0361 §3:4: the Approvals channel's sensor stops with the hub too.
            self._approvals_sensor.close()
        if self._shutdown is None:
            self._shutdown = asyncio.ensure_future(self._drain_and_close())
        await asyncio.shield(self._shutdown)

    async def _drain_and_close(self) -> None:
        """Drain every tracked operation, then close owned resources in order.

        The body of shutdown, run as one retained task so no caller's cancellation
        can leave it half-done (:meth:`aclose`). A tracked task orphaned by a
        cancelled call is still using a connection ``close()`` would shut, so
        **nothing is closed until every tracked task has completed** — which is
        ADR-0042 §2's requirement and is what both phases below end in.

        **Every closer is attempted, even after one fails — including on
        cancellation.** ADR-0042 §2 requires the façade to release *every* owned
        connection on shutdown, so a closer that raises, or is cancelled (a
        ``CancelledError``, which is a ``BaseException`` and not an ``Exception``),
        must not skip the ones after it — a leaked connection is the exact failure
        the ordered close exists to prevent. Ordinary failures are collected and
        re-raised together once every resource has had its close attempted; a
        cancellation is re-raised after the same best-effort sweep, so it still
        propagates but not before the remaining resources are released.

        Raises:
            CancelledError: If closing a resource was cancelled. Re-raised after
                every remaining closer has been attempted.
            ExceptionGroup: If one or more closers raised (and none was cancelled).
                Every closer was still attempted; the group carries each failure.
        """
        # ADR-0298 §7: every open change stream is woken to send its end, and given a
        # moment to be closed by its reader, before the drain — so a hub that closes
        # its listeners once the engine is closed has written each stream's end first.
        await self._change_stream.close()
        await self._drain()
        errors: list[Exception] = []
        cancelled: asyncio.CancelledError | None = None
        for close in self._closers:
            try:
                await close()
            except asyncio.CancelledError as exc:  # sweep the rest, then propagate
                cancelled = exc
            except Exception as exc:  # every resource must still get its close attempt
                errors.append(exc)
        if cancelled is not None:
            if errors:
                _log.error(
                    "resource_close_failed_during_shutdown_cancellation",
                    failures=[str(exc) for exc in errors],
                )
            raise cancelled
        if errors:
            raise ExceptionGroup("one or more resources failed to close on shutdown", errors)

    async def _drain(self) -> None:
        """Bring the tracked set to quiescence: wait, then cancel, then wait again.

        ADR-0083 §4's two phases, and the shape is decided rather than incidental.

        **Phase A is bounded** at ``drain_timeout``, and the bound is what keeps
        the graceful path reachable at all. Under a supervisor with a stop
        timeout, an unbounded wait ends in ``SIGKILL`` — which destroys exactly
        the ADR-0029 §4 bookkeeping the drain exists to preserve, committed under
        a shield so that "a shutdown that stops waiting politely" cannot leave a
        claimed call with its outcome unwritten.

        **Phase B cancels what is left and then awaits it, unbounded.** Three
        things make that safe, and each is load-bearing:

        * **Cancelling is not abandoning.** ADR-0054 makes a cancelled store call
          keep its connection until its worker thread physically finishes and
          re-raise only then, uniformly across all seven stores. So a cancelled
          task's ``CancelledError`` arrives *after* the connection is free, and
          awaiting it is still ADR-0042 §2's "awaits every tracked underlying
          operation to quiescence… before closing", satisfied literally.
        * **Cancelling is what preserves the bookkeeping**, not what loses it: a
          cancelled step still records why it ended (ADR-0029 §4), a ``SIGKILL``ed
          one does not.
        * **Bounding phase B is the one thing that must not be done.** Its only
          termination-forcing alternative is abandonment, and an abandoned store
          call is a worker thread holding a connection the very next statement
          closes — ADR-0054's bug, deliberately re-created. If phase B ever
          outlives the supervisor's stop timeout then ``SIGKILL`` is the correct
          outcome and is strictly safer: SQLite recovers a journal on next open,
          and has no recovery for a connection closed under a running statement.

        ADR-0060 §1 permits the unbounded tail and permits it for this reason —
        the deadline is one this object issues *itself*, so it is its own control
        flow, and the wait is on work that is observably completing. It is the
        "documented as unbounded" form that clause names, and this is where it is
        documented.

        With no budget (``drain_timeout=None``) there is no phase B: the wait is
        the whole drain, which is what this façade did before ADR-0083.
        """
        pending = set(self._inflight)
        # Recorded before anything is awaited, and narrowed only if phase B is
        # actually entered, so the hub's completion event (#559) is accurate at
        # every point a reader could reach it — including a shutdown that raised in
        # a closer after the drain, which is exactly when an operator wants to know
        # whether work had been cancelled.
        self._drain_phase = DrainPhase.QUIESCED
        if not pending:
            return
        if self._drain_timeout is None:
            await asyncio.gather(*pending, return_exceptions=True)
            return
        # Phase A. `asyncio.wait` returns rather than raising on the timeout, and
        # hands back precisely the set still running — no task is disturbed by the
        # budget merely elapsing, which is what makes the two phases separable.
        _finished, pending = await asyncio.wait(
            pending, timeout=self._drain_timeout.total_seconds()
        )
        if not pending:
            return
        # Phase B. Logged before cancelling: this is the moment a deployment's stop
        # timeout is being spent, so an operator reading the journal after a
        # SIGKILL can see that the drain had reached its budget and was cancelling.
        self._drain_phase = DrainPhase.CANCELLED
        # Safety children are awaited with their owners, but direct cancellation
        # would bypass the owner's shield and abandon deletion compensation.
        cancellable = pending - self._capture_safety
        _log.info("shutdown_drain_budget_exceeded", cancelling=len(cancellable))
        for task in cancellable:
            task.cancel()
        # Unbounded, and `return_exceptions=True` so a cancelled task's
        # `CancelledError` is a *result* here rather than something that aborts the
        # gather and skips its siblings. Every one must complete before a closer runs.
        await asyncio.gather(*pending, return_exceptions=True)

    def _register_capture(self, task: asyncio.Task[None]) -> None:
        """Keep ordinary and safety cleanup in the same shutdown registry as work."""
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    def _register_capture_safety(self, task: asyncio.Task[None]) -> None:
        """Track deletion cleanup without letting shutdown cancel it directly."""
        self._capture_safety.add(task)
        task.add_done_callback(self._capture_safety.discard)
        self._register_capture(task)

    def _spawn_read(self, read: Coroutine[None, None, None]) -> None:
        """Start one of the chat reader's reads as work this engine tracks (ADR-0293 §6).

        In a context of its own, so neither the correlation scope nor the activation
        of the call that noticed the message is inherited by the read; tracked like
        every other task here, so :meth:`aclose` drains it (ADR-0042 §2).

        **Nor the requesting device** (ADR-0298 §2:6): the activation a message starts
        outlives the ``write_message`` that started it, so it runs with the requesting
        device unset — the hub's own machine — and the assistant's own work is never
        checked as the device that wrote the message. The fresh context is what unsets
        it, so :mod:`ai_assistant.core.device_context` needs no unsetter.
        """
        task = asyncio.get_running_loop().create_task(read, context=contextvars.Context())
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    def _chat_activation_id(self) -> str:
        """Mint the id a reader's input is marked taken in by, and admitted with (§6:6).

        The engine's own activation id factory. One whose reading is not canonical
        UUID4 text would leave the activation's capture degraded with no id (ADR-0275
        §2), and a message the reader marks must name the activation that took it in,
        so a fresh UUID4 stands in, logged as the degradation it is.
        """
        try:
            minted = self._activation_id_factory()
            parsed = uuid.UUID(minted)
            if parsed.version == 4 and str(parsed) == minted:  # noqa: PLR2004 — mandated UUID version
                return minted
        except Exception:
            _log.warning("activation_capture_degraded", stage="chat_reader", reason="identifier")
            return _uuid()
        _log.warning("activation_capture_degraded", stage="chat_reader", reason="identifier")
        return _uuid()

    async def _read_in(self, taken: ChatInput) -> bool:
        """Admit the activation for the reader's input, then write what it ends with.

        The input is admitted as a typed message on the conversation channel, with the
        id the reader minted, and its **first step, once its episode is written, marks
        the messages taken in** under that id (ADR-0293 §6:8): so whatever cancels it, a
        shutdown included, leaves an episode closed interrupted, and its messages are
        either marked by it or still waiting (§6:9). It then runs as a typed turn of a
        bounded audience — the conversation's own devices — with the reader's window as
        its channel window (§6:4). What it ends with is written into the conversation
        it came from by the adapter: the reply, or *couldn't finish* listing what did
        happen (§10:1, §10:2). An activation that marked nothing — a store that refused
        the marking, or messages gone since they were read — did nothing, and nothing
        is written for it.

        **A shutdown that cancels it writes nothing** (§9:2): the cancellation is
        re-raised before the adapter is reached, the activation's episode is closed
        interrupted, and the conversation's state reads *interrupted* (§8:3).

        **Nor does a stop** (ADR-0295 §3:3, ADR-0297 §4): the pass ends with the stop's
        end entry, the awaited task raises ``ActivationStoppedError``, nothing is
        written, and the conversation's state reads *stopped*.

        Returns:
            Whether the activation marked anything taken in; ``False`` too where the
            engine was already closing, and nothing was admitted. Whatever else runs,
            on this conversation or any other, it is admitted (ADR-0349 §8:1).

        Raises:
            CancelledError: If the activation, or this read, was cancelled.
        """
        reader = self._chat_reader
        assert reader is not None  # noqa: S101 — only the reader calls this
        place = ChannelIdentity(channel_type="conversation", instance_id=taken.conversation_id)
        if self._closing:
            return False
        accepted = ChannelInput(target=place, payload=TextChannelPayload(text=taken.text))
        state = admit_channel(
            accepted,
            WholeTextReply(),
            clock=self._now,
            id_factory=lambda: taken.activation_id,
            stage_limit=self._stage_record_limit,
        )
        marked: list[int] = []

        async def turn() -> None:
            try:
                await reader.take_in(taken, into=marked)
                if not marked:
                    raise _NothingTakenInError
                # §6:6: the pass runs on what it took in alone. A message read as
                # waiting and not marked — deleted, or taken in elsewhere, in between —
                # reaches no stage. The episode keeps the text the activation was
                # admitted with: an open episode is only ever extended (ADR-0286 §3:4,
                # §12:2), and what an episode records is never kept in step with the
                # transcript (ADR-0293 §5:5).
                await self._chat_input_turn(taken.narrowed(marked))
            except Exception:
                # §9:1, §10:2: what was marked is consumed, so its failure is written.
                # Once the phases' run has begun, the controller holding the pass's
                # working set on the state, the run writes it (ADR-0307 §3:7); a failure
                # before then, such as a marking that failed part way, is written here,
                # inside the activation, as the run would have written it (#2900).
                if marked and state.working is None and self._phases is not None:
                    await self._phases.unbegun(
                        activation_id=taken.activation_id,
                        conversation_id=taken.conversation_id,
                        state=state,
                    )
                raise

        deadline = asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()
        task = self._activation_task(
            ActivationScope(state),
            turn,
            seam="chat_reader",
            check_output=_unchecked,
            deadline=deadline,
        )
        try:
            await task
        except asyncio.CancelledError:
            raise
        except ActivationStoppedError:
            # ADR-0295 §3:3, ADR-0297 §4: a stopped activation writes nothing into the
            # conversation — no reply, even one already composed, no *couldn't finish*
            # and no message saying it stopped. What it marked is taken in; what waited
            # meanwhile is taken in by the reader's next look, as after any activation
            # (ADR-0295 §3:6).
            return bool(marked)
        except Exception as failure:  # every failure of the pass is §10:2's ending
            _log_chat_failure(failure, state=state, marked=bool(marked))
            if not marked:
                return False
        # The phases wrote every message the pass owed while it ran, the *couldn't
        # finish* message included (ADR-0307 §3), so nothing is written here.
        return True

    async def _stop_line(self, activation_id: str) -> bool:
        """Stop one activation running from the line's chat, for its ``/stop`` (ADR-0332 §8:4).

        The reader calls it for each one running (ADR-0349 §4:3).

        As :meth:`stop_activation` stops one (ADR-0295, ADR-0297): the mark, then the
        stop record. A record that cannot be written leaves the mark set (ADR-0297 §3:7),
        so the activation is stopped all the same.

        Returns:
            Whether it stopped one: ``False`` where it had already ended.
        """
        try:
            return await self._stop(activation_id) is ActivationStop.STOPPED
        except PlanningError:
            _log.warning("telegram_stop_unrecorded", stage="telegram_reader", reason="store_failed")
            return True
        except MemoryStoreError:
            # Not running: only then is the episode read, so nothing was stopped.
            return False

    async def _chat_input_turn(self, taken: ChatInput) -> None:
        """The reader's input, planned by the phases (ADR-0309 §2:6)."""
        await self._phases_turn(taken)

    async def _line_read_in(self, taken: TelegramInput) -> bool:
        """Admit the activation for the Telegram line's input (ADR-0323 §5, §6).

        As :meth:`_read_in` admits the hub chat's: the input is admitted as a typed
        message on the line's channel, with the id the reader minted and each message
        it took in recorded on the trigger, dated, a forward with its original sender
        (§4:10, §5:4) — so an input taking one in is admitted with the origin the kind
        declares for it (§4:11). Its **first step, once its episode is written, marks
        the updates taken in** on the line's intake record (§5:8, ADR-0293 §6:8), so
        whatever cancels it leaves its updates either marked by it or never taken in
        (§5:10). It then runs as a typed turn of a bounded audience — the line is
        private (§9:6) — with the line's episode window as its channel window (§10),
        and the phases write its messages into the line's chat through the line's
        writer alone (§6:1, §11:3). A shutdown that cancels it, and a stop, write
        nothing (ADR-0295 §3:3); the restart's message is the reader's (§6:10).

        Returns:
            Whether the activation marked anything taken in; ``False`` too where the
            engine was already closing, and nothing was admitted. Whatever else runs,
            on the line's chat or any other place, it is admitted (ADR-0349 §8:1).

        Raises:
            CancelledError: If the activation, or this read, was cancelled.
        """
        reader = self._telegram_reader
        writer = self._telegram_writer
        assert reader is not None  # noqa: S101 — only the line's reader calls this
        assert writer is not None  # noqa: S101 — wired with the reader
        if self._closing:
            return False
        accepted = ChannelInput(target=taken.channel, payload=TextChannelPayload(text=taken.text))
        state = admit_channel(
            accepted,
            WholeTextReply(),
            clock=self._now,
            id_factory=lambda: taken.activation_id,
            stage_limit=self._stage_record_limit,
            messages=taken.recorded,
        )
        target = PlaceTarget(channel=taken.channel, writer=writer.for_place(taken.channel))
        marked: list[int] = []

        async def turn() -> None:
            try:
                await reader.take_in(taken, into=marked)
                if not marked:
                    raise _NothingTakenInError
                # §5:9: the pass runs on what it took in alone.
                await self._line_turn(taken.narrowed(marked), target)
            except Exception:
                # As the chat's: what was marked is consumed, so a failure before the
                # phases' run began writes *couldn't finish* here (ADR-0317 §3:3).
                if marked and state.working is None and self._phases is not None:
                    await self._phases.unbegun(
                        activation_id=taken.activation_id,
                        state=state,
                        target=target,
                        description=TELEGRAM.description,
                    )
                raise

        deadline = asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()
        task = self._activation_task(
            ActivationScope(state),
            turn,
            seam="telegram_reader",
            check_output=_unchecked,
            deadline=deadline,
        )
        try:
            await task
        except asyncio.CancelledError:
            raise
        except ActivationStoppedError:
            # ADR-0295 §3:3: a stopped activation writes nothing new into the chat.
            return bool(marked)
        except Exception as failure:  # every failure of the pass is §10:2's ending
            _log_chat_failure(failure, state=state, marked=bool(marked), reader="telegram")
            if not marked:
                return False
        return True

    async def _line_turn(self, taken: TelegramInput, target: PlaceTarget) -> None:
        """The line's input, planned by the phases (ADR-0309 §2:6, ADR-0323 §15).

        A turn as the hub chat's is, its input already resolved to the line's channel
        — the line's chat is no conversation the lifecycle begins (§2:5) — so the
        controller runs the windows, recall, understanding and the story links, then
        recall's second run and the four phase stages. The working set's place is the
        line's chat, its messages go through the line's writer, its window is the
        line's episode window (§10), and a yes it carries is given through the line
        (§4:9).
        """
        phases = self._phases
        assert phases is not None  # noqa: S101 — the line is wired only beside them
        state = active_state()
        trigger = None if state is None else state.trigger
        if state is not None and trigger is not None:
            # ADR-0349 §5:3, §7:5: who handed the input in, which the in-progress
            # section, an absorption and an offer read: the line's kind establishes the
            # user as the author of every message it takes in, a forward's included, who
            # forwarded it, and a forward's party is its original sender, claimed
            # (ADR-0351 §4:2, §2:7), so its parties carry no authority (§6:1).
            state.input_messages = taken.recorded
            state.standing = input_standing(parties=trigger.parties, established=True)
        resolved = ResolvedChannelInput(
            channel=taken.channel,
            text=taken.text,
            modality=Modality.TEXT,
            context=_EMPTY_CHANNEL_CONTEXT,
        )
        working = _TurnPass(
            utterance=taken.text,
            requested=None,
            context=_EMPTY_CHANNEL_CONTEXT,
            deadline=(asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()),
            # ADR-0323 §9:6: the line is private, declared by setting it up, so a
            # record placed for the owner alone may be shown (ADR-0307 §6:4).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            transcript=taken.window,
            understanding_wired=self._understanding is not None,
            recall_wired=self._recall is not None,
            story_links_wired=self._story_links is not None,
            phases=phases.begin_line(
                activation_id=taken.activation_id,
                window=taken.window,
                target=target,
                description=TELEGRAM.description,
                giver=LINE_GIVER,
                trigger=trigger,
                owner_records=True,
            ),
            input=resolved,
            activation=state,
        )
        if working.phases is not None:
            # ADR-0350 §3:4: a person's activation on the line is offered spawn.
            working.phases.scheduling = self._scheduling(state, taken.channel)
        stages: list[ControllerStageRun[_TurnPass]] = [
            Stage(ControllerStage.WINDOWS, self._windows_stage, expired=_windows_expired),
            phases.recall_stage(
                TolerantStage(ControllerStage.RECALL, self._recall_stage, expired=_recall_expired),
                self._recall,
            ),
            Stage(ControllerStage.UNDERSTANDING, self._understanding_stage, expired=_turn_expired),
            TolerantStage(
                ControllerStage.STORY_LINKS, self._story_links_stage, expired=_story_links_expired
            ),
            Stage(ControllerStage.TAKEOVER, self._takeover_stage, expired=_takeover_expired),
            *phases.stages(),
        ]
        await phases.run(
            working,
            lambda: self._controlled(working, stages),
            state=state,
        )

    async def _phases_turn(self, taken: ChatInput) -> None:
        """The reader's input planned by the phases (ADR-0309 §2:6, §3).

        The turn's working set holds the input, its window and the phases' part, and
        the controller runs ADR-0309 §3's table over the stages before planning — the
        conversation, the windows, recall, understanding and the story links, then
        recall's second run (ADR-0308 §2) — and the four phase stages. The phases write
        the activation's messages as it runs, and the path carries what the episode
        freezes with.
        """
        phases = self._phases
        assert phases is not None  # noqa: S101 — the reader is wired only beside them
        state = active_state()
        trigger = None if state is None else state.trigger
        if state is not None and trigger is not None:
            # ADR-0349 §5:3, §7:5: who wrote the input, which the in-progress section,
            # an absorption and an offer read: every message the reader takes in is the
            # user's (ADR-0293 §6:1), and carries the owner's words, as the hub chat's
            # kind declares (ADR-0351 §3:1).
            state.input_messages = tuple(
                RecordedInputMessage(
                    text=one.text,
                    sent_at=one.written_at,
                    position=one.position,
                    party=message_party("conversation", None),
                )
                for one in taken.messages
            )
            state.standing = input_standing(
                parties=trigger.parties,
                established=all(one.author is MessageAuthor.USER for one in taken.messages),
            )
        working = _TurnPass(
            utterance=taken.text,
            requested=taken.conversation_id,
            context=_EMPTY_CHANNEL_CONTEXT,
            deadline=(asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()),
            # The conversation's own devices (ADR-0293 §7:4): a bounded audience, so a
            # record placed for the owner alone may be shown (ADR-0307 §6:4).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            transcript=taken.window,
            understanding_wired=self._understanding is not None,
            recall_wired=self._recall is not None,
            story_links_wired=self._story_links is not None,
            phases=phases.begin(
                activation_id=taken.activation_id,
                window=taken.window,
                conversation_id=taken.conversation_id,
                trigger=trigger,
                owner_records=True,
            ),
            activation=state,
        )
        if working.phases is not None:
            # ADR-0350 §3:4: a person's conversation is offered spawn.
            working.phases.scheduling = self._scheduling(
                state,
                ChannelIdentity(channel_type="conversation", instance_id=taken.conversation_id),
            )
        stages: list[ControllerStageRun[_TurnPass]] = [
            Stage(ControllerStage.BEGIN_CONVERSATION, self._begin_conversation_stage),
            Stage(ControllerStage.WINDOWS, self._windows_stage, expired=_windows_expired),
            # ADR-0308 §2: recall runs twice on a phases pass, its second run over the
            # same stage once understanding has recorded, which the path runs.
            phases.recall_stage(
                TolerantStage(ControllerStage.RECALL, self._recall_stage, expired=_recall_expired),
                self._recall,
            ),
            Stage(ControllerStage.UNDERSTANDING, self._understanding_stage, expired=_turn_expired),
            TolerantStage(
                ControllerStage.STORY_LINKS, self._story_links_stage, expired=_story_links_expired
            ),
            Stage(ControllerStage.TAKEOVER, self._takeover_stage, expired=_takeover_expired),
            *phases.stages(),
        ]
        await phases.run(
            working,
            lambda: self._controlled(working, stages),
            state=state,
        )

    async def _phases_event(
        self,
        resolved: ResolvedChannelInput,
        *,
        deadline: float,
        projection: ChannelProjection,
    ) -> ChannelResult:
        """An event run through the phases (ADR-0313 §4:3-§4:5).

        One activation whose place takes no message (ADR-0307 §3:8): the windows,
        recall, understanding and the story links run as on a turn's pass, then
        recall's second run and the four phase stages by ADR-0309 §3's table. Its
        rounds' text is kept with the episode and written nowhere, nothing they wrote is
        returned, and it cannot message the user (ADR-0309 §5:6); planning can still
        remember, note and change stories (§5:5). ``deadline`` is the event's
        ``timeout`` read at admission, the activation's budget (§4:5).

        Returns:
            The result: *done*, or *couldn't finish* where the round limit ended it.
            One whose stage failed or timed out, or that was stopped, raises here and
            :meth:`_activation_task` answers it with its result once the episode has
            frozen (§4:5).
        """
        phases = self._phases
        assert phases is not None  # noqa: S101 — an event is refused at admission without them
        state = active_state()
        trigger = None if state is None else state.trigger
        activation_id = None if state is None else state.activation_id
        event = _EventPass(
            input=resolved,
            deadline=deadline,
            # ADR-0276 §4: an informational-event pass is of bounded audience, so a
            # record placed for the owner alone may be shown (ADR-0307 §6:4).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            understanding_wired=self._understanding is not None,
            recall_wired=self._recall is not None,
            story_links_wired=self._story_links is not None,
            phases=phases.begin_event(
                # An activation whose id was not minted has a degraded capture
                # (ADR-0275 §2); its rounds still need one to claim under.
                activation_id=_uuid() if activation_id is None else activation_id,
                trigger=trigger,
                owner_records=True,
            ),
            activation=state,
        )
        stages: list[ControllerStageRun[_EventPass]] = [
            Stage(ControllerStage.WINDOWS, self._windows_stage, expired=_windows_expired),
            # ADR-0308 §2: recall runs twice on a phases pass, as on a turn's.
            phases.recall_stage(
                TolerantStage(ControllerStage.RECALL, self._recall_stage, expired=_recall_expired),
                self._recall,
            ),
            Stage(
                ControllerStage.UNDERSTANDING,
                self._phases_event_understanding_stage,
                expired=_turn_expired,
            ),
            TolerantStage(
                ControllerStage.STORY_LINKS, self._story_links_stage, expired=_story_links_expired
            ),
            Stage(ControllerStage.TAKEOVER, self._takeover_stage, expired=_takeover_expired),
            *phases.stages(),
        ]
        await phases.run(
            event,
            lambda: self._controlled(event, stages),
            state=state,
        )
        unfinished = state is not None and state.unfinished
        result = ChannelResult(
            channel=resolved.channel,
            capture=UNCAPTURED,
            result=InformationalEventResult(
                ended=ActivationEnding.COULDNT_FINISH if unfinished else ActivationEnding.DONE
            ),
        )
        self._checked(projection.terminal(result), projection.method)
        return result

    # --- the Approvals channel (ADR-0361) ---

    def _wire_approvals(
        self, seams: ApprovalsSeams, *, plans: PlanStore, memory: MemoryStore
    ) -> None:
        """Build the sensor and ``request_approval``'s runner, and offer the two calls.

        Raises:
            ConfigurationError: If the phases are not wired, which plan every activation
                an outcome starts.
        """
        phases = self._phases
        if phases is None:
            msg = (
                "an approval's activation runs through the phases, so the Approvals channel "
                "is wired only beside them (ADR-0361 §6, ADR-0309 §2:6)"
            )
            raise ConfigurationError(msg)
        calls = ApprovalCalls(
            plans=plans,
            expiry=seams.expiry,
            now=self._clock,
            wake=self.approvals_changed,
            cards=seams.cards,
        )
        self._approvals_sensor = ApprovalsSensor(
            plans=plans,
            memory=memory,
            push=self._push_outcome,
            is_running=self._approval_live,
            closing=lambda: self._closing,
            recheck=seams.recheck,
            now=self._clock,
        )
        if self._place_lists is None:
            line = self._telegram_seams
            self._place_lists = PlaceLists(
                conversations=self._conversations.chat_space,
                line=None if line is None else line.channel,
                line_connected=None if line is None else self._line_connected,
            )
        phases.attach_approvals(calls, self._tickets_held)

    def approvals_changed(self) -> None:
        """Wake the Approvals channel's sensor: a request was written, tapped or voided.

        ADR-0361 §3:4: the sensor wakes on every write to a request. A surface's tap
        (AP3's card, AP4's panel) calls this once its store step has landed.
        """
        if self._approvals_sensor is not None:
            self._approvals_sensor.wake()

    # --- the hub page's approvals panel (ADR-0361 §4:6-§4:9, §8:4) ---

    async def approvals(self, *, limit: int = DEFAULT_PAGE_SIZE) -> ApprovalPanel:
        """The person's requests, as the hub page's approvals panel shows them (§4:6).

        Read from the plan store whether or not the Approvals channel is wired: a hub
        with none wired holds no request, and shows none. The person is the owner, whom
        every device admitted under ADR-0124 carries (§4:8, ADR-0124 §5).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``limit`` is out of range.
            TypeError: If ``limit`` is not an integer.
            PlanningError: If the plan store cannot be read.
        """
        self._reject_if_closing()
        page_argument(limit, name="limit")
        check_arguments("approvals", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            approval_panel(
                self._plans,
                self._approval_facts,
                person=OWNER_PERSON_ID,
                now=self._now(),
                limit=limit,
            ),
            "approvals",
            checked=True,
        )

    async def tap_approval(
        self, request_id: Identifier, /, *, choice: ApprovalChoice
    ) -> ApprovalPanelTap:
        """The panel's tap: mark the request, then wake the sensor (ADR-0361 §4:7-§4:9).

        A command, never perceived: nothing here admits an activation. The sensor, woken
        once the store step has landed, pushes the outcome (§3:4), and the line's reader
        edits the card (§4:5).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``request_id`` is not an identifier, or ``choice`` is neither
                Approve nor Deny.
            PlanningError: If the plan store cannot be read or written.
        """
        self._reject_if_closing()
        named = identifier(request_id, name="request_id")
        chosen = approval_choice(choice)
        check_arguments(
            "tap_approval", max_bytes=self._max_payload_bytes, request_id=named, choice=chosen
        )
        return await self._tracked(self._tap_approval(named, chosen), "tap_approval", checked=True)

    async def _tap_approval(self, request_id: str, choice: ApprovalChoice) -> ApprovalPanelTap:
        tapped, landed = await tap_on_approval_panel(
            self._plans,
            self._approval_facts,
            request_id,
            choice,
            person=OWNER_PERSON_ID,
            now=self._now(),
        )
        if landed:
            self.approvals_changed()
        return tapped

    async def _approval_facts(self, requests: Sequence[ApprovalRequest]) -> dict[str, CardFacts]:
        """What each request's card shows beside it, read from the activation that asked.

        From the running activation where this engine still runs it, and otherwise from
        its frozen episode (:func:`episode_card_facts`).
        """
        facts: dict[str, CardFacts] = {}
        unread: list[ApprovalRequest] = []
        for one in requests:
            state = self._running_state(str(one.activation_id))
            if state is None:
                unread.append(one)
            else:
                facts[str(one.id)] = approval_card_facts(one, state.trigger, state.call_records)
        if unread:
            facts.update(await episode_card_facts(self._memory, unread))
        return facts

    def _approval_live(self, activation_id: str) -> bool:
        """Whether an approval's activation is being pushed, or runs here."""
        return activation_id in self._approval_pushing or (
            self._running_state(activation_id) is not None
        )

    def _held_requests(self, state: ActivationState) -> tuple[str, ...]:
        """The requests whose approval input ``state`` holds now (ADR-0361 §5:6).

        The approval's own activation's, where no take moved it on, and each one a take
        brought it, followed through what it absorbed. An activation absorbed, or whose
        input was taken, holds none: what it held moved with its input.
        """
        if not self._approval_inputs:
            return ()
        if state.absorbed_by is not None or state.handed_to is not None:
            return ()
        own = (state.activation_id,) if state.activation_id is not None else ()
        held = [one for one in (*own, *state.merged) if one in self._approval_inputs]
        return tuple(dict.fromkeys(str(self._approval_inputs[one].id) for one in held))

    async def _tickets_held(self, state: ActivationState) -> tuple[Ticket, ...]:
        """The tickets ``state`` holds, approved and still held, read now (§5:1, §5:6).

        Only the request's person's: a ticket is for that person alone (§5:1). A store
        that cannot be read shows none, and runs none.
        """
        held = self._held_requests(state)
        if not held:
            return ()
        try:
            found = await self._plans.approval_requests(list(held))
        except PlanningError:
            _log.warning("approval_tickets_unread", stage="planning", reason="store_failed")
            return ()
        person = activation_person(state.trigger)
        now = self._now()
        return tuple(
            ticket
            for one in found
            if one.person == person and (ticket := ticket_of(one, at=now)) is not None
        )

    async def _void_tickets(self, state: ActivationState, held: Sequence[str]) -> None:
        """ADR-0361 §5:7: the work holding these tickets' inputs ended without running them.

        A ticket used or already void answers that it holds none, which changes nothing.
        """
        for request_id in held:
            try:
                await self._plans.void_approval_ticket(request_id)
            except PlanningError:
                _log.warning("approval_ticket_unvoided", stage="approvals", reason="store_failed")
        for one in (state.activation_id, *state.merged):
            self._approval_inputs.pop(str(one), None)
        self.approvals_changed()

    async def _push_outcome(self, request: ApprovalRequest, activation_id: str | None) -> None:
        """Push one request's outcome, and admit its activation (ADR-0361 §3:4, §3:7).

        The id the activation will be admitted under is minted here and named by the
        pushed mark, written in one store step that refuses where the outcome is already
        marked; a push again after a restart names the id the mark already holds, and
        marks nothing.
        """
        if self._closing:
            return
        fresh = activation_id is None
        pushed_to = self._chat_activation_id() if activation_id is None else activation_id
        self._approval_pushing.add(pushed_to)
        try:
            if fresh:
                answer = await self._plans.mark_approval_outcome_pushed(str(request.id), pushed_to)
                if answer is not ApprovalOutcomePush.PUSHED:
                    return
            context, linked, suggests = await self._approval_context(request)
            self._admit_approval(request, pushed_to, context, linked, suggests)
        except RuntimeError:
            # The engine began closing: left pushed, the next start pushes it again.
            if not self._closing:
                raise
        finally:
            self._approval_pushing.discard(pushed_to)

    async def _approval_context(
        self, request: ApprovalRequest
    ) -> tuple[PlaceItem, tuple[str, ...], tuple[str, ...]]:
        """What an approval's input brings with it, and where its asking work spoke (§6:2, §6:7).

        The request as its card shows it, linked to the asking activation's episode; that
        episode's address where it has frozen, which the episode window shows by its short
        view (ADR-0356 §9); and the places the asking work's place list suggests: the place
        its input came from where it takes a message, or, for an activation the Task
        Scheduler started, its task's suggested places.
        """
        asking = str(request.activation_id)
        address = f"activation:{asking}"
        running = self._running_state(asking)
        place = None if running is None else running.place
        linked: tuple[str, ...] = ()
        try:
            record = await self._memory.get(address)
        except MemoryStoreError:
            record = None
        if isinstance(record, EpisodicMemory) and record.processing_record is not None:
            trigger = record.processing_record.trigger
            if place is None:
                target = trigger.channel or trigger.target
                place = target if isinstance(target, ChannelIdentity) else None
            if not record.processing_record.is_open:
                linked = (address,)
        suggests: tuple[str, ...] = ()
        if place is not None and place.channel_type in {"conversation", TELEGRAM.channel_type}:
            suggests = (place_of(place),)
        elif place == SCHEDULE:
            suggests = await self._task_places(asking)
        kind = None if place is None else origin_kind(place.channel_type)
        call = request.call
        line = exact_line(
            AskedCall(
                part=1,
                tool=call.tool,
                values=call.values,
                binding=call.binding,
                deliberate_repeat=call.deliberate_repeat,
            ),
            filled=call.tool.system_supplied,
        )
        where = "where nothing is recorded" if kind is None else kind.where
        text = (
            f"A request for the person's yes, as its card shows it: {line}. Why, as the "
            f"system said when it asked: {request.why} It was asked {where}, and is now "
            f"{request.state.value}."
        )
        return (
            PlaceItem(
                author=PlaceAuthor.APPROVALS,
                text=text,
                at=request.written_at,
                episode_id=address,
            ),
            linked,
            suggests,
        )

    async def _task_places(self, activation_id: str) -> tuple[str, ...]:
        """The places the task an activation the Task Scheduler started suggests."""
        try:
            lineage = await self._plans.scheduled_lineage(activation_id)
        except PlanningError:
            return ()
        for task in reversed(lineage):
            if any(activation_id in one.activations for one in task.occurrences):
                return tuple(place_of(one) for one in task.places)
        return ()

    def _admit_approval(
        self,
        request: ApprovalRequest,
        activation_id: str,
        context: PlaceItem,
        linked: tuple[str, ...],
        suggests: tuple[str, ...],
    ) -> None:
        """Admit the activation an outcome starts, in one synchronous step (ADR-0361 §6).

        Its input is the outcome, stated by the hub, on the approvals, carrying no one's
        words and no authority (§6:1); it is meant for the asking activation by code's
        link (§6:3), and runs side by side with every other activation.
        """
        text = approval_input(request)
        state = admit_channel(
            ChannelInput(target=THE_APPROVALS, payload=TextChannelPayload(text=text)),
            None,
            clock=self._now,
            id_factory=lambda: activation_id,
            stage_limit=self._stage_record_limit,
        )
        state.meant_for = str(request.activation_id)
        # ADR-0349 §7:21: what a take of its offer brings, the input as the hub stated it.
        state.input_messages = (RecordedInputMessage(text=text, sent_at=self._now()),)
        self._approval_inputs[activation_id] = request
        deadline = asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()
        work = self._activation_task(
            ActivationScope(state),
            lambda: self._approval_turn(
                activation_id, deadline, context=context, linked=linked, suggests=suggests
            ),
            seam="approvals",
            check_output=_unchecked,
            deadline=deadline,
        )
        self._spawn_read(self._approval_ended(work, state))

    async def _approval_ended(
        self,
        work: asyncio.Task[tuple[None, EpisodeCaptureReport | None]],
        state: ActivationState,
    ) -> None:
        """Read how an approval's activation ended: a stop by a take is how it hands over.

        Its outcome is already the request's (§3:4); what it held is voided as it ends
        (§5:7). A failure is logged as a channel activation's is.
        """
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # every ending is the activation's own
            if not isinstance(exc, ActivationStoppedError):
                _log_chat_failure(exc, state=state, marked=True, reader="approvals")

    async def _approval_turn(
        self,
        activation_id: str,
        deadline: float,
        *,
        context: PlaceItem,
        linked: tuple[str, ...],
        suggests: tuple[str, ...],
    ) -> None:
        """An activation an approval's outcome started, planned by the phases (ADR-0361 §6).

        Its place window is the request as its card shows it, and its episode window the
        asking episode where it has frozen (§6:2). Understanding still reads its input;
        code sets what it continues and the matter it belongs to (§6:3), so the takeover
        stage offers it to the asking work where that work still runs (§6:4); otherwise
        it plans with its input, after any wait the offer leaves (§6:5). Its messages go
        only into places on its place list (§6:7).
        """
        phases = self._phases
        assert phases is not None  # noqa: S101 — the Approvals channel is wired only beside them
        state = active_state()
        trigger = None if state is None else state.trigger
        payload = None if trigger is None else trigger.payload
        text = payload.text if isinstance(payload, RecordedTextInput) else context.text
        resolved = ResolvedChannelInput(
            channel=THE_APPROVALS,
            text=text,
            modality=Modality.TEXT,
            context=ChannelContext(
                history=(
                    ChannelContextItem(
                        text=context.text, item_id=context.episode_id, source="Approvals"
                    ),
                )
            ),
        )
        working_phases = phases.begin_approval(
            activation_id=activation_id, trigger=trigger, context=(context,)
        )
        scheduling = self._approval_scheduling(state, suggests)
        if scheduling is not None:
            scheduling.places, scheduling.targets = await scheduling.build()
            working_phases.place = replace(
                working_phases.place, takes_message=bool(scheduling.targets)
            )
        working_phases.scheduling = scheduling
        event = _TaskPass(
            input=resolved,
            deadline=deadline,
            # The approvals are private (§3:2), so a record placed for the owner alone may
            # be shown (ADR-0307 §6:4).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            understanding_wired=self._understanding is not None,
            recall_wired=self._recall is not None,
            story_links_wired=self._story_links is not None,
            phases=working_phases,
            activation=state,
            linked=linked,
        )
        stages: list[ControllerStageRun[_EventPass]] = [
            Stage(ControllerStage.WINDOWS, self._windows_stage, expired=_windows_expired),
            phases.recall_stage(
                TolerantStage(ControllerStage.RECALL, self._recall_stage, expired=_recall_expired),
                self._recall,
            ),
            Stage(
                ControllerStage.UNDERSTANDING,
                self._phases_event_understanding_stage,
                expired=_turn_expired,
            ),
            TolerantStage(
                ControllerStage.STORY_LINKS, self._story_links_stage, expired=_story_links_expired
            ),
            Stage(ControllerStage.TAKEOVER, self._takeover_stage, expired=_takeover_expired),
            *phases.stages(),
        ]
        await phases.run(event, lambda: self._controlled(event, stages), state=state)

    def _approval_scheduling(
        self, state: ActivationState | None, suggests: tuple[str, ...]
    ) -> Scheduling | None:
        """An approval's activation's place list (ADR-0361 §6:7), and no spawn.

        The line's chat, where the line is connected, and the asking work's places,
        marked suggested; it writes messages into places on that list alone, as a task's
        activation does (ADR-0350 §6:7).
        """
        lists = self._place_lists
        person = None if state is None else activation_person(state.trigger)
        if lists is None or person is None:
            return None

        async def build() -> tuple[tuple[ListedPlace, ...], dict[str, PlaceTarget]]:
            places = await lists.shown(input_place=None, suggested=suggests)
            targets = {
                one.place: target
                for one in places
                if (target := self._place_target(one.channel)) is not None
            }
            return places, targets

        return Scheduling(
            person=person, set_in=THE_APPROVALS, build=build, by_label=True, spawns=False
        )

    # --- the Task Scheduler (ADR-0350) ---

    def _wire_task_scheduler(
        self, seams: TaskSchedulerSeams, *, plans: PlanStore, memory: MemoryStore
    ) -> None:
        """Build the sensor, the Task Manager and the place lists, and offer the calls.

        Raises:
            ConfigurationError: If the phases are not wired, which plan every activation
                a task starts.
        """
        phases = self._phases
        if phases is None:
            msg = (
                "the Task Scheduler's activations run through the phases, so it is wired "
                "only beside them (ADR-0350 §6, ADR-0309 §2:6)"
            )
            raise ConfigurationError(msg)
        # ADR-0340 §3:3, §6:1: every scheduled task's times are read and rendered in the
        # person's zone, their profile's where the person model sets one, and the hub's
        # ``Settings.timezone`` otherwise.
        blocks = self._person_blocks
        self._task_zones = PersonZones(
            default=ZoneInfo(seams.zone), people=None if blocks is None else blocks.store
        )
        self._lateness_grace = seams.lateness_grace
        self._task_manager = TaskManager(
            plans=plans,
            memory=memory,
            running=lambda: (one.state for one in self._running if one.state is not None),
            # §7:8: a task is kept while its parent, the activation that spawned it, runs.
            is_running=lambda one: self._running_state(one) is not None,
            starting=self._starting,
            wake=self._wake_sensor,
            limits=seams.limits,
            zones=self._task_zones,
            now=self._clock,
        )
        self._task_sensor = TaskSchedulerSensor(
            plans=plans,
            memory=memory,
            conversations=self._conversations.chat_space,
            push=self._push_occurrence,
            is_running=self._is_live,
            settled=self._occurrence_settled,
            retry=self._write_unwritten,
            closing=lambda: self._closing,
            persons=seams.persons,
            limits=SensorLimits(recheck=seams.recheck, push_limit=seams.push_limit),
            now=self._clock,
        )
        line = self._telegram_seams
        self._place_lists = PlaceLists(
            conversations=self._conversations.chat_space,
            line=None if line is None else line.channel,
            line_connected=None if line is None else self._line_connected,
        )
        phases.attach_task_scheduler(
            ScheduledTaskCalls(manager=self._task_manager, now=self._clock)
        )

    @property
    def task_manager(self) -> TaskManager | None:
        """The Task Manager (ADR-0350 §10), or ``None`` where no Task Scheduler is wired.

        Concrete surface, not ``AssistantEngine``'s (§10:6): no adapter reaches it until
        the decision that opens its view brings its operations to the local API.
        """
        return self._task_manager

    def _is_live(self, activation_id: str) -> bool:
        """Whether an activation is running here, pushed and not yet admitted, or ending.

        One the Task Scheduler started counts until its occurrence's outcome is written,
        so a later settlement never settles it twice (§7:6, §8:1).
        """
        return (
            activation_id in self._pushed
            or activation_id in self._admitted
            or activation_id in self._unwritten
            or self._running_state(activation_id) is not None
        )

    async def _write_unwritten(self) -> None:
        """Write again each outcome the store failed to take when its activation ended.

        ADR-0350 §7:6: the outcome is how the activation ended, known when it ended, so
        it is written as it was decided; a write that fails again is held for the next.
        """
        for activation_id, outcome in list(self._unwritten.items()):
            try:
                settled = await self._plans.settle_occurrence(activation_id, outcome)
            except PlanningError:
                _log.warning(
                    "task_outcome_unwritten", stage="task_scheduler", reason="store_failed"
                )
                continue
            self._unwritten.pop(activation_id, None)
            await self._occurrence_settled(settled)

    def _wake_sensor(self) -> None:
        if self._task_sensor is not None:
            self._task_sensor.wake()

    async def _line_connected(self) -> bool:
        """Whether the line's connection is active (ADR-0350 §5:8, ADR-0323 §3:7)."""
        line = self._telegram_seams
        if line is None:
            return False
        accounts = await self._connections.connected()
        return any(
            one.reference == line.reference and one.state is ProvisioningState.ACTIVE
            for one in accounts
        )

    def _scheduling(
        self,
        state: ActivationState | None,
        set_in: ChannelIdentity,
        task: ScheduledTask | None = None,
    ) -> Scheduling | None:
        """What an activation offered spawn holds of the Task Scheduler (ADR-0350 §3:4).

        Offered only to an activation that is a person's and was started from a
        conversation, from the line or by the Task Scheduler; ``None`` otherwise, and
        where no Task Scheduler is wired.
        """
        lists = self._place_lists
        person = None if state is None else activation_person(state.trigger)
        if lists is None or person is None or set_in.channel_type not in SPAWNING_KINDS:
            return None
        suggested = None if task is None else [place_of(one) for one in task.places]
        input_place = None if task is not None else set_in

        async def build() -> tuple[tuple[ListedPlace, ...], dict[str, PlaceTarget]]:
            # ADR-0361 §7:3: a place an input taken by a take came from is on the list.
            taken = () if state is None or task is not None else _taken_channels(state)
            places = await lists.shown(input_place=input_place, suggested=suggested, taken=taken)
            targets = {
                one.place: target
                for one in places
                if (target := self._place_target(one.channel)) is not None
            }
            return places, targets

        return Scheduling(person=person, set_in=set_in, build=build, task=task)

    def _place_target(self, channel: ChannelIdentity) -> PlaceTarget | None:
        """A place on a place list, with its writer: the hub chat's, or the line's."""
        phases = self._phases
        if channel.channel_type == "conversation" and phases is not None:
            return phases.conversation_target(channel.instance_id)
        writer = self._telegram_writer
        if writer is not None and channel.channel_type == TELEGRAM.channel_type:
            return PlaceTarget(channel=channel, writer=writer.for_place(channel))
        return None

    async def _task_writers(self) -> tuple[str, ...]:
        """The activations the Task Scheduler started lately, which may be a message's writer.

        ADR-0350 §9:1: a message such an activation wrote into a place a reader's window
        shows links to it. Those running, and those frozen on the schedule.
        """
        if self._task_manager is None:
            return ()
        running = [
            one.state.activation_id
            for one in self._running
            if one.state is not None
            and one.state.activation_id is not None
            and one.state.place == SCHEDULE
        ]
        return (
            *running,
            *(
                one.processing_record.activation_id
                for one in await self._schedule_episodes()
                if one.processing_record is not None
            ),
        )

    async def _schedule_episodes(self) -> tuple[EpisodicMemory, ...]:
        """The schedule's recent frozen episodes, newest last (ADR-0350 §7:9, §9:1)."""
        if self._task_manager is None:
            return ()
        try:
            page = await self._memory.channel_episodes(SCHEDULE, limit=CHAT_WINDOW_SIZE)
        except MemoryStoreError:
            _log.warning("schedule_episodes_unread", stage="reader", reason="store_failed")
            return ()
        return tuple(
            one.record
            for one in page.entries
            if one.record.processing_record is not None and not one.record.processing_record.is_open
        )

    async def _push_occurrence(self, due: DueOccurrence) -> None:
        """Push one due occurrence, and admit its activation unless it is stopped (§7:5).

        The id the activation will be admitted under is minted and held here before the
        pushed mark is written, so a stop naming it meanwhile is noted; the mark is
        written in one store step that refuses only where the occurrence is no longer
        pending or its task is no longer held, never for its lineage (ADR-0352 §2:3).
        Admission then refuses an id carrying a stop record (§9:10), read with nothing
        awaited between that check and the admission, so nothing starts that a stop
        named.
        """
        if self._closing:
            return
        push = await self._occurrence_push(due)
        activation_id = self._chat_activation_id()
        self._pushed[activation_id] = False
        try:
            answer = await self._plans.mark_occurrence_pushed(
                due.task.id, due.number, activation_id, rule=push.rule
            )
            if answer is not OccurrencePush.PUSHED:
                self._pushed.pop(activation_id, None)
                return
            stopped = activation_id in await self._plans.stopped_activations([activation_id])
        except BaseException:
            self._pushed.pop(activation_id, None)
            raise
        pushed_at = self._now()
        if stopped or self._pushed.get(activation_id, False):
            self._pushed.pop(activation_id, None)
            settled = await self._plans.settle_occurrence(activation_id, OccurrenceState.STOPPED)
            await self._occurrence_settled(settled)
            return
        try:
            self._admit_task(due, activation_id, pushed_at=pushed_at, push=push)
        except RuntimeError:
            # The engine began closing: left pushed, the next start settles it (§8:5).
            self._pushed.pop(activation_id, None)
            if not self._is_closing():
                raise

    def _is_closing(self) -> bool:
        return self._closing

    async def _occurrence_push(self, due: DueOccurrence) -> _OccurrencePush:
        """What a push of ``due`` states, read before its pushed mark is written.

        The person's zone, which its input is told in (ADR-0340 §6:1); a person-model
        store that cannot be read raises, before anything is written, so the sensor
        tries the push again at a later look rather than guess a zone. For a rule's
        occurrence never pushed before, the instants the rule's arithmetic gives in the
        zone it is computed in now, its own or the person's (§4:3): its successor, and,
        where it missed more than one, the latest missed, pushed in its place, and those
        between, recorded skipped (§4:6, §4:8). A push again after a restart states none
        (§4:8, ADR-0350 §8:5-§8:6).
        """
        task = due.task
        occurrence = task.occurrence(due.number)
        assert occurrence is not None  # noqa: S101 — the store gave this occurrence as due
        zone = await self._task_zones.of(task.person)
        when = task.when
        if not isinstance(when, DueOnRule) or occurrence.activations or occurrence.due_at is None:
            return _OccurrencePush(
                zone=zone, due_at=occurrence.due_at, second_try=occurrence.second_try
            )
        stated = rule_push(when, occurrence.due_at, task_zone(task, zone), now=self._now())
        if stated.latest is None:
            return _OccurrencePush(zone=zone, due_at=occurrence.due_at, rule=stated)
        # The pending occurrence and each one between it and the latest end skipped.
        return _OccurrencePush(
            zone=zone, due_at=stated.latest, rule=stated, skipped=len(stated.skipped) + 1
        )

    def _admit_task(
        self,
        due: DueOccurrence,
        activation_id: str,
        *,
        pushed_at: datetime,
        push: _OccurrencePush,
    ) -> None:
        """Admit the activation an occurrence starts, in one synchronous step (ADR-0350 §6).

        Its input is the task's, stated by the hub (§6:2), on the schedule; its origin is
        what the register declares for it, ``outside`` where the task carries the mark
        (§6:3). It runs side by side with every other activation (§2:6), as the line's
        and the chat's do, and its outcome is written on its occurrence once it ends.
        """
        task = due.task
        due_at = push.due_at
        late = due_at is not None and pushed_at - due_at > self._lateness_grace
        text = task_input(
            task,
            due_at=due_at,
            second_try=push.second_try,
            zone=push.zone,
            late_at=pushed_at if late else None,
            skipped=push.skipped,
            now=pushed_at,
        )
        state = admit_channel(
            ChannelInput(target=SCHEDULE, payload=TextChannelPayload(text=text)),
            None,
            clock=self._now,
            id_factory=lambda: activation_id,
            stage_limit=self._stage_record_limit,
            carries_outside_mark=task.outside_content,
        )
        deadline = asyncio.get_running_loop().time() + self._chat_turn_budget.total_seconds()
        work = self._activation_task(
            ActivationScope(state),
            lambda: self._task_turn(task, activation_id, deadline, zone=push.zone),
            seam="task_scheduler",
            check_output=_unchecked,
            deadline=deadline,
        )
        # Admitted: the activation is among those running from here (eager start).
        self._admitted.add(activation_id)
        self._pushed.pop(activation_id, None)
        self._spawn_read(self._task_ended(work, state, activation_id))

    async def _task_ended(
        self,
        work: asyncio.Task[tuple[None, EpisodeCaptureReport | None]],
        state: ActivationState,
        activation_id: str,
    ) -> None:
        """Write the occurrence's outcome from how its activation ended (ADR-0350 §7:6).

        *done* where its episode froze completed, *couldn't finish* where it froze failed,
        *stopped* where a stop ended it, and *interrupted* otherwise. A shutdown's
        cancellation writes nothing: the next start settles it (§8).
        """
        try:
            await self._settle_ended(work, state, activation_id)
        finally:
            self._admitted.discard(activation_id)

    async def _settle_ended(
        self,
        work: asyncio.Task[tuple[None, EpisodeCaptureReport | None]],
        state: ActivationState,
        activation_id: str,
    ) -> None:
        failure: BaseException | None = None
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # every ending is the occurrence's outcome
            failure = exc
            if not isinstance(exc, ActivationStoppedError):
                _log_chat_failure(exc, state=state, marked=True, reader="task_scheduler")
        if state.stopped:
            outcome = OccurrenceState.STOPPED
        else:
            status, _ = terminal_status(state, failure)
            outcome = {
                ProcessingStatus.COMPLETED: OccurrenceState.DONE,
                ProcessingStatus.FAILED: OccurrenceState.COULDNT_FINISH,
            }.get(status, OccurrenceState.INTERRUPTED)
        try:
            settled = await self._plans.settle_occurrence(activation_id, outcome)
        except PlanningError:
            # The outcome is known: it is held, and written again at the sensor's next
            # look, never classified again as a restart would (§7:6).
            _log.warning("task_outcome_unwritten", stage="task_scheduler", reason="store_failed")
            self._unwritten[activation_id] = outcome
            self._wake_sensor()
            return
        await self._occurrence_settled(settled)

    async def _occurrence_settled(self, task: ScheduledTask) -> None:
        """An occurrence ended: wake the sensor, and tidy its task away (§7:7, §7:8)."""
        self._wake_sensor()
        if self._task_manager is not None:
            await self._task_manager.tidy([task.id])

    def _parent_ended(self, scope: ActivationScope) -> None:
        """An activation ended: the tasks it spawned may now be removed (§7:8)."""
        manager = self._task_manager
        state = scope.state
        if manager is None or state is None or state.activation_id is None or self._closing:
            return
        self._spawn_read(manager.parent_ended(state.activation_id))

    async def _task_turn(
        self, task: ScheduledTask, activation_id: str, deadline: float, *, zone: ZoneInfo
    ) -> None:
        """An activation a scheduled task started, planned by the phases (ADR-0350 §6).

        Its channel window is the schedule's place window, its task's lineage (§6:5),
        and its episode window shows the episodes its input links to. It is an ordinary
        activation beyond its place list (§6:10): the windows, recall, understanding and
        the story links run as on an event's pass, then recall's second run and the four
        phase stages, and its messages go only into places on its list (§6:7).
        """
        phases = self._phases
        assert phases is not None  # noqa: S101 — the Task Scheduler is wired only beside them
        state = active_state()
        trigger = None if state is None else state.trigger
        steps, linked = await self._lineage(task, activation_id, zone)
        payload = None if trigger is None else trigger.payload
        text = payload.text if isinstance(payload, RecordedTextInput) else task.instruction
        resolved = ResolvedChannelInput(
            channel=SCHEDULE,
            text=text,
            modality=Modality.TEXT,
            context=ChannelContext(
                history=tuple(
                    ChannelContextItem(
                        text=one.text, item_id=one.episode_id, source="the Task Scheduler"
                    )
                    for one in steps
                )
            ),
        )
        working_phases = phases.begin_task(
            activation_id=activation_id,
            trigger=trigger,
            lineage=tuple(
                PlaceItem(
                    author=PlaceAuthor.TASK_SCHEDULER,
                    # ADR-0307 §9:2, ADR-0350 §6:3: a task carrying the outside-content
                    # mark is shown withheld, and reaches planning through understanding.
                    text=text if one.current and not task.outside_content else one.text,
                    at=one.at,
                    is_input=one.current,
                    episode_id=one.episode_id,
                )
                for one in steps
            ),
        )
        scheduling = self._scheduling(state, SCHEDULE, task)
        if scheduling is not None:
            # ADR-0350 §5:8: the place list is built at the activation's start, so a stage
            # failing before planning still writes *couldn't finish* into its suggested
            # places (§6:7); each planning round builds it again.
            scheduling.places, scheduling.targets = await scheduling.build()
            working_phases.place = replace(
                working_phases.place, takes_message=bool(scheduling.targets)
            )
        working_phases.scheduling = scheduling
        event = _TaskPass(
            input=resolved,
            deadline=deadline,
            # The schedule is private (§2:4), so a record placed for the owner alone may
            # be shown (ADR-0307 §6:4).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            understanding_wired=self._understanding is not None,
            recall_wired=self._recall is not None,
            story_links_wired=self._story_links is not None,
            phases=working_phases,
            activation=state,
            linked=linked,
        )
        stages: list[ControllerStageRun[_EventPass]] = [
            Stage(ControllerStage.WINDOWS, self._windows_stage, expired=_windows_expired),
            phases.recall_stage(
                TolerantStage(ControllerStage.RECALL, self._recall_stage, expired=_recall_expired),
                self._recall,
            ),
            Stage(
                ControllerStage.UNDERSTANDING,
                self._phases_event_understanding_stage,
                expired=_turn_expired,
            ),
            TolerantStage(
                ControllerStage.STORY_LINKS, self._story_links_stage, expired=_story_links_expired
            ),
            Stage(ControllerStage.TAKEOVER, self._takeover_stage, expired=_takeover_expired),
            *phases.stages(),
        ]
        await phases.run(event, lambda: self._controlled(event, stages), state=state)

    async def _lineage(
        self, task: ScheduledTask, activation_id: str, zone: ZoneInfo
    ) -> tuple[tuple[LineageStep, ...], tuple[str, ...]]:
        """The schedule's window for ``activation_id``, and the episodes its input links to.

        Its times are told in ``zone``, the person's as the push read it (ADR-0340 §6:1).

        The lineage is read from the tasks the Task Scheduler keeps (§6:5, §7:8); the
        links are its task's parent's episode and each waited-on task's (§6:5). A store
        that cannot be read leaves the current step alone, and links nothing it could not
        read.
        """
        try:
            lineage = await self._plans.scheduled_lineage(activation_id)
            waited = (
                await self._plans.scheduled_tasks(task.when.tasks)
                if isinstance(task.when, DueAfterTasks)
                else ()
            )
        except PlanningError:
            _log.warning("task_lineage_unread", stage="task_scheduler", reason="store_failed")
            lineage, waited = (task,), ()
        lineage = lineage or (task,)
        linked = (
            f"activation:{task.parent}",
            *(f"activation:{one.activations[-1]}" for one in waited if one.activations),
        )
        # A step's activation is the one its occurrence was pushed to, which for a rule
        # is the occurrence that spawned the step below it (ADR-0340 §4:10).
        ran = (lineage_occurrence(each, below).activations for each, below in pairwise(lineage))
        addresses = sorted(
            {
                f"activation:{one}"
                for one in (lineage[0].parent, *(each[-1] for each in ran if each))
            }
            | set(linked)
        )
        try:
            found = without_open_episodes(await self._memory.get_many(addresses))
        except MemoryStoreError:
            _log.warning("task_lineage_unread", stage="task_scheduler", reason="store_failed")
            found = {}
        episodes = {
            address: record
            for address, record in found.items()
            if isinstance(record, EpisodicMemory)
        }
        return lineage_steps(lineage, episodes, zone), tuple(
            one for one in linked if one in episodes
        )

    def _activation_task[T](  # noqa: PLR0913 — the scope, the work, and one knob per way a kind's call is answered
        self,
        scope: ActivationScope,
        work: Callable[[], Awaitable[T]],
        *,
        seam: str,
        check_output: Callable[[T], None],
        deadline: float | None = None,
        unfinished: Callable[[ActivationEnding], T] | None = None,
    ) -> asyncio.Task[tuple[T, EpisodeCaptureReport | None]]:
        """Enter cleanup before cancellation is possible, register, then release work.

        The deferred callable prevents an un-awaited processing coroutine when
        cancellation arrives at the admission barrier.

        **A channel activation's episode is written once the barrier opens and
        before any of its processing runs** (ADR-0286 §2:1).

        ``deadline`` is the budget the call was handed, read at receiver admission
        on the running loop's clock (ADR-0274 §7). The admission write runs inside
        it, and one it cuts short is dropped: the work then meets the expiry itself
        and is classified as its kind classifies it, and the freeze's read settles
        whether the cut-off insert landed (ADR-0286 §3:4).

        ``unfinished`` answers an activation that could not finish, or was stopped,
        with a result rather than a raise: an event the phases run (ADR-0313 §4:5). It
        is handed *stopped* where the stop mark is set and *couldn't finish* for any
        other failure, once the episode has frozen classified by that failure, so the
        record keeps why it did not finish. A cancellation still propagates as itself.

        **Its end is told to what crosses activations** (ADR-0349 §7:24-§7:25): once it
        is no longer running, each offer still open to it is declined, and each wait on
        it reads its end.
        """
        self._reject_if_closing()
        admitted = asyncio.Event()

        async def run() -> tuple[T, EpisodeCaptureReport | None]:
            token = CURRENT_ACTIVATION.set(scope)
            self._running.append(scope)
            self._admitted_in_order(scope)
            value: T | None = None
            failure: BaseException | None = None
            report: EpisodeCaptureReport | None = None
            try:
                try:
                    await admitted.wait()
                    if scope.state is not None:
                        await self._episode_admitted(scope.state, deadline)
                    value = await work()
                except BaseException as exc:
                    failure = exc
                state = scope.state
                if state is not None:
                    report = state.degraded_report()
                    try:
                        completion = await self._activation_coordinator.finish(
                            state,
                            failure=failure,
                            check_output=lambda: check_output(cast("T", value)),
                        )
                        report = completion.report
                        if failure is None:
                            failure = completion.output_failure
                    except asyncio.CancelledError:
                        if failure is None:
                            raise
                    except Exception:
                        capture_loss("terminal", "failed")
                    # ADR-0329 §7:6: the episode is frozen, so a run of the observer
                    # starts, without this activation waiting on it.
                    self._observe_soon()
                failure = _stopped_failure(state, failure)
                answer = _answered(
                    value, failure, state=state, unfinished=unfinished, check=check_output
                )
                return answer, report
            finally:
                self._running[:] = [one for one in self._running if one is not scope]
                self._no_longer_running(scope)
                self._count_end(scope)
                CURRENT_ACTIVATION.reset(token)
                self._parent_ended(scope)

        # Eager start enters run's finally and reaches only the closed barrier.
        # No processing can run until its lifetime is in the shutdown registry.
        # ADR-0298 §2:6: an activation may outlive the request that started it — a
        # stream abandoned mid-turn runs on (ADR-0173 §9) — so it runs with the
        # requesting device unset; the request's membership was checked before it.
        task = asyncio.create_task(
            self._operation_traces.observing(seam, run()),
            eager_start=True,
            context=without_requesting_device(),
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        admitted.set()
        return task

    def _admitted_in_order(self, scope: ActivationScope) -> None:
        """ADR-0349 §7:5: "started before" is read in the order of admission."""
        if scope.state is not None:
            self._admissions += 1
            scope.state.order = self._admissions

    def _no_longer_running(self, scope: ActivationScope) -> None:
        """ADR-0349 §7:24: an offer still open to it is declined, and every wait reads its end.

        ADR-0361 §5:7: a ticket whose input the ending work holds is void once it ends
        without running it, however it ends.
        """
        if scope.state is not None:
            self._matters.ended(scope.state)
            held = self._held_requests(scope.state)
            if held and not self._closing:
                self._spawn_read(self._void_tickets(scope.state, held))

    async def _tracked(  # noqa: PLR0913 — the work, its seam, and one knob per policy a caller sets
        self,
        coro: Awaitable[_T],
        seam: str,
        observe: Callable[[_T], Observation] | None = None,
        *,
        checked: bool = False,
        shielded: bool = True,
        traced: bool = True,
    ) -> _T:
        """Run ``coro`` as a tracked task, so shutdown can drain it — and usually trace it.

        The task is what :meth:`aclose` awaits. **Tracking is what ADR-0042 §2
        requires, and it is the whole of what it requires here**: the façade
        "tracks the underlying work itself, not merely its public call-tasks",
        because "cancelling the awaiting coroutine — whether by shutdown *or* by a
        client cancelling its own ``converse()``/``resume()`` mid-call — abandons
        the coroutine but **not** the worker thread". Shutdown then "awaits every
        tracked underlying operation to quiescence — **including work orphaned by an
        already-cancelled call** — before closing, shielding **that drain** from the
        shutdown's own cancellation as needed".

        **So the ADR's shield is on the drain, and a call cancelled by its caller is
        a state it expects rather than one it forbids.** ``shielded`` defaults to
        ``True`` because most of this surface keeps a call running to completion
        once begun, which is this implementation's choice and not the ADR's
        requirement — an earlier docstring here claimed ADR-0042 §2 as its ground
        and it does not say that. The distinction stopped being academic at
        ADR-0131 §2a, which is normative that "a close detected before that step
        runs cancels the poll and takes no entry": under an unconditional shield a
        disconnected long poll ran on and could still lease an entry for a
        connection that had gone. ``next_notification`` therefore passes
        ``shielded=False`` and scope-shields its own mutating steps instead, which
        satisfies both texts — see :meth:`_poll`.
        Every public method that touches a connection-owning store runs through
        here, so none can be racing a store call when :meth:`aclose` closes it. The
        public methods reject a closing engine *before* building ``coro``
        (:meth:`_reject_if_closing`), so this never receives work it must throw away
        un-awaited.

        **It is also ADR-0119 §8's one wiring point**, for the reason that section
        gives: this already wraps every public method, so "the operation's name,
        its outcome, its elapsed time and its fault class are all in hand at one
        place, for a turn, a scheduled job and a client command alike". Everything
        the emitter does is subordinate to the work (§5) — no trace failure
        reaches ``coro``'s caller, and no operation is retried, delayed or altered
        because a trace could not be written.

        **The tracing wraps the coroutine *inside* the task rather than around the
        shield**, and the placement is load-bearing twice. §4's correlation scope
        opens in the task's own copy of the context, so two concurrent operations
        cannot see each other's identifier and every trace emitted below joins to
        the right one. And the trace covers the work the task actually did: a
        caller that cancels this await abandons the shield while the task runs on,
        and a trace written out here would be a trace for an await rather than for
        an operation.

        **The result-size refusal is inside the traced region, deliberately.**
        :meth:`_checked` used to run out here, after this returned, which made an
        operation whose result would not fit record ``OK`` while its caller got an
        :class:`~ai_assistant.core.errors.OversizedValueError` — a trace that
        disagreed with the answer. It is now applied to the result *within* the
        traced work, so the refusal is what the trace records (``REFUSED``, since
        ADR-0084 §4's limit is a contract answer rather than a malfunction). What
        does not change is where the effect stands: :meth:`_checked` still runs
        after the work has committed, and ADR-0085 §8e's residue is untouched.

        **What is still not covered is what never reaches here.** A call refused at
        the door — a closing engine, a malformed page argument, an oversized
        *argument* — raises before ``coro`` is built and emits no trace. Those are
        refusals of a *call*; a trace records an operation that was served (§1), and
        widening the boundary to them means moving the emitter off the single wiring
        point §8 chose it for, which would also cost a trace for work whose caller
        cancelled the shield. #855 carries the question rather than this lane.

        Args:
            coro: The operation's own work.
            seam: Its name — a literal constant at the call site, matching the
                public method's, so a measure filtering the stream by seam is
                filtering by the surface a caller actually invoked.
            observe: How to read the operation's result onto its trace, for the
                operations whose detail the envelope cannot see (ADR-0119 §8).
                ``None`` where the envelope is the whole story.
            checked: Whether the result is measured against the contract's payload
                limit before it is returned (:meth:`_checked`). ``True`` on every
                operation whose result crosses the ``AssistantEngine`` boundary;
                ``False`` on the four maintenance operations, whose reports are the
                scheduler's and never a client's (ADR-0085 §1).
            shielded: Whether a caller's cancellation is kept off the work. ``True``
                runs it to completion regardless; ``False`` lets the cancel through,
                for an operation that must stop when its caller goes away
                (ADR-0131 §2a). **Tracking is unaffected either way** — the drain
                covers the task in both cases, which is what ADR-0042 §2 binds.
            traced: Whether an ADR-0119 §8 operation trace is emitted. ``True``
                everywhere except ADR-0151 §1's five connection operations, whose
                §6 forbids it: "No provisioning act, and no operation on this
                surface, is recorded in a trace (ADR-0141), an ``AuditTrail``, a
                conversation or a plan."

                **It suppresses the trace and nothing else** — the task is still
                registered, still drained and still shielded on the same terms, so
                ADR-0042 §2's obligation is untouched. That split is the whole
                reason this is a knob rather than a separate method: the connection
                store is connection-owning like every other, so an untracked
                provisioning act would let :meth:`aclose` close the store out from
                under ADR-0148 §6's three writes.

                **The prohibition is categorical rather than credential-scoped.**
                No trace here carries an argument — a trace records the seam, the
                outcome, the elapsed time and the fault class — so nothing leaks
                today. What §6 forecloses is the *act* being recorded at all, and
                the reason is legible in ADR-0151 §18: a connection record
                deliberately carries **no instant** (ADR-0149 §3), so a trace of
                ``connect_account`` would reintroduce a timestamped record of the
                owner's act through a different door, which §18 defers to "the
                first surface that has to answer 'when did I connect this?'".

        Returns:
            Whatever ``coro`` returned.
        """
        work = self._checked_result(coro, seam) if checked else coro
        task = self._track(work, seam, observe, traced=traced)
        if not shielded:
            # Awaiting the task directly propagates this caller's cancellation into
            # it, which is the point; it stays in `_inflight` either way, so the
            # drain still waits for whatever it orphans.
            return await task
        return await asyncio.shield(task)

    def _track(
        self,
        work: Awaitable[_T],
        seam: str,
        observe: Callable[[_T], Observation] | None = None,
        *,
        traced: bool = True,
    ) -> asyncio.Task[_T]:
        """Register one operation's work as a task shutdown will drain.

        The half of :meth:`_tracked` that does not await, for a caller that needs
        the task itself, still inside the drain ADR-0042 §2 obliges.

        Args:
            work: The operation's own work, already wrapped in whatever measurement
                its caller owes.
            seam: Its name, for the trace.
            observe: How to read the result onto its trace, or ``None``.
            traced: Whether an ADR-0119 §8 operation trace is emitted.

        Returns:
            The registered task. It is *not* awaited here, and it is not shielded —
            a caller that wants either does it itself.
        """
        # ADR-0298 §2:6: the task may outlive the request — a shielded one runs on
        # after its caller is cancelled — so it starts with the requesting device
        # unset. A check it runs was handed the device the façade read at the call.
        task: asyncio.Task[_T] = without_requesting_device().run(
            asyncio.ensure_future,
            self._operation_traces.observing(seam, work, observe) if traced else work,
        )
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return task

    async def _uninterruptibly(self, coro: Awaitable[_T]) -> _T:
        """Run one step to completion even if this caller is cancelled, still tracked.

        :meth:`_tracked` without the tracing or the result measurement — for a step
        *inside* an unshielded operation that must not be torn in half. The task is
        registered in ``_inflight`` before it is awaited, so ADR-0042 §2's actual
        requirement holds for it: a cancel that abandons the caller leaves work that
        the shutdown drain still knows about and waits for, rather than a worker
        thread using a connection ``aclose`` is about to shut.

        Args:
            coro: The step to run to completion.

        Returns:
            Whatever ``coro`` returned.
        """
        task: asyncio.Task[_T] = without_requesting_device().run(asyncio.ensure_future, coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return await asyncio.shield(task)

    async def _checked_result(self, coro: Awaitable[_T], method: str) -> _T:
        """Await ``coro`` and measure what it produced, as one traced unit.

        The one-line adapter that puts :meth:`_checked` inside the region
        :meth:`_tracked` observes. It exists as a method rather than a closure so
        the wrapped coroutine is created eagerly by the caller and awaited exactly
        once, which is what keeps ``ensure_future``'s "never receives work it must
        throw away un-awaited" property true of the wrapper as well.

        Args:
            coro: The operation's work.
            method: The operation's name, for the refusal's own message.

        Returns:
            What ``coro`` produced.

        Raises:
            OversizedValueError: If the result exceeds the contract limit.
        """
        return self._checked(await coro, method)

    def _reject_if_closing(self) -> None:
        """Refuse new work once shutdown has begun (ADR-0042 §2 stops accepting).

        The message is :data:`ENGINE_SHUTTING_DOWN` rather than a literal, because
        ADR-0083 §8 makes the hub's scheduler act on *this* ``RuntimeError``
        specifically — as **stop**, not as a job failure to log and retry — and a
        caller that has to recognise it needs something to compare against that
        cannot drift from what is raised here.

        Raises:
            RuntimeError: If :meth:`aclose` has been entered.
        """
        if self._closing:
            raise RuntimeError(ENGINE_SHUTTING_DOWN)

    async def _controlled[P: PassFacts](
        self,
        working: P,
        stages: Sequence[ControllerStageRun[P]],
    ) -> None:
        """Run one pass's stages by ADR-0309 §3's table, recording on its state.

        The working set is carried on the activation's state while the pass runs
        (ADR-0280 §3), and the entries accumulate there, each appended to the open
        episode as its stage ends (ADR-0286 §3). A pass with no admitted activation
        still runs by the rules, into a record nothing writes.
        """
        state = active_state()
        record = StageRecord() if state is None else state.stages
        if state is not None:
            state.working = working
        await ActivationController(
            stages=stages,
            clock=self._clock,
            rules=ACTIVATION_RULES,
            appended=self._stage_appended,
            stopped=None if state is None else (lambda: state.stopped),
            # ADR-0314 §4:4, §5:4: the controller binds the admitted activation for
            # its run and writes its steps through the composition root's sink.
            activation_id=None if state is None else state.activation_id,
            diagnostics=self._diagnostics,
        ).run(working, record)
        if state is not None and state.stopped:
            # ADR-0297 §4: the controller left its loop on the stop and appended the
            # stop's end entry; nothing after the stages runs, and the call awaiting
            # the pass raises in its place.
            raise ActivationStoppedError(_STOPPED_MESSAGE)

    async def _windows_stage(self, working: _ActivationPass) -> None:
        """ADR-0282 §3: assemble the pass's windows before recall and understanding.

        The channel window is a turn's transcript, which the chat's reader brought its
        input in with (ADR-0293 §6:4), or what an event's channel supplied (ADR-0276
        §3). The episode window is the selector's choice, held as ids after the
        audience predicate. Its reads run inside the pass's deadline, and an expiry —
        the timer firing, or assembly that crossed the deadline and returned — is the
        classified timeout. It is not failure-tolerant: any other failure takes the
        fixed default.

        Raises:
            ModelTimeoutError: If the pass's deadline expired inside the stage.
        """
        assert self._windows is not None  # noqa: S101 — the engine refuses understanding without it
        try:
            async with asyncio.timeout_at(working.deadline):
                if isinstance(working, _TurnPass):
                    # ADR-0293 §6:4: the reader's window, the conversation's recent
                    # transcript.
                    channel: ChannelWindow = working.transcript
                else:
                    assert isinstance(working, _EventPass)  # noqa: S101 — the two pass kinds
                    channel = SuppliedWindow(working.input.context)
                windows = await self._windows.assemble(
                    channel, audience=working.supply, episodes=True
                )
        except TimeoutError:
            late = _windows_expired(working)
            if late is None:
                raise
            raise late from None
        # A timer fires only when the loop gets control, so assembly can cross the
        # deadline and return: that is the expiry too, and its decision is not made.
        if (late := _windows_expired(working)) is not None:
            raise late
        if isinstance(working, _TaskPass) and windows.episode_ids is not None:
            # ADR-0350 §6:5: the episodes the input links to, shown wherever frozen.
            windows = replace(
                windows,
                episode_ids=tuple(dict.fromkeys((*working.linked, *windows.episode_ids))),
            )
        working.windows = windows

    async def _fetch_held(self, working: _ActivationPass, windows: Windows) -> Fetched:
        """The window's and recall's records, fetched by id in one read (ADR-0282 §5).

        What was fetched and what came back missing is written on the working episode
        before the records are returned. Recall's ids are the ones its decision kept;
        a decision that kept none adds none.
        """
        recalled = working.recalled
        fetched = await fetch_held(
            self._memory,
            episode_ids=windows.episode_ids,
            recalled_ids=()
            if recalled is None
            else tuple(item.id for item in recalled.result.items),
            audience=working.supply,
        )
        working.understanding_fetch = fetched
        _log.info(
            "stage_fetch",
            stage="understanding",
            fetched=len(fetched.fetched),
            missing=len(fetched.missing),
        )
        return fetched

    async def _understand(
        self,
        input: ResolvedChannelInput,  # noqa: A002 — resolved channel input
        *,
        working: _ActivationPass,
    ) -> None:
        """Enter the understanding stage once, and carry what it records (ADR-0276 §5, §7).

        The version is minted one greater than the last on the activation's state and
        ``recorded_at`` read from this engine's clock; the record is carried on the
        state and written once, at capture. **Any raise out of the stage is
        ``failed``** — the stage was entered, which is what separates it from
        ``not_reached`` — and propagates unchanged: an ``UnderstandingError`` fails
        the activation as ``understanding_failed`` and a ``ModelError`` takes the row
        its class already takes (§6). Nothing is substituted for an understanding the
        stage could not obtain.

        **It reads what the working episode holds** (ADR-0282 §5): the windows the
        windows stage recorded, and the episode window's and recall's records fetched
        by id in one read — current versions, the audience predicate applied again, a
        missing one left out and recorded on the working episode.

        **It assembles the candidate stories first** (ADR-0300 §6:1-§6:4), where they
        are wired: the stories the episode window's fetched episodes belong to, each
        read as a short view, written on the working episode with what was fetched
        for them before the stage renders. A story store that cannot be read leaves
        none, and the stage proceeds. A version the stage records is written on the
        working episode as well as the state, where the story-links rule reads it.

        **It runs inside the pass's existing deadline** (§5): the fetch and both
        completions are bounded by what is left of the budget the call was handed,
        and a deadline that expires is a classified timeout — ``ModelTimeoutError``,
        the row a timed-out completion of this stage already takes (§6). A deadline
        that had already expired is raised **before** the stage is entered, so the
        record says ``not_reached`` rather than ``failed``. The stage itself starts no
        completion past it, and a stage that crossed it without the timer firing —
        work that never yielded — is judged by the deadline, not by what it returned.

        Args:
            input: The resolved activation input.
            working: The pass's working episode, holding the window decision, recall's
                decision, the audience posture and the deadline.

        Raises:
            ModelTimeoutError: If the deadline expired before the stage or inside it.
        """
        if self._understanding is None:
            return
        windows = working.windows
        assert windows is not None  # noqa: S101 — the windows row precedes understanding's wherever it is wired
        deadline = working.deadline
        state = active_state()
        loop = asyncio.get_running_loop()
        if deadline <= loop.time():
            raise ModelTimeoutError(_UNDERSTANDING_EXPIRED)
        # ADR-0332 §3:9-§3:10: the version covers the inputs held as the stage begins,
        # each one a merge brought read beside the trigger's.
        held = working.inputs_held
        joined = state.joined if state is not None else ()
        try:
            async with asyncio.timeout_at(deadline):
                person = await self._person_block(state, working)
                fetched = await self._fetch_held(working, windows)
                stories = await self._assembled_candidates(working, fetched)
                recalled = working.recalled
                # ADR-0349 §5:8: the in-progress section as it stands when the call is
                # rendered, read with no await before the stage renders it.
                running, more = self._in_progress(state, working)
                # ADR-0353 §5:2: every time is rendered in the person's zone, or the hub's
                # where they set none or the stimulus is no person's.
                own = None if person is None else person_zone(person.profile, stage="understanding")
                understood = await self._understanding.understand(
                    input.text,
                    channel=input.channel,
                    window=windows.channel,
                    audience=working.supply,
                    episodes=fetched.episodes,
                    version=1 if state is None else state.next_understanding_version(),
                    now=self._clock,
                    deadline=deadline,
                    recall=None if recalled is None else recalled.result,
                    recalled=fetched.recalled,
                    stories=stories,
                    # ADR-0351 §5:9: a relay mark an earlier version recorded holds for
                    # the rest of the activation, so this version records it too.
                    relayed=state is not None and relayed_by(state.understanding),
                    joined=joined,
                    running=running,
                    running_more=more,
                    person=person,
                    # ADR-0353 §3:1, §7:3: the stimulus is attributed and framed by its
                    # recorded trigger's parties and messages, and §5:2's zone is the
                    # person's own or the hub's.
                    trigger=None if state is None else state.trigger,
                    zone=self._task_zones.default if own is None else own,
                    own_zone=own is not None,
                    received_at=None if state is None else state.started_at,
                )
        except BaseException as exc:
            # A timer fires only when the loop gets control, so a stage can cross the
            # deadline without it firing — and then end in whatever the late work
            # raised. Past the deadline, a timeout, a model failure and an
            # unparseable output are all the expiry; anything else is not, and
            # propagates as itself.
            expired = deadline <= loop.time() and isinstance(
                exc, TimeoutError | ModelError | UnderstandingError
            )
            if state is not None:
                state.understanding_failed(TimeoutError() if expired else exc)
                # ADR-0349 §7:12, §7:15: an omission settles what waits on this one.
                self._matters.changed()
            if not expired:
                raise
        else:
            # The same, for a stage that crossed it and returned: what it produced is
            # not recorded, and the pass ends as any expiry inside does.
            expired = deadline <= loop.time()
            if expired and state is not None:
                state.understanding_failed(TimeoutError())
                self._matters.changed()
        if expired:
            # Outside the handler: the timer's own exception rides along as nothing.
            raise ModelTimeoutError(_UNDERSTANDING_EXPIRED) from None
        self._recorded_understanding(state, working, understood, covers=held)

    async def _person_block(
        self, state: ActivationState | None, working: _ActivationPass
    ) -> PersonBlock | None:
        """The activation's person block, assembled once, before understanding (§7:1).

        ADR-0338 §2:2-§2:4: the person is read from the recorded trigger, and an
        activation that is no person's — or a pass no channel admitted — is given none.
        The block is carried on the state, which every planning round reads, so an
        understanding run again for joined input reads the same block, less what the
        memory store no longer holds (§7:10). ``None`` where no person-model store is
        wired.
        """
        if self._person_blocks is None or state is None:
            return None
        if not state.person_block_assembled:
            state.person_block_assembled = True
            state.person_block = await self._person_blocks.assemble(
                activation_person(state.trigger), supply=working.supply
            )
        elif state.person_block is not None:
            # §7:10, for an understanding run again on joined input as for a planning
            # round: a memory forgotten since the block was assembled reaches no request.
            state.person_block = await still_held(state.person_block, self._memory)
        if state.person_block is not None:
            # ADR-0309 §5:10: what understanding is shown of the block is supply the
            # episode's placement inherits from, whether or not a round is planned.
            state.gave_person_memories(state.person_block.pinned)
        return state.person_block

    def _recorded_understanding(
        self,
        state: ActivationState | None,
        working: _ActivationPass,
        understood: ActivationUnderstanding,
        *,
        covers: int,
    ) -> None:
        """Carry a recorded version on the state and the working set (ADR-0276 §7).

        It covers ``covers`` inputs, those held as its stage began (ADR-0332 §3:9), and
        planning starts over for it (§3:12). The story-links rule reads it off the
        working set (ADR-0300 §6:11).
        """
        if state is not None and state.meant_for is not None:
            # ADR-0361 §6:3: an approval's input is meant for the asking activation, and
            # belongs to each matter it belongs to, by code's link; what understanding
            # named for it is not read.
            understood = understood.model_copy(
                update={
                    "continues": (state.meant_for,),
                    "story_links": (
                        StoryMember(kind=StoryMemberKind.ACTIVATION, id=state.meant_for),
                    ),
                }
            )
        if state is not None:
            state.understood(understood, limit=self._understanding_version_limit, inputs=covers)
            working.understanding = understood
            if working.phases is not None:
                working.phases.understood(understood.version, relayed=understood.relayed)
        working.understood = covers
        # ADR-0349 §7:12, §7:15: a recorded version may settle what waits on this one.
        self._matters.changed()

    def _in_progress(
        self, state: ActivationState | None, working: _ActivationPass
    ) -> tuple[tuple[InProgressEntry, ...], int]:
        """Understanding's in-progress section, read now, and how many more run (§5:2-§5:10).

        Every activation running for the same person on any place, newest first, under
        the pass's audience and ``in_progress_limit``. None for a pass no channel
        admitted, or whose author its place does not establish (§5:5).
        """
        if state is None:
            return (), 0
        return self._matters.in_progress(state, supply=working.supply)

    async def _assembled_candidates(
        self, working: _ActivationPass, fetched: Fetched
    ) -> Candidates | None:
        """ADR-0300 §6:1-§6:4: the candidate stories, written on the working episode.

        First the stories of the activations the place window's items link to, newest
        item first, as the stage will resolve its labels (ADR-0303 §7:9): the window the
        windows stage holds, with the links the sensor brought with it. Then the episode
        window's stories, looked up from the episodes the fetch admitted, in the
        window's order; a pass that takes no episode window has none of its own. Then
        recall's (§7): the stories its kept episodes belong to, as its decision recorded
        them, the item with the higher search score first, from the items whose records
        the same fetch admitted. What the assembly fetched and what came back missing
        ride on the decision (ADR-0282 §2:7). ``None`` where no assembler is wired, and
        then no section is rendered.
        """
        if self._story_candidates is None:
            return None
        recalled = working.recalled
        admitted = frozenset(record.id for record in fetched.recalled)
        windows = working.windows
        candidates = await self._story_candidates.assemble(
            fetched.episodes or (),
            audience=working.supply,
            recalled=() if recalled is None else recalled.stories(admitted),
            place=()
            if windows is None
            else place_window_links(
                windows.channel, audience=working.supply, episodes=fetched.episodes
            ),
        )
        working.story_candidates = candidates
        return candidates

    async def _story_links_stage(self, working: _ActivationPass) -> StageResult:
        """ADR-0300 §6:12-§6:13's story-links stage, failure-tolerant, for both pass kinds.

        It reads the latest recorded understanding's links off the working episode and
        records them in the story store, for the activation the state names. The
        decision is written on the working episode before the stage returns, so the
        rule that made it due does not answer again; a ``StoryStoreError`` is a
        ``failed`` decision returned ``tolerated`` with its error, and the pass goes on
        while its deadline holds (ADR-0281 §5). An activation with no id — capture
        degraded at admission — has no member to link, and decides that it linked
        nothing.

        Its writes run inside the pass's deadline, and an expiry is the classified
        timeout, as recall's is.

        Raises:
            ModelTimeoutError: If the pass's deadline expired inside the stage.
        """
        assert self._story_links is not None  # noqa: S101 — the rule makes the stage due only where it is wired
        understanding = working.understanding
        assert understanding is not None  # noqa: S101 — the rule makes the stage due only once a version is recorded
        state = active_state()
        activation_id = None if state is None else state.activation_id
        if activation_id is None:
            decision = StoryLinksDecision(outcome=StageOutcome.DONE)
        else:
            try:
                async with asyncio.timeout_at(working.deadline):
                    decision = await self._story_links.record(
                        understanding.story_links, activation_id=activation_id
                    )
            except TimeoutError:
                late = _story_links_expired(working)
                if late is None:
                    raise
                raise late from None
        working.story_links = decision
        if decision.outcome is StageOutcome.DONE:
            return StageResult(StageOutcome.DONE)
        return StageResult(decision.outcome, decision.error, tolerated=True)

    async def _recall_stage(self, working: _ActivationPass) -> StageResult:
        """ADR-0281's recall stage, failure-tolerant (§5), for a turn and an event alike.

        The decision is recorded on the working set and carried on the activation's
        state before the stage returns, so the rule that made it due does not answer
        again. A ``failed`` or ``timed_out`` decision is returned ``tolerated`` with
        its error, and the controller goes on to understanding while the pass's
        deadline holds.

        **Past the pass's deadline, whatever recall returned is the expiry** (§5). A
        search can cross the deadline without the timer firing — work that never
        yielded — and then return found, nothing found or failed. As the
        understanding stage does (ADR-0276 §5), what it produced is not recorded:
        the decision is ``timed_out`` with no items, and the stage returns the pass's
        own classified expiry, which the controller re-raises.
        """
        assert self._recall is not None  # noqa: S101 — the rule makes recall due only where it is wired
        windows = working.windows
        assert windows is not None  # noqa: S101 — the windows row precedes recall's wherever it is wired
        recalled = await self._recall.recall(
            working.text,
            audience=working.supply,
            deadline=working.deadline,
            # ADR-0282 §4: what the windows already hold is not recalled again.
            shown=windows.shared | frozenset(windows.episode_ids or ()),
        )
        late = _recall_expired(working)
        if late is not None:
            recalled = Recalled(
                ActivationRecall(outcome=RecallOutcome.TIMED_OUT, cues=recalled.result.cues),
                error=late,
            )
        working.recalled = recalled
        if (state := active_state()) is not None:
            state.recall = recalled.result
        outcome = _RECALL_STAGE_OUTCOMES[recalled.result.outcome]
        if outcome is StageOutcome.DONE:
            return StageResult(StageOutcome.DONE)
        return StageResult(outcome, recalled.error, tolerated=True)

    async def _phases_event_understanding_stage(self, event: _EventPass) -> None:
        """ADR-0276 §5's stage for an event the phases run, as a turn's is entered.

        Its failures propagate as themselves, a classified model timeout included: the
        pass ends on them and the event returns *couldn't finish* (ADR-0313 §4:5), so
        nothing maps them to the event-summary stage's errors.

        Raises:
            ModelTimeoutError: If the deadline expired before the stage or inside it.
        """
        await self._understand(event.input, working=event)

    async def _begin_conversation_stage(self, working: _TurnPass) -> None:
        """ADR-0074 §2: resolve the conversation before the turn's work, and bind it.

        An id the store does not know is refused here, before anything is routed or
        planned, exactly as it was refused before.
        """
        conversation = await self._conversations.begin(working.requested)
        if (state := active_state()) is not None:
            state.resolved_conversation(conversation.id)
        working.input = ResolvedChannelInput(
            channel=ChannelIdentity(channel_type="conversation", instance_id=conversation.id),
            text=working.utterance,
            modality=Modality.TEXT,
            context=working.context,
        )

    async def _understanding_stage(self, working: _TurnPass) -> None:
        """ADR-0276 §5's understanding stage, for a turn the phases plan.

        Its windows are the windows stage's (ADR-0282 §3), read off the working episode
        and filtered by this pass's audience (§3, §4). What it records is carried on the
        activation's state.

        Raises:
            ModelTimeoutError: If the deadline expired before the stage or inside it.
        """
        await self._understand(_resolved_turn(working), working=working)

    async def _takeover_stage(self, working: _ActivationPass) -> None:
        """ADR-0349 §7:4's takeover stage, once for each version naming any activation.

        **It first waits** (§7:15-§7:16), once, for each older activation running for the
        same person of this input's standing, until each has ended or recorded its first
        understanding version or its omission and, where that version names any
        activation, the takeover decision for it; what it waits for is what runs when the
        wait begins, and the wait is bounded by the pass's deadline, past which nothing is
        absorbed or offered and the stage ends as one whose deadline expired.

        **Then, in one step with no await between**
        (:meth:`~ai_assistant.orchestration.matters.Matters.merge`), it follows each
        activation named forward through absorptions and hand-overs; absorbs, all or none
        under ``held_input_limit``, those it reached that started before this one, run
        with their stop mark unset and their standing this input's, and have not
        committed (§7:5-§7:7); and offers its input to, or waits on, those that have acted
        (§7:17-§7:22). The decision is recorded for the version (§10:4), so
        ``takeover_undecided`` does not answer again.

        **An absorbed activation is stopped as a stop is** (§4:5, ADR-0297 §3): its marks
        are set in that step, and only then is its stop record written, inside the pass's
        deadline, with no cascade. A record that cannot be written is logged and the pass
        goes on: the marks are set, so the other activation runs no further stage and
        commits nothing. The stage is not entered past the deadline
        (:func:`_takeover_expired`).

        Raises:
            ModelTimeoutError: If the deadline passed during the wait, or had passed once
                it ended; nothing is absorbed or offered.
        """
        understanding = working.understanding
        assert understanding is not None  # noqa: S101 — the rule makes the stage due only once a version is recorded
        state = active_state()
        if state is None:
            # A pass no channel admitted is no one's to merge with (§5:3).
            working.undecidable.add(understanding.version)
            return
        if not await self._matters.before_takeover(state, working.deadline):
            raise ModelTimeoutError(_TAKEOVER_EXPIRED)
        # Read again with no await before the step: a wait that ended past the deadline
        # absorbs nothing (§7:16).
        if working.deadline_passed:
            raise ModelTimeoutError(_TAKEOVER_EXPIRED)
        decided, absorbed = self._matters.merge(state, understanding, at=self._now())
        state.takeovers[understanding.version] = decided
        self._matters.changed()
        _log.info(
            "activation_takeover",
            stage="takeover",
            named=len(decided),
            absorbed=len(absorbed),
            offered=sum(one.became is Became.OFFERED for one in decided),
            waited=sum(one.became is Became.WAITED_ON for one in decided),
        )
        for activation_id in absorbed:
            await self._matters.record_stop(
                activation_id, deadline=working.deadline, stage="takeover"
            )

    async def _beliefs(
        self,
        *,
        bands: tuple[BeliefBand, ...] | None,
        kinds: tuple[MemoryKind, ...] | None,
        limit: int,
        offset: int,
    ) -> tuple[BeliefSummary, ...]:
        """Relay the enumeration to the store and summarise each memory (ADR-0328 §15:1).

        The filter arrives already materialised by :meth:`beliefs`; the page's order
        and membership are the store's, and this adds no re-ordering, no re-filtering
        and no count of its own. Its supports' episodes are resolved in one read for
        the page, so each summary can say whether none of them resolves (§15:7).
        """
        records = await self._memory.list_beliefs(
            bands=bands, kinds=kinds, limit=limit, offset=offset
        )
        reading = await self._support_contents(
            [record for record in records if isinstance(record, Memory)]
        )
        now = self._clock()
        return tuple(
            belief_summary(record, now=now, supports_gone=reading.all_gone(record))
            if isinstance(record, Memory)
            else episode_summary(record)
            for record in records
        )

    async def _belief(self, record_id: str) -> Belief | None:
        """Read one live record and project it, or report that there is none."""
        record = await self._memory.get(record_id)
        if record is None:
            return None
        if not isinstance(record, Memory):
            return episode_view(record)
        reading = await self._support_contents((record,))
        return belief_view(
            record,
            now=self._clock(),
            contents=reading.contents,
            supports_gone=reading.all_gone(record),
        )

    async def _support_contents(self, memories: Sequence[Memory]) -> _SupportReading:
        """Resolve each support's part to readable content at presentation (ADR-0328 §15:2).

        **Lazily, here, and without rewriting anything** (ADR-0077 §6, kept by §15:7).
        Each part reads as the content of that part on its episode's record — the input
        or one of its messages, a round's message, a digest's evidence item, the
        statement a confirmed question part showed, a remember call's statement — and
        as gone (``None``) where the episode no longer resolves or holds no such part
        (:mod:`~ai_assistant.orchestration.support_parts`). A legacy part reads as the
        content of the record it carries (§16:4).

        Every episode the memories point into, the asking activations' included, is read
        through **one** :meth:`~ai_assistant.core.protocols.MemoryStore.get_many`
        (ADR-0086 §6), and the effect records their remember calls are claimed under
        through one :meth:`~ai_assistant.core.protocols.PlanStore.activation_effects`,
        so every support is judged against one state of each store.

        Resolution happens at this façade rather than in `interfaces/`, which golden
        rule 3 keeps thin.
        """
        wanted = episodes_to_read(memories)
        found = await self._memory.get_many(wanted) if wanted else {}
        episodes = {
            record_id: record
            for record_id, record in found.items()
            if isinstance(record, EpisodicMemory)
        }
        activations = remember_activations(memories, episodes)
        effects = (
            {effect.id: effect for effect in await self._plans.activation_effects(activations)}
            if activations
            else {}
        )
        asked = requests_to_read(memories)
        requests = (
            {str(one.id): one for one in await self._plans.approval_requests(list(asked))}
            if asked
            else {}
        )
        contents: dict[SupportPart, str | None] = {}
        for memory in memories:
            for support in memory.supports:
                contents[support.points_at] = part_content(
                    support.points_at,
                    episodes=episodes,
                    effects=effects,
                    carried=support.carries,
                    requests=requests,
                )
        return _SupportReading(contents=contents, held=frozenset(episodes))

    def _checked(self, result: _T, method: str) -> _T:
        """Refuse a result the contract does not admit, before returning it (§8c).

        ADR-0084 §4 puts the limit on **both** directions, so an oversized
        ``Belief.evidence`` coming back is refused exactly as an oversized utterance
        going in — otherwise the in-process engine would hand a caller a value the
        client standing in for it provably cannot deliver.

        Measured on the canonical encoding rather than on a cheaper proxy, because
        the boundary is contract-visible: a caller catches
        :class:`~ai_assistant.core.errors.OversizedValueError` and branches on it, so
        two implementations refusing different sets is a disagreement about the
        contract. ADR-0087 §7 permits "any cheaper test that refuses exactly the same
        set", and this is not one — it is the definition, which is the right thing
        for the implementation the conformance suite measures the others against.

        **On a mutating call this runs after the work has committed, and the effect
        stands.** The old path's ``converse`` was the case: a turn that ran a tool,
        persisted its execution and captured the exchange, and only then produced an
        outcome too large to carry, raised here with all of that already durable. That
        is not an ordering this lane chose and it is not one it can fix: no measurement
        of a *result* can precede producing it, and a wire client meets the identical
        situation one frame further out — the hub runs the turn and then cannot send
        what came back.

        **ADR-0085 §8e names this residual and declines to design around it.** The
        unbounded factor is ``Belief.evidence`` under `REINFORCE` (#473), which
        ADR-0084 §11 makes a prerequisite of the *client* lane rather than of this
        one, and §8e records that until that bound lands "the bad state is
        unreachable rather than provably unreachable". What the contract adds is that
        the failure arrives as a typed error naming the limit, the measured size and
        the largest contributing member — "a sentence a user can read and act on,
        rather than a frame that will not send".

        **Nothing is lost, and where to look for it is the part worth stating.** The
        effect is durable and inspectable by exactly the reads this surface already
        offers: the conversation was captured, so ``conversation`` and
        ``recent_conversations`` show it; anything memory folded is on ``beliefs``;
        the execution state is in the plan store. The caller cannot *re-derive* the
        outcome value, and that gap is tracked in #570 rather than closed here,
        because closing it means either bounding the result before the work (which is
        #473's) or adding a recovery method to a `core` Protocol, which no ADR
        ratifies and this lane may not author.
        """
        check_payload(
            result, max_bytes=self._max_payload_bytes, subject=f"the result of {method}()"
        )
        return result

    def _check_page(self, method: str, *, limit: int, offset: int) -> None:
        """Refuse a malformed page argument locally, then measure the call (§3a, §9).

        The two paging arguments are refused **before any I/O**, so both
        implementations refuse the same values without a round trip and neither is
        silently more permissive. ``limit`` is deliberately absent from the measured
        argument object: it is what a caller *omits* to get
        :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`, and an argument the
        caller did not pass is absent rather than ``null`` (ADR-0085 §10).
        """
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(method, max_bytes=self._max_payload_bytes, limit=limit, offset=offset)


# --- the hub page's approvals panel, read once for the engine and the fake ------------
#
# ADR-0361 §4:6: the panel shows each request as its card shows it, by the one renderer
# every surface shows a request by (§2:11, ``approval_calls.card_text``), handed what the
# request does not record: where the asking work came from, and whether it had read
# outside content. The engine and the canonical fake both answer through these, so the
# suite compares two implementations of the surface rather than two readings of a card.

#: Reads what each request's card shows beside it, by the request's id.
type CardFactsReader = Callable[[Sequence[ApprovalRequest]], Awaitable[Mapping[str, CardFacts]]]

#: What a card shows where the asking activation cannot be read: where it was asked is
#: not recorded, and the outside-content line is shown, the cautious reading.
_UNREAD_FACTS: Final = CardFacts(origin=None, read_outside=True)


def approval_card_facts(
    request: ApprovalRequest,
    trigger: RecordedChannelTrigger | None,
    calls: Sequence[RecordedCall],
) -> CardFacts:
    """What a request's card shows beside it, from the activation that asked (§2:11).

    Where its input came from, by its trigger's channel; and whether it had read outside
    content, by whether its ``request_approval`` entries in the request's round rest on
    outside content (ADR-0356 §8:7). A round holding no such entry, as one not yet
    recorded, shows the outside line: the cautious reading, as the line's card reads an
    episode after a start.

    Args:
        request: The request.
        trigger: The asking activation's recorded trigger, or ``None`` where it cannot
            be read.
        calls: The calls its rounds recorded.

    Returns:
        The facts.
    """
    if trigger is None:
        return _UNREAD_FACTS
    target = trigger.channel or trigger.target
    entries = [
        one
        for one in calls
        if one.round == request.round and one.capability == REQUEST_APPROVAL_CAPABILITY
    ]
    return CardFacts(
        origin=target if isinstance(target, ChannelIdentity) else None,
        read_outside=not entries or any(one.marked for one in entries),
    )


async def episode_card_facts(
    memory: MemoryStore, requests: Sequence[ApprovalRequest]
) -> dict[str, CardFacts]:
    """What each request's card shows beside it, from the asking activation's episode.

    One batch read. An episode that cannot be read, is not held, or holds no processing
    record shows :data:`_UNREAD_FACTS`, so a store that fails still lets the panel show
    and answer the request, whose call and ``why`` are the request's own.

    Args:
        memory: The memory store the episodes are held in.
        requests: The requests.

    Returns:
        The facts, by request id.
    """
    addresses = {str(one.id): f"activation:{one.activation_id}" for one in requests}
    try:
        records = await memory.get_many(list(dict.fromkeys(addresses.values())))
    except MemoryStoreError:
        _log.warning("approval_facts_unread", stage="approvals", reason="store_failed")
        records = {}
    facts: dict[str, CardFacts] = {}
    for one in requests:
        record = records.get(addresses[str(one.id)])
        processing = record.processing_record if isinstance(record, EpisodicMemory) else None
        facts[str(one.id)] = (
            _UNREAD_FACTS
            if processing is None
            else approval_card_facts(one, processing.trigger, processing.call_records)
        )
    return facts


def approval_panel_entry(
    request: ApprovalRequest, facts: CardFacts, *, now: datetime
) -> ApprovalPanelEntry:
    """One request as the panel shows it: as its card shows it, at ``now`` (§4:6).

    Args:
        request: The request, as the store holds it.
        facts: What its card shows beside it.
        now: The instant it is shown at, which its state is read at.

    Returns:
        The entry.
    """
    answer = request.answer
    return ApprovalPanelEntry(
        request_id=request.id,
        text=card_text(request, facts, now=now),
        state=ApprovalCardState(card_state(request, now=now)),
        written_at=request.written_at,
        expires_at=request.expires_at,
        answered_by=None if answer is None else answer.who,
        answered_at=None if answer is None else answer.at,
    )


def _ended_at(request: ApprovalRequest) -> datetime:
    """When a request stopped waiting: its tap, or its expiry."""
    return request.expires_at if request.answer is None else request.answer.at


async def approval_panel(
    plans: PlanStore,
    facts_of: CardFactsReader,
    *,
    person: str,
    now: datetime,
    limit: int,
) -> ApprovalPanel:
    """The person's requests, as the hub page's approvals panel shows them (§4:6).

    The pending ones, the oldest first, and the ones answered or expired most recently,
    the most recent first, at most ``limit`` of each. A request still pending at or
    after its expiry is shown expired among the recent ones: no tap can approve it now
    (§3:5), whether or not the sensor has ended it.

    Args:
        plans: The plan store, which holds the Approvals channel's content.
        facts_of: Reads what each request's card shows beside it.
        person: The person whose requests are shown.
        now: The instant the panel is read at.
        limit: The most entries each list holds.

    Returns:
        The panel.

    Raises:
        PlanningError: If the plan store cannot be read.
    """
    held = await plans.person_approval_requests(person, tuple(ApprovalRequestState))
    waiting = sorted(
        (one for one in held if card_state(one, now=now) == "pending"),
        key=lambda one: one.written_at,
    )[:limit]
    ended = sorted(
        (one for one in held if card_state(one, now=now) != "pending"),
        key=_ended_at,
        reverse=True,
    )[:limit]
    facts = await facts_of((*waiting, *ended))
    return ApprovalPanel(
        pending=tuple(approval_panel_entry(one, facts[str(one.id)], now=now) for one in waiting),
        recent=tuple(approval_panel_entry(one, facts[str(one.id)], now=now) for one in ended),
    )


async def tap_on_approval_panel(  # noqa: PLR0913 — the store, the reader, the tap, and its person and instant
    plans: PlanStore,
    facts_of: CardFactsReader,
    request_id: str,
    choice: ApprovalChoice,
    *,
    person: str,
    now: datetime,
) -> tuple[ApprovalPanelTap, bool]:
    """Carry out a tap on the panel, as the hub page's ``ApprovalGiver`` (§4:8-§4:9).

    The request is read first, and a tap on one that is not ``person``'s changes
    nothing and shows nothing of it (§4:8). Otherwise it is marked approved or denied,
    with the tap's instant, in the store's one step that refuses where the request is no
    longer pending, so the first tap to land wins and a later one is answered with the
    request's state.

    Args:
        plans: The plan store.
        facts_of: Reads what the request's card shows beside it.
        request_id: The request tapped.
        choice: Approve or Deny.
        person: The person tapping, whom the request must be for.
        now: The tap's instant.

    Returns:
        What the tap came to, and whether a store step landed that the sensor is woken
        for: this tap's mark, or a tap past the request's expiry, which the sensor ends
        expired at its next look (§3:5).

    Raises:
        PlanningError: If the plan store cannot be read or written.
    """
    found = await plans.approval_requests([request_id])
    if not found or found[0].person != person:
        return ApprovalPanelTap(answer=ApprovalPanelTapAnswer.UNKNOWN), False
    state = (
        ApprovalRequestState.APPROVED
        if choice is ApprovalChoice.APPROVE
        else ApprovalRequestState.DENIED
    )
    step = await plans.answer_approval_request(
        request_id, state, ApprovalTap(who=ApprovalGiver.USER_TAP_ON_HUB_PANEL, at=now)
    )
    facts = await facts_of((step.request,))
    entry = approval_panel_entry(step.request, facts[str(step.request.id)], now=now)
    if step.answer is ApprovalStepAnswer.CHANGED:
        answer = ApprovalPanelTapAnswer.ANSWERED
    elif entry.state is ApprovalCardState.EXPIRED:
        answer = ApprovalPanelTapAnswer.EXPIRED
    else:
        answer = ApprovalPanelTapAnswer.ALREADY_ANSWERED
    landed = step.answer in {ApprovalStepAnswer.CHANGED, ApprovalStepAnswer.PAST_EXPIRY}
    return ApprovalPanelTap(answer=answer, entry=entry), landed


__all__ = [
    "CardFactsReader",
    "Engine",
    "approval_card_facts",
    "approval_panel",
    "approval_panel_entry",
    "conversation_summary",
    "episode_card_facts",
    "tap_on_approval_panel",
]
