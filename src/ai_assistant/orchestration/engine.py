"""The engine façade an interface adapter drives (ADR-0042 §1, §3, §4).

:class:`Engine` is the single, concrete surface `interfaces/` depends on. It is
**not** a Protocol (ADR-0042 §1): there is one orchestration engine and one class
of consumer, so a contract modelling substitutability would encode a
substitutability that does not exist, and pay a triad's cost for it. The stage
objects — :class:`~ai_assistant.orchestration.loop.LearningLoop` and
:class:`~ai_assistant.orchestration.runner.StepRunner` — become collaborators the
façade *composes*, addressable to the adapter only through the façade's own
methods (ADR-0042 §1). Sequencing them is the orchestration this package owns; an
adapter doing it would pull pipeline logic into `interfaces/` (ADR-0042
Alternatives).

Two call shapes, mirroring the two the engine already has (ADR-0042 §3):

* :meth:`Engine.converse` runs one turn and drives the step it produces;
* :meth:`Engine.resume` answers a parked confirmation and continues that step.

Both return a :class:`TurnOutcome` — one result in, one result out. What the
adapter may and may not do with it is ADR-0042 §6: it renders the content,
collects the human's yes/no, and relays an **opaque** :class:`ContinuationToken`;
it never authors a permission outcome, and it never inspects the token.

Beside them sit the two non-turn legs, each its own result DTO: :meth:`Engine.learn`
folds one piece of feedback into memory (:class:`LearnOutcome`), and the
**inspection surface** — :meth:`Engine.beliefs`, :meth:`Engine.belief` and
:meth:`Engine.forget` — lets a person read what the assistant believes about them
and destroy any of it (:class:`Belief`; ADR-0073 §7). Inspection is where
:func:`~ai_assistant.core.types.band_of` is applied, **once**: classifying a record
into its band is ADR-0072 §1's projection, and an adapter doing it would put that
projection in `interfaces/` (ADR-0073 §7).

:meth:`Engine.observe` is the third non-turn leg (ADR-0077 §8): the *passive* half
of accumulation, where ``learn`` is the dictated one. It reads a bounded batch of
a conversation's episodes, has the injected ``Observer`` propose what they justify
believing, and puts each proposal through the same write path ``learn`` uses —
returning an
:class:`~ai_assistant.orchestration.observation.ObservationReport`. It is
deliberately explicit: nothing triggers it but a caller — the CLI, or the hub's
scheduler as a second caller of the same operation, unchanged and **disabled by
default** until the observation cursor lands (ADR-0083 §7, §13).

Beside those sits the **maintenance surface** ADR-0083 §8 adds for that scheduler:
:meth:`Engine.start`'s sweeps, :meth:`Engine.purge_expired`,
:meth:`Engine.ingest_calendar`, :meth:`Engine.ingest_email` and
:attr:`Engine.drain_phase`. New *concrete* surface on this class rather than
``core`` contract surface — the scheduler holds this object from inside the hub,
not the ``AssistantEngine`` Protocol a client sees, whose fifteen methods
ADR-0085 §1 fixes and none of these is among.

:meth:`Engine.ingest_calendar` is that surface's second scheduled operation and
leg 6's (ADR-0093 §6); :meth:`Engine.ingest_email` is ADR-0140's, added beside it
rather than through it. **One operation per ingestion source, and no ingestion
operation takes a source** (ADR-0142 §4): each reads the injected
:class:`~ai_assistant.core.protocols.Reader` once and puts every belief the
reading proposes through the same write path ``learn`` and ``observe`` use,
because ADR-0093 §1 declines the capture exemption to a reader and a third
party's report is the last thing that should reach the store unmediated. Each is
**optional collaborator, required behaviour**: a reader ships disabled by default
(§7), so an engine wired without one is the ordinary deployment — and asking it
to ingest that source is then a wiring fault it refuses rather than an empty
success it reports, per source and naming that source's own configuration
(ADR-0142 §6).

**Scope today.** ``respond`` "still ends at the plan" and the multi-step
plan-driving stage — ordering, dependencies and cancellation across a plan's
steps — is "the next slice" (`loop.py`). So a turn drives **at most one** step,
the plan's first, through the already-built :class:`StepRunner`; the rest await
that stage. This is the transitional reach ADR-0042 §3 names when it says
per-attempt and per-request coincide "today", and §7's "the CLI's reach grows
with the engine's". The *contract* — these signatures and DTOs — is fixed now, so
the adapter is not rewritten as those stages land.

Nothing concrete is imported: every collaborator arrives by injection and is seen
only through its Protocol or through this package's own stage objects (CLAUDE.md
golden rule 1). The wiring that constructs the concrete subsystems is the
composition root's, a separate package (ADR-0042 §2).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from itertools import count
from typing import TYPE_CHECKING, Any, Final, TypeVar, assert_never

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    MemoryStoreError,
    MemoryStoreStaleError,
    NotificationBudgetError,
    OversizedValueError,
    PlanningError,
    SpeechError,
    TraceStoreError,
    TranscriptionFailedError,
    UngrantableActError,
    UnknownContinuationError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    Belief,
    BeliefSummary,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    ConversationSummary,
    CoverageUnrecordedBinding,
    DeferralAdmissionOutcome,
    Disposition,
    Evidence,
    ExchangeDisposition,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryDecisionKind,
    MemoryKind,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    NotificationDelivery,
    OperationConfirmation,
    OriginUnrecordedBinding,
    ParkedBinding,
    Placement,
    PlacementReach,
    PlacementSetter,
    QueuedQuestion,
    QueueOutcome,
    ReplyChunk,
    RoutableOperation,
    RouteApproval,
    RoutedOperation,
    RoutedOperationRecord,
    RouteOutcome,
    SpeechFailure,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryState,
    SpokenRendering,
    SpokenTurn,
    StepOutcome,
    StepStatus,
    TraceOutcome,
    TurnOutcome,
    TurnResult,
    band_of,
    describe_untrusted,
    is_live_confirmation_park,
    rests_on_recorded_external_content,
    secret_value,
)
from ai_assistant.orchestration.composing import ComposedReply
from ai_assistant.orchestration.disclosure import (
    BoundedAudienceSupply,
    TurnSupply,
    UnboundedAudienceSupply,
    notification_is_speakable,
)
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.orchestration.notifications import hand_off
from ai_assistant.orchestration.origin import SelectionOrigin
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    JSON_STRING_QUOTE_BYTES,
    canonical_payload,
    check_arguments,
    check_payload,
    check_provisioning_call,
    encoded_text_bytes,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
)
from ai_assistant.orchestration.questions import question_state
from ai_assistant.orchestration.routing import (
    FORGET_LOOKUP_KINDS,
    Resolved,
    RoutingStage,
)
from ai_assistant.orchestration.routing import (
    perform as perform_route,
)
from ai_assistant.orchestration.routing import (
    resolve as resolve_route,
)
from ai_assistant.orchestration.speech import (
    DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
    SPOKEN_PARK_SENTENCE,
    classify_speech_failure,
    synthesize_within,
    transcribe_within,
)
from ai_assistant.orchestration.traces import Observation, OperationTraces

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        AuditTrail,
        DeferralStore,
        MemoryStore,
        NotificationPolicy,
        NotificationStore,
        PlanStore,
        SourceReadTrail,
        SpeechSynthesizer,
        SpeechTranscriber,
        SpendLedger,
        TraceRetention,
        TraceSink,
        TranscriptArchive,
    )
    from ai_assistant.core.types import (
        ActionPlan,
        AnswerOutcome,
        BeliefBand,
        ConnectedAccount,
        ConnectionAct,
        Conversation,
        ConversationDigest,
        DeferralAdmission,
        DurableIdentifier,
        EncodableText,
        FeedbackEvent,
        FrozenJsonMapping,
        GrantableSource,
        GrantScope,
        HeldNotification,
        Identifier,
        MemoryRecord,
        NonBlankEncodableText,
        NotificationCandidate,
        NotificationDisposition,
        NotificationPreferences,
        ObservationReport,
        PermissionDecision,
        Question,
        RecipientGrant,
        RecipientGrantOutcome,
        RecordedInvocation,
        RoutedListing,
        SecretValue,
        SourceGrant,
        SourceReadRecord,
        SpendTotal,
        SpokenAudio,
        SpokenDeliveryReport,
        TranscriptArchiveSize,
        TranscriptEntry,
        TranscriptHit,
        UtcInstant,
    )
    from ai_assistant.orchestration.composing import ComposingStage
    from ai_assistant.orchestration.connections import ConnectionOperations
    from ai_assistant.orchestration.consolidation import (
        ConsolidationReport,
        ConsolidationStage,
    )
    from ai_assistant.orchestration.conversations import ConversationLifecycle
    from ai_assistant.orchestration.delivery import DeliveryOutbox
    from ai_assistant.orchestration.grants import GrantOperations
    from ai_assistant.orchestration.ingestion import IngestionReport, IngestionStage
    from ai_assistant.orchestration.loop import LearningLoop
    from ai_assistant.orchestration.observation import ObservationRunReport, ObservationStage
    from ai_assistant.orchestration.questions import QuestionStage
    from ai_assistant.orchestration.recipient_grants import RecipientGrantOperations
    from ai_assistant.orchestration.recovery import RecoveryScan
    from ai_assistant.orchestration.routing import RoutedRoute
    from ai_assistant.orchestration.runner import (
        EstablishingAnswer,
        StepDisposition,
        StepRunner,
    )
    from ai_assistant.orchestration.upcoming import UpcomingEventStage
    from ai_assistant.orchestration.writes import WriteOutcome

_log = structlog.get_logger(__name__)

#: The one-character reply :meth:`Engine._reply_room` measures a probe outcome with.
#: Its own encoding is subtracted straight back out, so the character is arbitrary
#: — what it has to be is *something*, since
#: :data:`~ai_assistant.core.types.NonBlankEncodableText` has no spelling for the
#: empty answer and a ``None`` reply would encode as ``null`` rather than a string.
_ROOM_PROBE: Final[str] = "x"

#: ``Settings.routed_confirmation_ttl``'s own default, restated where the invariant
#: is used so an engine built in a test that reads no setting still has a bounded
#: routed park (ADR-0197 §7). A routed park is invisible — ``pending_confirmations``
#: does not list it and no durable store recovers it — so without a lifetime a client
#: that disconnected between the park and its token would hold a ceiling slot nothing
#: could ever free.
_DEFAULT_ROUTED_CONFIRMATION_TTL: Final = timedelta(minutes=15)

#: How many times a colliding ``route_id`` is retried from the injected factory inside
#: the reserving critical section before the pass gives up (ADR-0197 §9). Small,
#: because the budget exists for a *repeating* factory rather than for a collision
#: probability: a random factory does not reach two, and a factory that repeats every
#: value is not made to work by trying it eight more times. Exhausting it ends the pass
#: in ``UNRECORDED`` with nothing reserved, nothing parked, no row written, no token
#: minted and the operation never called.
_ROUTE_ID_ATTEMPTS: Final = 8


def _note_failure(turn: asyncio.Task[TurnOutcome]) -> None:
    """Observe a finished streaming turn's failure, whether or not anyone read it.

    A turn abandoned by its client (ADR-0173 §9) runs on and may still fail, and its
    exception would otherwise reach asyncio's unretrieved-exception reporter at some
    later collection with no context. Retrieving it here logs it once, at the moment
    it happened, and leaves ``result()`` free to re-raise it for a caller that *is*
    still reading.
    """
    if turn.cancelled():
        return
    failure = turn.exception()
    if failure is not None:
        _log.warning("streamed_turn_failed", exc_info=failure)


_T = TypeVar("_T")


def _elapsed_since(started: datetime, now: datetime) -> timedelta:
    """How long a poll has run, never negative.

    A clock that steps backwards would otherwise lengthen the budget rather than
    spend it, and on a maximal budget the subtraction against it would overflow.
    """
    elapsed = now - started
    return max(elapsed, timedelta(0))


#: Default ceiling on unanswered parked confirmations held in memory (see
#: :class:`Engine`). Generous enough that a real interactive session never reaches
#: it, low enough that an abandoning client cannot exhaust memory.
_DEFAULT_MAX_OUTSTANDING = 1024

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
class PurgeReport:
    """What one retention sweep physically reclaimed (ADR-0083 §7, §8).

    The result of :meth:`Engine.purge_expired`, which is **one** job over **three**
    stores because ADR-0078 §10 item 8 says so in as many words: the deferral
    queue's purge "is wired wherever ``purge_expired`` is wired and inherits the
    same fate", and "inventing a second sweeping mechanism for one store would be
    the thing that has to be undone at leg 5". ADR-0119 §10 sends the trace store
    to the same place — "the trace purge becomes the third call behind that same
    operation" — rather than giving the seventh database a job of its own.

    The first two counts are reclamation, not visibility: both Tier 1 stores
    already hide what is past its deadline at *read* time (ADR-0007 §2, ADR-0078
    §6), so a sweep that never runs costs the exposure cap ADR-0078 §1 names and
    costs nothing else. The third is different, and ADR-0119 §10 says why: "the
    horizon is enforced by deletion only… there is no read-time retention filter",
    so what this sweep does not delete is what a walk still returns.

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
    #: Purgeable deferred-question rows removed.
    questions: int
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


def _uuid() -> str:
    return str(uuid.uuid4())


def _check_positive_int(value: int, *, name: str) -> None:
    """Refuse a constructor knob that is not a positive integer.

    Three of this façade's knobs are counts or byte bounds, and each fails *open and
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
        "questions": report.questions,
    }
    if report.traces is not None:
        metrics["traces"] = report.traces
    if report.notifications is not None:
        metrics["notifications"] = report.notifications
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


def _ingested(report: IngestionReport) -> Observation:
    """Read one scheduled ingestion onto its own ``OPERATION`` trace (ADR-0119 §8).

    **The report's two string-shaped fields are deliberately left off.** §2 admits
    no string into a trace that is not an identifier, an enum member, a literal
    written here or an exception's class name, and
    :attr:`~ai_assistant.orchestration.ingestion.IngestionReport.source` is none of
    those — it is a reader's declared identity, read at runtime. ``read_at`` is a
    ``datetime``, which the metric map's value type does not admit at all. Neither
    is a loss the envelope feels: the seam says which operation this was, and
    ``occurred_at`` says when.

    Args:
        report: What the reading proposed and what memory did with it.

    Returns:
        The four counts that partition the proposals.
    """
    return Observation(
        metrics={
            "proposed": report.proposed,
            "stored": report.stored,
            "deferred": report.deferred,
            "rejected": report.rejected,
        }
    )


def _consolidated(report: ConsolidationReport) -> Observation:
    """Read one consolidation run onto its own ``OPERATION`` trace (ADR-0119 §8).

    **A halted run is ``INCOMPLETE``, which is the only place the fourth outcome
    is produced.** ADR-0111 §9's third clause rules that "a run that halts under §5
    without processing its remaining work is recorded as a completed run that did
    not exhaust its work, not as a failure", and ADR-0119 §3 calls ``INCOMPLETE``
    that clause "given a value": recording a halt as ``OK`` makes a job that has
    stopped making progress invisible, and recording it as ``FAULT`` makes a queue
    at its cap indistinguishable from a broken store.

    ``halted`` is therefore **not** also a metric. The outcome carries it, and a
    second copy is a second thing to disagree with the first —
    :attr:`~ai_assistant.orchestration.consolidation.ConsolidationReport.exhausted`
    is a different fact and is carried, because a run that spent its budget and one
    that halted are distinguishable only through the pair.

    Args:
        report: What the run examined, proposed and recorded.

    Returns:
        The run's counters, and ``INCOMPLETE`` if it halted.
    """
    return Observation(
        outcome=TraceOutcome.INCOMPLETE if report.halted else TraceOutcome.OK,
        metrics={
            "chunks": report.chunks,
            "examined": report.examined,
            "proposed": report.proposed,
            "committed": report.committed,
            "deferred": report.deferred,
            "rejected": report.rejected,
            "discarded_unusable": report.discarded_unusable,
            "discarded_over_limit": report.discarded_over_limit,
            "refused_self_citing": report.refused_self_citing,
            "exhausted": report.exhausted,
        },
    )


def _observed(report: ObservationReport) -> Observation:
    """Read one **interactive** observation pass onto its own trace (ADR-0222 §9).

    **The asymmetry this closes was not a decision, which is why it is closed here
    in passing.** A scheduled run has carried a twelve-metric reading since ADR-0218
    (:func:`_observed_due`), while a hand-run pass was tracked with no mapper at all
    and therefore recorded empty metrics — so the denominator of any per-pass figure
    was readable for the scheduler and not for the user. ADR-0222 §9 names that "cheap
    to close", and closing it is the whole of the mechanism that ADR owes: the
    act-record share and the laundering count it defines are a **reading of proposal
    content** in a QA pass, and no field, flag or enum member is added to carry
    either.

    **Only counts the report already carries** (ADR-0222 §5's closing clause, which
    is what makes this hook lawful where §5's own elision counts are not). Every
    value below is a field of
    :class:`~ai_assistant.core.types.ObservationReport` or a property it defines:
    ``proposed`` is the length of the entries it returned and ``stored`` is its own
    property for how many left a record live. Nothing here re-derives a rule that
    lives in :mod:`ai_assistant.orchestration.observation` — a second statement of
    which rulings count as committing is a second thing to disagree with the first —
    and nothing here reaches for content, which ADR-0119 forbids a trace to carry at
    all.

    **No outcome, because there is no second one to reach.** A pass that raises
    propagates and takes ``_tracked``'s fault path; a pass that returns is ``OK``,
    which is the default, and stating it again here would be a second place for the
    two to disagree. That is the difference from :func:`_consolidated`, whose
    ``INCOMPLETE`` is a real fourth state ADR-0111 §9 gives a value.

    Args:
        report: What the pass read, proposed, and what memory did with it.

    Returns:
        The pass's own counts, on the operation's own trace.
    """
    return Observation(
        metrics={
            "episodes_read": report.episodes_read,
            "proposed": len(report.proposals),
            "stored": report.stored,
            "dropped_unsupported": report.dropped_unsupported,
            "discarded_unusable": report.discarded_unusable,
            "discarded_over_limit": report.discarded_over_limit,
        }
    )


def _observed_due(report: ObservationRunReport) -> Observation:
    """Read one scheduled observation run onto its own ``OPERATION`` trace (ADR-0119 §8).

    **Always ``OK``, and there is no fourth outcome to reach here.** ADR-0218 §3
    gives a returning run exactly two terminal reasons — the listing it last read
    held no due candidate, or the budget was spent — and §9 makes both *successful*:
    "A run whose passes all complete but which observed nothing […] is a
    **successful** run." The third disposition a reader might look for does not
    exist as a return value at all: a run whose pass raises propagates and returns
    no report, so it reaches this projection never and ``_tracked``'s fault path
    always.

    ``budget_spent`` is carried as a metric rather than as an outcome for exactly
    that reason. It is not ``ConsolidationReport.halted``'s analogue — a halt is a
    chunk that could not be recorded, where this is a bound working as designed —
    so recording it as ``INCOMPLETE`` would report a job doing its job as a job that
    stopped short.

    Args:
        report: What the run performed, read and ruled.

    Returns:
        The run's counters, and ``OK``.
    """
    return Observation(
        outcome=TraceOutcome.OK,
        metrics={
            "passes": report.passes,
            "conversations": report.conversations,
            "episodes_read": report.episodes_read,
            "model_calls": report.model_calls,
            "proposed": report.proposed,
            "committed": report.committed,
            "deferred": report.deferred,
            "rejected": report.rejected,
            "dropped_unsupported": report.dropped_unsupported,
            "discarded_unusable": report.discarded_unusable,
            "discarded_over_limit": report.discarded_over_limit,
            "budget_spent": report.budget_spent,
        },
    )


def queued_question(admission: DeferralAdmission) -> QueuedQuestion:
    """Translate a ``core`` admission into the surface's own echo (ADR-0078 §7).

    A **module function rather than a classmethod**, like every other projection in
    this package (ADR-0085 §6a): the promoted models carry their fields, not their
    constructors. The rule is stated over *every* projection helper rather than
    over the ones that would break the build, because a rule with exceptions is one
    the next reader has to re-derive — and because a projection from a ``core``
    record into a ``core`` DTO belongs to the layer that *decides* the projection.

    It branches on the ``outcome`` and **never on an id comparison**, which is the
    shape ADR-0078 §2 rejects: comparing the returned id to the one the coordinator
    minted fails the moment a caller retries with the same id, and the surface would
    announce a newly parked question over a suppressed one.
    """
    match admission.outcome:
        case DeferralAdmissionOutcome.ADMITTED:
            outcome = QueueOutcome.QUEUED
        case DeferralAdmissionOutcome.SUPPRESSED:
            outcome = QueueOutcome.ALREADY_ASKED
        case DeferralAdmissionOutcome.REFUSED:
            # No deferral to read at all — reaching for one here is the
            # dereference the three-shape validator exists to prevent.
            return QueuedQuestion(outcome=QueueOutcome.QUEUE_FULL)
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(admission.outcome)
    deferral = admission.deferral
    if deferral is None:  # pragma: no cover — the validator pins the shapes
        return QueuedQuestion(outcome=outcome)
    return QueuedQuestion(
        outcome=outcome,
        question_id=deferral.id,
        question_state=question_state(deferral.state),
    )


def learn_outcome(outcomes: tuple[WriteOutcome, ...]) -> LearnOutcome:
    """Translate the write stage's outcomes into the surface's summary.

    The one place a ``core``
    :class:`~ai_assistant.core.types.MemoryIngestResult` or
    :class:`~ai_assistant.core.types.DeferralAdmission` is read on the learn path;
    everything a client sees downstream is a promoted type (ADR-0042 §1).

    **It cannot be a classmethod on the promoted model, and this is the helper that
    proves the rule** (ADR-0085 §6a): it names
    :class:`~ai_assistant.orchestration.writes.WriteOutcome`, which lives in
    `orchestration`. Carried onto :class:`~ai_assistant.core.types.LearnOutcome` it
    would put ``core -> orchestration`` in the import graph — the precise
    ``lint-imports`` failure the closure is promoted to avoid, reintroduced by a
    classmethod nobody counted as a field.
    """
    return LearnOutcome(
        results=tuple(
            IngestSummary(
                decision=learn_decision(outcome.result.decision.kind),
                record_id=outcome.result.record_id,
                reason=outcome.result.decision.reason,
                queued=_queued(outcome),
            )
            for outcome in outcomes
        )
    )


def _queued(outcome: WriteOutcome) -> QueuedQuestion | None:
    """Where one write outcome's deferred question went, or ``None`` (ADR-0078 §10.9).

    Three cases, and the third is the one that must not collapse into the others:

    * not a deferral at all — no question was raised, so there is nothing to say;
    * a deferral the stage offered to the queue — the admission says what happened;
    * a deferral the stage never offered, because it is secret-tier (ADR-0078 §1).
      The stage returns no admission for it, and reading that absence as "nothing to
      say" would route every ``ASK_USER`` through the queued-question line and tell
      the user to go answer something that was never queued.
    """
    if outcome.result.decision.kind is not MemoryDecisionKind.ASK_USER:
        return None
    if outcome.admission is None:
        return QueuedQuestion(outcome=QueueOutcome.NOT_QUEUABLE)
    return queued_question(outcome.admission)


def learn_decision(kind: MemoryDecisionKind) -> LearnDecision:
    """Map a ``core`` memory ruling to its surface-level echo (ADR-0042 §1).

    Total by construction: every :class:`~ai_assistant.core.types.MemoryDecisionKind`
    is handled, so a new ruling added to ``core`` fails type-checking here until it
    is given an echo, rather than silently losing its rendering.

    Package-internal rather than module-private: the observation stage translates
    the rulings it collects the same way, because ADR-0077 §4 puts every proposal
    through the write path ``learn`` already uses — and two copies of a total
    mapping is how one of them silently stops being total.
    """
    match kind:
        case MemoryDecisionKind.ACCEPT:
            return LearnDecision.STORED
        case MemoryDecisionKind.REJECT:
            return LearnDecision.REJECTED
        case MemoryDecisionKind.REINFORCE:
            return LearnDecision.REINFORCED
        case MemoryDecisionKind.SUPERSEDE:
            return LearnDecision.SUPERSEDED
        case MemoryDecisionKind.ASK_USER:
            return LearnDecision.DEFERRED
        case MemoryDecisionKind.STORE_TEMPORARY:
            return LearnDecision.STORED_TEMPORARILY


#: The floor a belief's **presented** confidence falls to as its support is lost
#: (ADR-0077 §6). A documented positive constant, and the *exact* value is this
#: lane's: what §6 ratifies is that the adjustment is a pure function of the stored
#: confidence and how many citations still resolve, bounded above by the stored
#: value and below by ``min(stored, floor)``.
#:
#: Positive rather than zero because a belief whose evidence is all gone is **held,
#: marked and answerable — not auto-retired** (§6): a presented zero would read as
#: "the assistant no longer believes this", which is the cascade under another name.
#: Low, because an unsupported derived belief that keeps reaching prompts at its old
#: standing is the "wrong record laundered into a fact" ADR-0072 §6 exists to
#: prevent.
_PRESENTATION_FLOOR = 0.1


def presented_confidence(stored: float, *, cited: int, resolved: int) -> float:
    """The confidence a surface states, given how much support still resolves (§6).

    **Presentation only.** The stored number never moves: nothing here writes, and
    ``MemoryStore.search`` stays confidence-neutral (ADR-0072 §5), so retrieval order
    is untouched by a value computed at the moment of display. ``export`` likewise
    carries the record *as stored* — an export is the user's data as held, not a
    rendering of it (ADR-0007 §3).

    The ratified properties, all of which this satisfies by construction:

    * **equal to ``stored`` when every citation resolves**, and when the record
      cites nothing at all (an assertion's warrant is the user's own word);
    * **bounded above by ``stored``** — losing support never makes a belief look
      better held;
    * **bounded below by ``min(stored, floor)``**, never by the floor alone. That
      is the whole of the edge case: ``Provenance.confidence`` permits ``0.0`` and
      only *this* producer is bound to a positive ladder, so a belief can be stored
      at or beneath the floor — where an absolute floor and "never above stored"
      have no value between them at all. Capping the floor by the stored value keeps
      both bounds satisfiable everywhere;
    * **strictly decreasing in lost support while above the effective floor**, and
      unchanged once it has reached it — which, for a belief stored at or below the
      floor, is from the first loss onward. A value that has run out of room to fall
      says nothing about how much support went away, which is what the tombstones
      beside it are for;
    * **no clock, no randomness, nothing read from a store.**

    Args:
        stored: The confidence as written on the record.
        cited: How many citations the record carries.
        resolved: How many of them still resolve to a record the store holds.

    Returns:
        The number every surface states for this belief.
    """
    floor = min(stored, _PRESENTATION_FLOOR)
    # Nothing cited, or nothing lost: the stored value stands unadjusted.
    if cited in (0, resolved):
        return stored
    # Linear between the effective floor (nothing resolves) and the stored value
    # (everything does). Where ``stored <= floor`` the two coincide and the span is
    # zero, so the result is ``stored`` at every level of support — the no-op §6
    # names, with the loss carried by the tombstones instead.
    return floor + (stored - floor) * (resolved / cited)


def _confirmation_egress(recorded: PermissionDecision) -> ConfirmationEgress | None:
    """The egress facts a confirmation puts to the user, or ``None`` (ADR-0178 §5).

    Read from the **recorded** ``PermissionDecision`` the confirmation is about,
    which is ADR-0148 §1: the binding a confirmation shows is the one the ruling
    was taken over, fixed before the ruling and not moving after it. Reading it
    from anything the runner still holds would be a second source that could
    differ from the authorised one.

    **Three fields off a value already in hand, and nothing else.** It derives no
    binding, reads no connection record, opens no store, calls no seam and reads no
    clock — which is what keeps :meth:`Engine._confirmation`'s standing guarantee
    true (#287): everything that could **fail** still happens before ``run`` commits
    ``AWAITING_APPROVAL``, and no fallible work is left here. The one ``raise``
    below is an internal-fault guard over an unconstructable state, the same shape
    as :meth:`Engine._confirmation`'s three, not a check that could turn a parked
    step into a stranded one. The account's ``reference`` and
    the binding's ``transport_endpoint`` are the two fields deliberately left
    behind (ADR-0178 §2), so nothing this returns can carry them to an adapter.

    **The third is ``planned_with_external_content``** (ADR-0181 §3's third clause),
    populated from the recorded decision's ``egress_binding`` here and by no other
    route — which is what makes it the *same fact* reaching a surface rather than a
    second statement of it (ADR-0150 §1, ADR-0178 §5).

    **What a surface owes for it is ADR-0181 §6's, and this function neither
    discharges nor asserts any of it.** §10 assigns §6's implementation to the
    *follow-on consumer group* — ``interfaces/cli.py``'s
    ``_render_confirmation_egress`` and the gateway's confirmation view — which
    #1427 sequences after track web-client's milestone-16 lanes, and the ADR "does
    not relax that". Putting the fact on the carrier is what makes that lane
    possible and is the whole of what this one owes.

    **The same function serves both assembly sites**, which is how ADR-0178 §5's
    fourth clause is discharged rather than hoped for: a recovered confirmation
    carries the *same* egress content a live one carries for the same parked step,
    because ``PermissionDecision.egress_binding`` is a stored field the trail
    round-trips whole (ADR-0150 §9) and both sites hold a whole decision. There is
    no reduced, digested or partial recovered form.

    **Neither unrecorded binding is assumed away; each is refused**
    (ADR-0184 §8, ADR-0233 §14). ``ConfirmationEgress``'s
    ``planned_with_external_content`` and ``coverage`` are both required with no
    default, so composing one for a row that never recorded the value would demand
    exactly the fabrication ADR-0184 exists to avoid — at the surface where the user
    is being asked to approve something, which is the worst place in the system to
    invent a fact. ``None`` is not the answer either: ADR-0178 §4 makes it the
    discriminator for "the ruling was not taken over an egress binding at all",
    which for a row naming an account and a recipient would be false. So the absence
    is answered by not asking the question, and neither assembly site can reach
    either shape: both are fed by ``AuditTrail.pending_confirmation``, which answers
    ``None`` for both (ADR-0184 §5, ADR-0233 §14), and by a decision this process
    has just recorded, which ``record`` refuses to be either (§4).

    **The coverage-unrecorded refusal is stated and not inherited**, because the
    origin guard does not catch that epoch: such a row **has**
    ``planned_with_external_content``, so it is not an ``OriginUnrecordedBinding``
    and falls straight past the ``isinstance`` written for one, reaching the
    constructor where a required ``coverage`` can be neither transcribed from a
    binding that does not carry it nor honestly invented.

    Args:
        recorded: The recorded ``CONFIRM`` this confirmation is about.

    Returns:
        The egress facts, or ``None`` where the decision carries no binding — which
        is ADR-0178 §4's discriminator and states that the ruling was taken over an
        egress binding and nothing more.

    Raises:
        PlanningError: If the decision's binding records no origin, or records no
            coverage. Unreachable from either assembly site, and stated as a floor
            rather than a route that exists.
    """
    binding = recorded.egress_binding
    if binding is None:
        return None
    if isinstance(binding, OriginUnrecordedBinding):
        msg = (
            "a confirmation cannot be composed for a decision whose egress binding records "
            "no origin: the value the user would be shown was never recorded"
        )
        raise PlanningError(msg)
    if isinstance(binding, CoverageUnrecordedBinding):
        msg = (
            "a confirmation cannot be composed for a decision whose egress binding records "
            "no coverage: the value the user would be shown was never recorded"
        )
        raise PlanningError(msg)
    return ConfirmationEgress(
        account_identity=binding.account.identity,
        spans=binding.spans,
        planned_with_external_content=binding.planned_with_external_content,
        coverage=binding.coverage,
    )


def belief_from_record(record: MemoryRecord, evidence: tuple[Evidence, ...] = ()) -> Belief:
    """Project one stored record into the belief a person reads (ADR-0073 §7).

    The one place a ``core`` :class:`~ai_assistant.core.types.MemoryRecord` is read
    on the single-belief path, and one of the two places
    :func:`~ai_assistant.core.types.band_of` is applied — which is the deciding
    reason this is a function in `orchestration` and not a constructor on the
    promoted model (ADR-0085 §6a). ``band_of`` is ADR-0072 §1's projection and
    ADR-0073 §7 puts it in the engine; putting it in ``core/types.py`` would make
    ``core`` the home of a policy decision the engine owns.

    ``evidence`` is resolved by the caller, because resolving it is a *store read*
    and this is a pure projection. It must carry one entry per citation on the
    record, in order: the presented confidence is computed from how many of them
    resolved, so a caller that dropped the lost ones would report a belief as fully
    supported at the exact moment it stopped being.

    **``evidence_elided`` travels as stored — not clamped, not rounded, not
    recomputed** (ADR-0107 §8 item 2). It looks like a bug beside the resolved
    tuple, because it can exceed ``len(evidence)`` and can be non-zero where the
    tuple is empty; both are correct. The number counts displacements over the
    record's whole history and is an **upper bound** over a different population
    than the retained citations (ADR-0086 §4), which also double-counts in two
    reachable cases. ADR-0086 §4's rule for ``export`` is that the stored number
    travels so "the bound's imprecision travels with the field rather than being
    resolved in the artifact"; a projection that clamped it to the retained count
    would resolve exactly that imprecision, and resolve it wrongly. It is carried on
    **every** band (ADR-0107 §3): §2's rendering obligation is scoped to ``DERIVED``
    and this is not a rendering.

    **The origin of what it shows travels too** (ADR-0189 §1, §2): the record's
    ``attestation`` projected **whole** — never split into two scalars, which would
    reintroduce on the surface's side of the seam the half-states ADR-0092 §2 made
    unconstructable on the record's — and the answer
    :func:`~ai_assistant.core.types.rests_on_recorded_external_content` gives for
    this record's provenance. That function is read and
    ``Provenance.derived_from_external`` is **not**: ADR-0106 §2 rules that every
    consumer asking "does this rest on recorded external content?" calls it, because
    the hand-rolled disjunction "is short enough that every consumer will write it
    and one of them will write only the second half". Carrying the predicate's whole
    answer rather than only the part ``band`` does not cover is what stops each
    *client* re-deriving that disjunction and dropping the same half (ADR-0189 §3).

    Both travel **as the record holds them**, on every band: ADR-0189 §1's second
    clause forbids a projection computing a rendering, choosing a wording, or
    omitting a fact because the surface it expects would not display it. What a
    surface says about them is ADR-0189 §4's, and this is not a rendering either.
    """
    provenance = record.provenance
    resolved = sum(1 for item in evidence if not item.lost)
    return Belief(
        id=record.id,
        band=band_of(provenance.source),
        kind=MemoryKind(record.kind),
        content=record.content,
        confidence=presented_confidence(
            provenance.confidence, cited=len(evidence), resolved=resolved
        ),
        evidence=evidence,
        last_updated=provenance.last_updated,
        valid_until=record.validity.valid_until,
        evidence_elided=provenance.evidence_elided,
        attestation=provenance.attestation,
        rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
    )


def belief_summary_from_record(record: MemoryRecord, *, cited: int, resolved: int) -> BeliefSummary:
    """Project one stored record into the summary the **listing** ships (ADR-0085 §4a).

    The listing's counterpart to :func:`belief_from_record`, and the difference is
    the whole of ADR-0077 §6's split: this takes *how many* citations resolved
    rather than the resolved citations themselves, so no citation's content can
    reach a page. ADR-0073 §4's floor — "a citation the surface cannot render as
    evidence is never rendered *as* evidence" — becomes a static guarantee here
    rather than a convention, because a
    :class:`~ai_assistant.core.types.BeliefSummary` holds no citations at all.

    The adjusted confidence still needs the counts, which is why the listing keeps
    resolving *existence* per citation (ADR-0077 §6).

    **``evidence_elided`` travels as stored**, for the reason
    :func:`belief_from_record` states at length: it is an upper bound over the
    record's whole history, so it may exceed ``cited`` and may be non-zero where
    ``cited`` is zero, and clamping it to the retained count would resolve ADR-0086
    §4's deliberate imprecision wrongly. It is neither an input to nor an output of
    the presented confidence — feeding elisions into that function "would lower a
    belief's presented confidence because the system worked, which inverts the
    signal" (ADR-0086 §4).

    **The origin of what it shows is carried here exactly as
    :func:`belief_from_record` carries it** (ADR-0189 §1, §2), and the sameness is
    the point: ADR-0085 §4a's split is about *citations*, not about provenance, and
    a listing that disclosed less of a belief's origin than the detail view it is
    drilled into would make the two disagree about a fact neither computes. Both
    read :func:`~ai_assistant.core.types.rests_on_recorded_external_content` and
    neither reads ``Provenance.derived_from_external`` (ADR-0106 §2).

    Args:
        record: The stored record.
        cited: How many citations the record carries.
        resolved: How many of them still resolve to a record the store holds.
    """
    provenance = record.provenance
    return BeliefSummary(
        id=record.id,
        band=band_of(provenance.source),
        kind=MemoryKind(record.kind),
        content=record.content,
        confidence=presented_confidence(provenance.confidence, cited=cited, resolved=resolved),
        last_updated=provenance.last_updated,
        evidence_count=cited,
        lost_evidence=cited - resolved,
        valid_until=record.validity.valid_until,
        evidence_elided=provenance.evidence_elided,
        attestation=provenance.attestation,
        rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
    )


def conversation_summary(conversation: Conversation) -> ConversationSummary:
    """Project one stored conversation into the summary a person reads (ADR-0074 §2)."""
    return ConversationSummary(
        id=conversation.id,
        started_at=conversation.started_at,
        last_active_at=conversation.last_active_at,
        last_turn_at=conversation.last_turn_at,
    )


def _outcome_of(step: StepOutcome | None) -> ExchangeDisposition:  # noqa: PLR0911 — one return per Disposition member plus the no-step case; collapsing them would hide the totality the docstring relies on
    """What became of the exchange, as the captured episode's ``disposition`` (ADR-0221 §2).

    Total over :class:`~ai_assistant.orchestration.runner.Disposition` and
    mechanically so — the wildcard does nothing but ``assert_never`` — so a
    disposition added without a member here fails the gate rather than recording an
    exchange whose disposition reads as empty. This is deterministic recording, not a
    judgement: it says what the engine did, and infers nothing about the user.

    **A member rather than the phrase this returned until ADR-0221** (§2, §3). The
    eight strings composed here were stored in the episode's ``outcome``; §1 gives
    that field to the composed reply, so the fact goes into ``disposition`` as a
    member of a closed vocabulary and the phrase is produced by each of
    ``learning/observer.py``, ``planning/planner.py`` and
    ``orchestration/composing.py`` from a table written out at that site. §2 fixes
    those phrases as the strings this function used to return, byte for byte, which
    is what makes the three prompts identical across the change — and ``NO_ACTION``
    aside, the mapping below is one member of :class:`ExchangeDisposition` per member
    of :class:`~ai_assistant.orchestration.runner.Disposition`, never a collapse of
    two onto one (§2).
    """
    if step is None:
        return ExchangeDisposition.NO_ACTION_NEEDED
    match step.disposition:
        case Disposition.EXECUTED:
            return ExchangeDisposition.STEP_EXECUTED
        case Disposition.DENIED:
            return ExchangeDisposition.STEP_DENIED
        case Disposition.AWAITING_CONFIRMATION:
            return ExchangeDisposition.STEP_AWAITING_CONFIRMATION
        case Disposition.NO_CAPABLE_TOOL:
            return ExchangeDisposition.STEP_NO_CAPABLE_TOOL
        case Disposition.AMBIGUOUS_CAPABILITY:
            return ExchangeDisposition.STEP_AMBIGUOUS_CAPABILITY
        case Disposition.INVALID_PARAMETERS:
            return ExchangeDisposition.STEP_INVALID_PARAMETERS
        case Disposition.EGRESS_UNBINDABLE:
            return ExchangeDisposition.STEP_EGRESS_UNBINDABLE
        case _:  # pragma: no cover - exhaustive
            assert_never(step.disposition)


def _exchange_of(turn: TurnResult | None, step: StepOutcome | None, *, resumed: bool) -> str:
    """The canonical text rendering of one exchange (ADR-0005 §1, ADR-0074 §4).

    What was asked and how it turned out, in the store's own ``content`` field —
    which is what makes the episode citable and retrievable without a second,
    verbatim transcript store holding the same Tier 1 text under a second retention
    rule (ADR-0074 §3).

    ``turn`` is ``None`` only on a resumption recovered from durable state, where
    ``resumed`` is necessarily ``True``, so the rendering is never empty.
    """
    lines: list[str] = []
    if turn is not None:
        lines.append(f"The user asked: {turn.goal.statement}")
        if turn.plan.rationale:
            lines.append(f"The assistant's plan: {turn.plan.rationale}")
    if resumed:
        lines.append("The user answered the confirmation this action was parked on.")
    if step is not None and step.tool_id is not None:
        lines.append(f"The action selected the tool {step.tool_id}.")
    return "\n".join(lines)


def _routed_outcome_of(outcome: RouteOutcome) -> ExchangeDisposition:  # noqa: PLR0911 — one return per RouteOutcome member; collapsing them would hide the totality `assert_never` rests on
    """What became of a routed exchange, as its episode's ``disposition`` (§10, ADR-0221 §2).

    Total over :class:`~ai_assistant.core.types.RouteOutcome` and mechanically so — the
    wildcard does nothing but ``assert_never`` — so a member added without a member here
    fails the gate rather than recording an exchange whose disposition reads as empty.

    **A member rather than the phrase this returned until ADR-0221**, on the same
    ground as :func:`_outcome_of` and with the same three render sites producing §2's
    phrase for it. The ``ROUTED_*`` half of :class:`ExchangeDisposition` is one member
    per member of :class:`~ai_assistant.core.types.RouteOutcome`, and §2 forbids
    collapsing any of it onto the ``STEP_*`` half: ``ROUTED_PERFORMED`` and
    ``STEP_EXECUTED`` are synonyms in ordinary English and different acts under
    different clauses, so both ship.

    **Every member is about the route and none is about its subject** (ADR-0197 §10).
    The captured episode carries no part of the routed account: not the listing, not the
    display subject, not the scalar argument, and not the candidates. That is §6's second
    sentence made mechanical rather than hoped for — a conversation's recent turns are
    retrieved into the next turn's prompt (ADR-0074 §5, ADR-0158 §5), so a capture that
    folded a routed listing into the episode would deliver the routed result to a model
    one turn later, satisfying every same-pass clause of §6 while breaking §6. ADR-0221
    §1 puts the composed *reply* in that episode's ``outcome`` and leaves the clause
    true, because ADR-0197 §6 hands the composing stage two enum values and nothing
    else, so a routed reply cannot contain what §6 withholds.
    """
    match outcome:
        case RouteOutcome.PERFORMED:
            return ExchangeDisposition.ROUTED_PERFORMED
        case RouteOutcome.AWAITING_CONFIRMATION:
            return ExchangeDisposition.ROUTED_AWAITING_CONFIRMATION
        case RouteOutcome.REFUSED:
            return ExchangeDisposition.ROUTED_REFUSED
        case RouteOutcome.AMBIGUOUS:
            return ExchangeDisposition.ROUTED_AMBIGUOUS
        case RouteOutcome.AMBIGUOUS_TRUNCATED:
            return ExchangeDisposition.ROUTED_AMBIGUOUS_TRUNCATED
        case RouteOutcome.NOT_FOUND:
            return ExchangeDisposition.ROUTED_NOT_FOUND
        case RouteOutcome.UNRECORDED:
            return ExchangeDisposition.ROUTED_UNRECORDED
        case RouteOutcome.FAILED:
            return ExchangeDisposition.ROUTED_FAILED
        case _:  # pragma: no cover - exhaustive
            assert_never(outcome)


def _routed_exchange_of(utterance: str | None, *, resumed: bool) -> str:
    """The canonical text rendering of a routed exchange (ADR-0074 §4, ADR-0197 §10).

    **The utterance is threaded here rather than read off a turn**, because a routed
    pass produces no ``TurnResult`` — which is the one obligation ADR-0197 §10 warns a
    lane will discover the hard way: ``Engine._capture`` builds its episode content from
    the turn, so a lane that wired routing without threading the utterance would produce
    a captured exchange with the user's own sentence missing from it, a silent hole in
    the conversation record visible only to the next person to resume that conversation.

    A resume answering a routed park has no utterance of its own — the adapter relays an
    opaque token and a boolean — so its episode says what it is, exactly as a resumed
    step's does.
    """
    lines: list[str] = []
    if utterance is not None:
        lines.append(f"The user asked: {utterance}")
    if resumed:
        lines.append("The user answered the confirmation this operation was parked on.")
    return "\n".join(lines)


#: How a routed pass composes its answer: the whole routed account, and the
#: conversation the room is measured against.
#:
#: **The account rather than its two enum values**, and the difference is the streaming
#: ceiling. ADR-0197 §6 constrains what the *composing stage* is handed — two closed
#: vocabularies and nothing else — and the stage's own signature is where that is
#: enforced; what the engine needs one level up is the outcome it is about to **build**,
#: because ADR-0173 §3 measures the reply's room against exactly that value and a probe
#: omitting the listing would over-state it. Nothing here reaches a prompt. Two shapes satisfy it —
#: :meth:`Engine._composed_routed_whole` and a closure over
#: :meth:`Engine._compose_routed_streaming` — and it is a parameter rather than a flag
#: for :meth:`Engine._run_turn`'s own reason: a second copy of the routing driver would
#: be two places for the reservation's release and the capture point to drift apart.
type _RoutedComposer = Callable[[RoutedOperation, str], Awaitable[ComposedReply | None]]


#: How an ordinary pass composes its answer: what the turn produced, what became of the
#: step it drove, the conversation the streaming ceiling is measured against, the
#: tail's delivery facts, and which records this turn's citation hop reached.
#:
#: **The fourth member is ADR-0205 §5's supplied fact**, keyed by the episode it
#: qualifies, and it is an argument rather than a member of the turn for the reason §5
#: gives: it is a supplied *input* to this stage and not part of the episode's content,
#: which capture leaves byte-unchanged. It reaches every composer — a turn on
#: ``converse`` whose tail carries a delivery is a real case, the owner who speaks, is
#: interrupted, and then types — because the facts are about the tail's deliveries and
#: not about this turn's channel.
#:
#: **The fifth is ADR-0227 §3's carrier and travels for the same reason**: it is a
#: supplied *input* to the composing stage, stated at the servicer — "the one place
#: ``CITATION_HOP`` and ``SIGHTED_QUERY`` are distinguishable" — and never inferred at
#: the render site, which §3 refuses on three named reconstructions each of which is
#: unsound rather than merely inelegant. It reaches every composer for the delivery
#: fact's reason: what it is about is how a record was fetched, not what channel this
#: turn arrived on. It is **ordered**, because ADR-0227 §4's cap is taken over it in
#: ADR-0226 §6's order.
#:
#: **The sixth is ADR-0228 §10's carrier**, and it travels here rather than on the
#: turn for §10's own reason: it "is carried **inside**
#: ``ai_assistant.orchestration``, from the component that knows it to the render
#: site, as data", adding no field to a ``core`` type and no member to a Protocol,
#: and it "is never inferred at the render site — not from the plan, not from the
#: supply's length, not from the audit". It is the **bare fact** that the turn stopped
#: looking while it was still asking: no count, no duration, no guard name, no query
#: and no label. ``False`` on every other pass, where the assembled prompt is
#: byte-identical to what it is today.
type _Composer = Callable[
    [
        TurnResult | None,
        StepOutcome | None,
        str,
        Mapping[str, SpokenDelivery],
        Sequence[str],
        bool,
    ],
    Awaitable[ComposedReply | None],
]


#: Which conversational operation each pass of :meth:`Engine._run_turn` is running
#: under (ADR-0228 §4), named here and priced in
#: :class:`~ai_assistant.orchestration.loop.ConversationalOperation`.
#:
#: **What crosses the seam is the identity and never a duration.** §4 rules the budget
#: "not a ``Settings`` value, not a deployment flag and **not a per-request
#: parameter**", so this method does not compute, hold or pass a figure: it says which
#: operation it is, exactly as it tells the capture point which operation it is with
#: ``spoken`` (ADR-0205 §4) rather than reading a flag. The figures are the loop's,
#: fixed on a closed enum, and move only by the ADR that moves them.
#:
#: A pass that names no operation declares no budget and does not iterate, which is
#: §4's fail-closed direction for a lane that adds an operation and forgets to price
#: it. Every conversational operation here names one.


@dataclass(frozen=True, slots=True)
class _RoutedPark:
    """The private state one routed continuation token names (ADR-0197 §7).

    Never seen by an adapter, never enumerated by ``pending_confirmations``, and never
    recovered across a restart: a token presented to an engine that cannot resolve it
    yields ``UnknownContinuationError`` and never a denial (ADR-0084 §7). What a lost
    routed park costs is **one repeated sentence** — nothing has happened yet, the
    operation has not run, no side effect is pending, and the resolution is a lookup the
    next ask redoes in the same way.

    Attributes:
        operation: Which confirm-owed operation is waiting on the user's answer.
        subject: The display subject the card rendered, as a one-element listing.
        argument: The scalar identity the façade will be called with (ADR-0197 §5).
        route_id: The route's identity, carried from the ``OWED`` row so the ``resume``
            can write the answer under it (ADR-0197 §9).
        conversation_id: The conversation the ask ran under, so the resumption is
            captured where the question was asked.
        registered_at: When the park was registered, read from the **injected** clock
            (ADR-0009), which is what lets a test advance the lifetime rather than wait
            it out.
    """

    operation: RoutableOperation
    subject: RoutedListing
    argument: str
    route_id: str
    conversation_id: str
    registered_at: datetime


@dataclass(frozen=True, slots=True)
class _RouteReservation:
    """The two resources one route holds, taken together and released together (§7, §9).

    A ceiling slot and an identity, "under one acquisition and one ``finally``". The
    handle is ``None`` on a read-only route, which parks nothing and so takes no slot
    (ADR-0197 §1); the ``route_id`` is reserved by **every** route, read-only ones
    included, because a read-only route's ``NOT_OWED`` row under a live park's id would
    collide with that park's own answer exactly as a second park's ``OWED`` row would.

    Attributes:
        route_id: The reserved identity.
        handle: The reserved continuation handle, which is also the ceiling slot, or
            ``None`` on a read-only route.
    """

    route_id: str
    handle: str | None


@dataclass(frozen=True, slots=True)
class _Parked:
    """The private state one continuation token names (never seen by an adapter).

    ``turn`` is ``None`` and ``confirmation_id`` is ``None`` for an entry
    reconstructed from durable state by :meth:`Engine.pending_confirmations`
    (ADR-0052): a recovered park has no live turn, and a ``None`` confirmation id
    routes :meth:`Engine.resume` through the runner's restart recovery path
    (recover the ``CONFIRM`` by its ``(execution_id, step_id)`` binding, ADR-0044
    §3) rather than caching a decision id a concurrent resolution could stale.

    ``supplied_withheld`` is the parking turn's **own** ADR-0204 §2 evaluation —
    unchanged by ADR-0217 §3, which moves what it is written *into* and not how it is
    computed — retained here beside the turn it belongs to. The resolution's capture
    renders that turn's goal and plan into a second episode from a pass that
    retrieves nothing of its own, so the value is carried rather than recomputed —
    recomputing it there would evaluate an empty supply and answer ``False`` about a
    rendering the parking turn's warrant produced. ``False`` on a recovered entry,
    whose ``turn`` is ``None``: its episode carries no goal statement and no plan
    rationale of any turn, so there is nothing in it for a narrowing to be about.

    ``modality`` is retained for the same reason and by the same argument, one field
    over (ADR-0221 §5's second case, which is "ADR-0204 §2's fourth clause applied to
    a second field, for that clause's own reason"). The resolution's episode renders
    **the parked turn's** user material, so what it is stamped with is that turn's own
    value, "retained with the parked turn and applied unchanged. No implementation
    re-evaluates, recomputes or defaults it at the second capture" — never the
    resuming pass's, which is what a ``resume`` of a spoken turn would otherwise
    record as typed. :data:`Modality.TEXT` on a recovered entry, whose ``turn`` is
    ``None``: §5's third case, and true of what that episode holds rather than a
    fallback, because it renders no user material at all.

    ``derived_from_external`` is retained for a third time by the same argument
    (ADR-0223 §3's second case, "ADR-0204 §2's fourth clause applied to a third
    field, for that clause's own reason"). It is the parking turn's own disjunction
    over the supply *that* turn ran over, and the resolution's episode renders that
    turn's goal statement and plan rationale — so recomputing it at the second
    capture would evaluate the empty supply of a pass that retrieves nothing and
    answer ``False`` about a rendering the parked turn's supply produced. ``False``
    on a recovered entry, whose ``turn`` is ``None``: §3's third case, true of an
    episode that renders no turn's material at all rather than a default it falls
    back on.
    """

    turn: TurnResult | None
    execution_id: str
    step_id: str
    confirmation_id: str | None
    supplied_withheld: bool = False
    modality: Modality = Modality.TEXT
    derived_from_external: bool = False


@dataclass(frozen=True, slots=True)
class _Settled:
    """What one **answered** continuation token still names (ADR-0198 §1).

    A settled record, not a park: it carries the binding and the immutable facts of
    the resolution that answered it, it holds no live turn, it authorises nothing,
    and no code path resolves anything through it. Presenting its token again
    **restates** the answer already recorded rather than meeting
    ``UnknownContinuationError`` (§1), which is what lets a surface whose first
    answer's fate is unknown ask "did it land?" and be told (#1621).

    **Only immutable facts are retained** (§2). The ``Disposition`` is the gate's
    verdict on a decision ADR-0044 §2b makes unrepeatable, so it cannot go stale; the
    ``step_id`` and ``tool_id`` name what was bound. ``StepOutcome.state`` is *not*
    here on purpose — it is "the durable execution state after the last transition
    committed", and a value cached at settlement stops being that the moment anything
    advances the execution, so a restatement re-reads it from the plan store
    (ADR-0139 §2). What can change is read; what cannot is retained.

    **Not a park in any table that counts one.** A settled record holds no slot at
    ``max_outstanding_confirmations`` — that ceiling bounds *unanswered* parks, and
    counting these would let a client that answered every confirmation meet
    backpressure for having done so (§4). The retained set is bounded by that same
    number, discarding the least recently settled, and is never enumerated by
    ``pending_confirmations`` nor reached by its reconciliation.

    Attributes:
        execution_id: The settled binding's execution, re-read at each restatement.
        step_id: The settled binding's step.
        tool_id: The tool the step bound, or ``None`` where it bound none.
        disposition: The disposition the resolution reached.
    """

    execution_id: str
    step_id: str
    tool_id: str | None
    disposition: Disposition


def _paired_deliveries(
    deliveries: Mapping[str, SpokenDelivery], memories: Sequence[MemoryRecord]
) -> Mapping[str, SpokenDelivery]:
    """Keep only the delivery facts whose episode reached this turn (ADR-0205 §5).

    **A delivery fact travels with the episode it qualifies and never without it.**
    Where a supply site withheld a record — under ADR-0199 §3, or under ADR-0204 §3's
    test as ADR-0217 §2 now reads it, on ``MemoryBase.placement`` — that record is not in
    ``memories``, so its fact is not in what this returns and no delivery fact for
    that turn reaches the composing stage at all. A fact stating how long an answer
    ran, standing beside no answer, is a value that narrows what was withheld, and
    ADR-0199 §5's fourth clause forbids one.

    Structural rather than remembered: the composing stage renders what it is given,
    and what it is given is filtered here, so a renderer that later looked up a
    withheld episode by id would find nothing to look up.

    Args:
        deliveries: What the history read holds, keyed by episode id.
        memories: The supply the turn ran over, after ``narrow`` returned it.

    Returns:
        The subset whose episode survived, in insertion order. Empty where none did.
    """
    if not deliveries:
        return {}
    supplied = {record.id for record in memories}
    return {episode_id: fact for episode_id, fact in deliveries.items() if episode_id in supplied}


@dataclass(slots=True)
class _SpokenCapture:
    """What ``converse_spoken`` writes at capture, and what it reads back (ADR-0205).

    **One instance per call**, minted by the operation whose capture owes a
    delivery, exactly as ``Engine._run_turn`` mints one capacity handle per turn and
    ``converse_spoken`` mints one
    :class:`~ai_assistant.orchestration.disclosure.UnboundedAudienceSupply`. Two
    concurrent spoken turns therefore share nothing, and what is recorded here is a
    fact about *this* call rather than about the engine.

    **Its presence is what §4's "on this operation and no other" means
    mechanically.** ``_run_turn`` is given one only by ``converse_spoken``, and the
    capture point writes ``delivery`` from it; ``converse``, ``converse_streaming``
    and ``resume`` hand none and their rows carry none. Nothing in the capture path
    asks which operation it is running under, because it is told.

    Attributes:
        delivery: What capture writes onto the turn's index row —
            ``SpokenDelivery(state=UNKNOWN)`` unconditionally on this operation (§4),
            the park, the absent reply and the degraded synthesis included. At
            capture the hub has produced an answer and knows nothing about what
            reached anyone, and that is what ``UNKNOWN`` says.
        episode_id: The id of the episode recording the turn, written back by the
            capture point so ``SpokenTurn.episode_id`` can disclose it (§1).
            ``None`` where no index row stands for the turn: it is the
            :class:`~ai_assistant.orchestration.conversations.CaptureReport`'s own
            value, which is present even where the *episode* write failed, because
            the row is what carries the delivery.
    """

    delivery: SpokenDelivery = field(
        default_factory=lambda: SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
    )
    episode_id: str | None = None


def _spoken_text(outcome: TurnOutcome) -> str | None:
    """What this pass says aloud, or ``None`` where it says nothing (ADR-0207 §1).

    **Three answers, and the middle one is this ADR's whole addition.** A pass that
    composed an answer speaks that answer and nothing else, byte for byte, as it
    always has (ADR-0200 §4). A pass that reached a **live confirmation park** speaks
    :data:`~ai_assistant.orchestration.speech.SPOKEN_PARK_SENTENCE` — the constant
    ADR-0207 §2 fixes, on both of §1's shapes: a step the permission gate parked and
    a confirm-owed route the routing stage parked. Everything else is silent: a
    composition failure and a resume recovered from durable state each keep ADR-0200
    §4's silence in full, and nothing is invented to fill it (ADR-0207 §3).

    **The park is read from two recorded enum members and from nothing else**
    (:func:`~ai_assistant.core.types.is_live_confirmation_park`), so no confirmation,
    tool declaration, policy reason, resolved subject or part of the transcript is
    inspected to reach this answer, and none can reach the synthesizer through it:
    what this returns on a park is a constant.

    **It answers with the text rather than with the decision**, which is what keeps
    the rendering stage unable to see the park at all — the stage is handed a string
    and renders it, exactly as it renders an answer.

    Args:
        outcome: The turn this pass produced.

    Returns:
        The answer, ADR-0207 §2's sentence, or ``None``.
    """
    if outcome.reply is not None:
        return outcome.reply
    if is_live_confirmation_park(outcome):
        return SPOKEN_PARK_SENTENCE
    return None


@dataclass(frozen=True, slots=True)
class _RoutedSurface:
    """The engine's own operations, as ADR-0197 §2's third clause reaches them.

    Structurally satisfies :class:`~ai_assistant.orchestration.routing.RoutedOperations`,
    and every member but one **relays the engine's own façade method untouched** — which
    is §2's third clause and the reason it is stated rather than assumed: "perform the
    operation" could mean *call the façade method* or *do what the façade method does*,
    and only the first keeps one implementation of ``forget``. The second would put a
    second ``MemoryStore.delete`` call site behind a different set of preconditions, which
    is how two doors to one operation stop behaving the same way. Relaying through the
    façade is also what gives a routed listing the promoted surface's own defaults, its own
    bound and its own payload measurement for free.

    The exception is :meth:`beliefs`, which is not a routable operation at all: ADR-0197
    §5's ``forget`` lookup needs :class:`~ai_assistant.core.types.Belief` records, which is
    the arm §8 gives that operation, and the promoted ``beliefs`` answers
    :class:`~ai_assistant.core.types.BeliefSummary` rows.

    A separate object rather than the engine itself, so the engine's own public surface
    gains nothing: ADR-0197 §9 and §11 are explicit that ``AssistantEngine`` gains no
    method and no signature moves, and a public ``Engine`` member answering a different
    type from the Protocol's same-named one is the substitutability trap ADR-0084 §4
    names.
    """

    engine: Engine

    async def beliefs(self, *, limit: int, offset: int) -> tuple[Belief, ...]:
        """Enumerate live beliefs as §8's ``forget`` arm, for §5's lookup only."""
        return await self.engine._routed_beliefs(limit=limit, offset=offset)

    async def questions(self, *, limit: int, offset: int) -> tuple[Question, ...]:
        """Relay the promoted ``questions``."""
        return await self.engine.questions(limit=limit, offset=offset)

    async def recent_reads(self, *, limit: int) -> tuple[SourceReadRecord, ...]:
        """Relay the promoted ``recent_reads``."""
        return await self.engine.recent_reads(limit=limit)

    async def recent_invocations(self, *, limit: int) -> tuple[RecordedInvocation, ...]:
        """Relay the promoted ``recent_invocations``."""
        return await self.engine.recent_invocations(limit=limit)

    async def recent_decisions(self, *, limit: int) -> tuple[PermissionDecision, ...]:
        """Relay the promoted ``recent_decisions``."""
        return await self.engine.recent_decisions(limit=limit)

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """Relay the promoted ``standing_grants`` — unpaged, complete or refused."""
        return await self.engine.standing_grants()

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Relay the promoted ``spend_totals`` — unpaged."""
        return await self.engine.spend_totals()

    async def forget(self, record_id: str) -> bool:
        """Relay the promoted ``forget``."""
        return await self.engine.forget(record_id)

    async def revoke(self, source: str) -> SourceGrant | None:
        """Relay the promoted ``revoke``."""
        return await self.engine.revoke(source)

    async def forget_question(self, question_id: str) -> bool:
        """Relay the promoted ``forget_question``."""
        return await self.engine.forget_question(question_id)

    async def guard(self, record_id: str) -> Placement | None:
        """Relay the promoted ``guard``."""
        return await self.engine.guard(record_id)

    async def unguard(self, record_id: str) -> Placement | None:
        """Relay the promoted ``unguard``."""
        return await self.engine.unguard(record_id)


def _query_of(route: RoutedRoute) -> str:
    """The query a confirm-owed route must carry, or a defect.

    :func:`~ai_assistant.orchestration.routing._with_query` declines a confirm-owed
    envelope with no usable query, so a ``None`` here means the router produced a route
    the envelope reader could not have returned.
    """
    if route.query is None:  # pragma: no cover — a defect, not a reachable state
        msg = f"a routed {route.operation.value} arrived with no query to resolve from"
        raise AssertionError(msg)
    return route.query


class Engine:
    """The concrete façade an interface adapter drives (ADR-0042 §1).

    Composes the engine's stage objects behind two calls and one shutdown path.
    It is handed the stage objects and the ``PlanStore`` — the same instance its
    ``runner`` was wired with — by the composition root, the one layer licensed to
    construct concretes (ADR-0042 §2).
    """

    def __init__(  # noqa: PLR0913, PLR0915 — one parameter per injected collaborator plus its knobs, and one assignment or wiring check per parameter
        self,
        *,
        loop: LearningLoop,
        runner: StepRunner,
        plans: PlanStore,
        trail: AuditTrail,
        spend: SpendLedger,
        reads: SourceReadTrail,
        memory: MemoryStore,
        archive: TranscriptArchive,
        deferrals: DeferralStore,
        traces: TraceRetention,
        trace_sink: TraceSink,
        trace_retention: timedelta | None,
        conversations: ConversationLifecycle,
        composing: ComposingStage,
        observation: ObservationStage,
        questions: QuestionStage,
        grant_operations: GrantOperations,
        recipient_grant_operations: RecipientGrantOperations,
        connection_operations: ConnectionOperations,
        calendar_ingestion: IngestionStage | None = None,
        email_ingestion: IngestionStage | None = None,
        upcoming: UpcomingEventStage | None = None,
        consolidation: ConsolidationStage | None = None,
        notifications: NotificationStore | None = None,
        notification_policy: NotificationPolicy | None = None,
        notification_outbox: DeliveryOutbox | None = None,
        recovery: RecoveryScan | None = None,
        routing: RoutingStage | None = None,
        transcriber: SpeechTranscriber | None = None,
        synthesizer: SpeechSynthesizer | None = None,
        speakable_attested_sources: frozenset[str] = frozenset(),
        max_spoken_audio_bytes: int = DEFAULT_MAX_SPOKEN_AUDIO_BYTES,
        routed_confirmation_ttl: timedelta = _DEFAULT_ROUTED_CONFIRMATION_TTL,
        max_notification_budget: timedelta = _DEFAULT_MAX_NOTIFICATION_BUDGET,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
        id_factory: Callable[[], str] = _uuid,
        epoch_factory: Callable[[], str] = _uuid,
        now: Clock = _utcnow,
        max_outstanding_confirmations: int = _DEFAULT_MAX_OUTSTANDING,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        drain_timeout: timedelta | None = None,
    ) -> None:
        """Wire the façade from injected collaborators.

        **``plans`` must be the very instance ``runner`` holds.** No type can say
        so, so it is a composition-root obligation (ADR-0042 §2, the same shape as
        ADR-0028 §4's writer/store rule): the façade persists the turn's plan and
        starts the execution it drives through ``plans``, and reloads it through
        ``plans`` to resume, so a façade wired to a *second* store would drive and
        resume nothing while reporting success. The parked step's confirmation
        content rides back on the runner's own disposition
        (:attr:`~ai_assistant.orchestration.runner.StepDisposition.decision`), so
        the façade needs no audit-trail handle of its own.

        Args:
            loop: The turn stage. :meth:`converse` calls its ``respond``.
            runner: The single-step stage (selection, permission, execution). Its
                ``registry``, ``policy``, ``plans`` and ``trail`` are already
                wired; the façade adds only ``plans`` for the reads a driver needs
                around it.
            plans: Durable planning state — the same instance ``runner`` holds.
                The façade persists the turn's goal and plan and starts the
                execution it drives, and reloads it to resume.
            trail: The audit trail — the same instance ``runner`` holds (a
                composition-root single-instance obligation of the same shape as
                ``plans``; ADR-0052 §1). The façade reads it **query-only** to
                recover a durably-parked confirmation's display content after a
                restart (:meth:`pending_confirmations`): the ruling ``reason`` and
                the tool declaration live only in the trail (ADR-0042 §4), and a
                restarted façade has no in-process disposition to read them from. It
                records nothing; authoring rulings stays the runner's (ADR-0042 §6).
                A façade wired to a *second* trail would recover confirmations the
                runner's own ``resume`` cannot resolve.
            spend: The spend ledger — the **same object** ``trail`` is, wired
                through its ``SpendLedger`` face (ADR-0194 §5). One holder satisfies
                that Protocol, ``SpendGate`` and ADR-0192's ledger seam, because all
                three read the same rows and two keyed by them could disagree about
                a total. It is the ledger face and **never** the gate: an adapter
                able to call the admission has acquired the ability to spend a
                budget, which is ADR-0029 §1's argument one seam over.
            reads: The source-read trail — the **same instance** the three drivers
                record into (a composition-root single-instance obligation of the
                same shape as ``plans`` and ``trail``; ADR-0185 §4). The façade
                reads it **query-only**, for :meth:`recent_reads` and
                :meth:`export_reads`, and records nothing: authoring a row stays the
                driver's, on the seam that gated the read (ADR-0185 §5).

                **This is the wide seam's only holder**, which is the arrangement
                ADR-0185 §4 designed and §12 left this surface to complete.
                ``SourceReadTrail`` deliberately does not inherit
                ``SourceReadRecorder``, and the three drivers are annotated with the
                narrow one — so a driver cannot *name* ``recent`` or ``export``, and
                ADR-0093 §5's forbidden cursor stays out of a sensor's reach. That
                narrowing is what makes this parameter necessary rather than
                convenient: there is no collaborator the façade already holds that
                could answer these two.

                A façade wired to a *second* trail would answer a user's history
                from a store nothing writes to — which is worse than an error, since
                an empty trail is a truthful answer about a store that was never
                read from, and this one would be indistinguishable from it.
            memory: Long-term memory — the same instance ``loop`` retrieves from and
                the writer behind it persists to (a composition-root single-instance
                obligation of the same shape as ``plans`` and ``trail``; ADR-0028
                §4). The façade reads it for the inspection surface
                (:meth:`beliefs`, :meth:`belief`) and deletes through it
                (:meth:`forget`), because ADR-0042 §6 forbids an adapter reaching
                memory itself and ADR-0072 §7 forbids re-filtering ``export`` above
                the store. It is held **directly** rather than reached through
                ``loop``: inspection is not a turn, and threading a read that
                answers "what do you believe about me" through the turn stage would
                make the stage the seam for a question it has no part in. Wired to a
                *second* store, a listing would show beliefs the assistant does not
                use and ``forget`` would destroy nothing the user was shown.
            archive: The transcript archive, as its **wide** seam (ADR-0225 §10) and
                the **same** instance ``conversations`` was given the narrow face
                of — a composition-root single-instance obligation of the same shape
                as ``plans`` and ``trail``, because a façade wired to a second
                archive would destroy nothing capture wrote. It carries no
                ``append``, and the omission *is* the capability: §1 reserves writing
                to capture, so ``self._archive.append(...)`` fails ``mypy`` here
                whatever object was passed, and §4's package fence stops this module
                naming the concrete class to get one back.

                What this façade does with it in this change is one thing —
                :meth:`forget` cascades the address-scoped discard §5 puts ahead of
                the record's own destruction. The four reads, the conversation-scoped
                destroy and the size report are operations of their own and are not
                on this surface yet (ADR-0225 §14, lane C); this seam is reached from
                the façade's user-facing and data-rights operations and from **no**
                operation on the turn path (§4).
            deferrals: The durable deferred-question queue — the **same** instance
                ``questions`` holds and the write stage enqueues into, a
                composition-root single-instance obligation of the same shape as
                ``plans`` and ``trail``. Held directly, and for exactly one reason:
                :meth:`purge_expired` is *one* job over *both* stores because
                ADR-0078 §10 item 8 forbids a second sweeping mechanism, so the
                façade has to be able to reach this one. Everything a *user* does to
                a question still goes through ``questions``; nothing else on this
                surface touches this handle. Wired to a second queue, the sweep
                would reclaim rows nobody can see while the rows the user's
                questions actually live in kept growing — which is ADR-0078 §1's cap
                reported as kept and not kept.
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
            composing: The **terminal composing stage** (ADR-0170 §1, §2) — the one
                that speaks. Given the turn's goal, its assembled context, the
                memories retrieved for it, its plan and what became of the step the
                turn drove, it composes the natural-language answer
                :attr:`~ai_assistant.core.types.TurnOutcome.reply` carries. It holds
                its own injected ``ModelProvider`` and this façade holds none:
                ``Engine.__init__`` takes no ``ModelProvider`` and no
                ``ContextProvider``, and reaching a concrete subsystem's internals
                to find one is what golden rule 1 forbids (ADR-0170 §2). So the
                stage is injected already wired, exactly as ``observation`` and
                ``consolidation`` are.

                **Required rather than optional, and that is ADR-0170 §4.** An
                optional collaborator defaults to unwired, and an unwired composer
                is an engine that returns ``reply=None`` on turns §4 says must carry
                one — a state the ``TurnOutcome`` validator refuses, so an engine
                built without it could not return a conforming outcome at all. It is
                required for the reason ``conversations`` is: an engine that can be
                built without it is an engine that silently does not answer.
            observation: The observation stage (ADR-0077 §8) — the other layer
                holding both durable stores, because selecting a batch of episodes
                spans them exactly as capture does. It must be wired to the *same*
                ``MemoryStore`` passed above and to a writer over it, a
                composition-root obligation of the same shape: a stage over a
                second store would select episodes the write path cannot cite, and
                every proposal it made would be refused for evidence that resolves
                perfectly well in the store the user reads. Required rather than
                optional, for the reason ``conversations`` is: an engine that could
                be built without it is an engine whose ``observe`` silently does
                nothing, and this operation is the *only* thing that fills the
                derived band.
            questions: The deferred-question stage (ADR-0078 §8, §9) — the third
                two-store owner, and the one that also **writes** through both: it
                claims a question, re-submits its proposal through the same write
                path ``learn`` uses, and records the outcome. Three
                composition-root obligations ride on it, all argued on its own
                constructor: its ``DeferralStore`` must be the very instance the
                write stage behind ``loop`` and ``observation`` enqueues into (a
                second one queues questions nobody can answer), its writer must
                write to the same ``MemoryStore`` passed above (applying a confirmed
                retirement against a different store would retire nothing while
                reporting success), and it is the **only** producer of a
                ``UserConfirmation``. Required rather than optional, for the reason
                ``conversations`` is: an engine that could be built without it is an
                engine where a deferred question reaches nobody, which is the exact
                failure ADR-0078 exists to end.
            grant_operations: The four grant operations (ADR-0102 §1, §7) — the
                **only** object in the system holding a
                :class:`~ai_assistant.core.protocols.SourceGrantStore` (ADR-0097
                §3, §9), which is why it is injected rather than assembled here.
                The façade delegates ``grantable_sources``, ``grant``, ``revoke``
                and ``recent_grants`` to it, keeping this class's own job the
                argument validation, the size measurement and the drain-tracking
                every other method on the surface gets.

                **Required, where ``calendar_ingestion`` below is optional, and the
                asymmetry is the Protocol.** These four are ``AssistantEngine``
                methods and the shared conformance suite runs against this class,
                so an engine that could be built without them is one whose surface
                is conditionally present — which is what ADR-0102 §7's "no
                production path may build an engine with the store unopened" is
                aimed at. Its sibling stages ``conversations``, ``observation`` and
                ``questions`` are required for the same reason.

                **Spelled ``grant_operations`` and not ``grants``** because
                ``grants`` already means a
                :class:`~ai_assistant.core.protocols.SourceGrants` on every driver
                in this package, and ADR-0102 §2 records that reusing a word for a
                different type one constructor over is how two things come to be
                confused at a glance.
            recipient_grant_operations: The five recipient-grant operations
                (ADR-0235 §3, §7) — the **only** object in this package holding a
                :class:`~ai_assistant.core.protocols.RecipientGrantStore`, which is
                the face ADR-0193 §1 withholds from the policy and from the trail and
                which ``app/composition.py``'s own comment already anticipated
                passing *"whole to whatever performs it"*. The façade delegates
                ``grantable_decisions``, ``establish_recipient_grant``,
                ``standing_recipient_grants``, ``recent_recipient_grants`` and
                ``revoke_recipient_grant`` to it, and hands it the pair a ``resume``
                carrying ``remember_recipients_until`` collected.

                **Required, on ``grant_operations``' argument exactly**: these five
                are ``AssistantEngine`` methods and the shared conformance suite runs
                against this class, so an engine that could be built without them is
                one whose surface is conditionally present.

                **A second object rather than members on ``grant_operations``**,
                because recipient grants and source grants are two vocabularies and
                never one (ADR-0235 §7): one object over two stores that cannot
                substitute for each other is the shape that invites a control
                revoking across both.
            connection_operations: The five connection operations (ADR-0151 §1,
                §10) — the **only** object in this package holding a
                :class:`~ai_assistant.core.protocols.ConnectionProvisioner`. The
                façade delegates ``connect_account``, ``reprovision_account``,
                ``disconnect_account``, ``connected_accounts`` and
                ``recent_connection_acts`` to it, keeping this class's own job the
                argument validation, the size measurement and the drain tracking.

                **Required, on ``grant_operations``' argument exactly** — these
                five are ``AssistantEngine`` methods and the shared conformance
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
            calendar_ingestion: The **calendar's** read-only ingestion stage
                (ADR-0093 §6), or ``None`` where this deployment configured no
                calendar source. It writes through the *same* write stage the learn
                leg and ``observation`` use — the composition-root obligation
                ADR-0078 §3 puts on every producer, so an ingested belief the policy
                defers parks a question the user can actually answer, and one it
                stores is retrievable and forgettable through the surfaces the user
                already has (ADR-0028 §4).

                **One stage per source, held as its own collaborator** (ADR-0142
                §3). It is named for its source rather than being *the* ingestion
                stage, and ``email_ingestion`` below is its sibling rather than an
                argument to it: "No ingestion stage holds more than one reader, and
                no ingestion stage dispatches over a collection of readers." A
                multiplexing stage would put one interval behind two sources and
                fuse their failure modes, which is what §3 refuses.

                **Optional, where its three siblings above are required, and the
                asymmetry is ADR-0093 §7 rather than laxity.** Every reader ships
                **disabled by default**, "and the reason is that nothing may read a
                user's personal files because a default said so" — so an engine
                with no reader is not a half-built engine, it is the default
                deployment, and requiring the stage would make every caller
                manufacture a reader for a source the operator never configured.
                What is *not* optional is what :meth:`ingest_calendar` does about it: it
                refuses rather than reporting an empty success, because a job that
                reports health while ingesting nothing is the failure mode this
                corpus keeps naming (ADR-0022 §4a).
            email_ingestion: The **email** source's read-only ingestion stage
                (ADR-0140, ADR-0142 §3), or ``None`` where this deployment
                configured no mail store. Everything said of ``calendar_ingestion``
                above holds of it unchanged — the same write stage, the same
                disabled-by-default reason, the same refusal rather than an empty
                success — and what is *not* shared is the point.

                **Its own stage over its own reader, and neither derived from the
                calendar's** (ADR-0142 §3, ADR-0096 §5). ADR-0093 §7 bounds a reader
                at one outstanding worker *per instance*, so two sources' ingestion
                can never contend for one reservation; ADR-0083 §7's serial loop
                makes the stronger statement anyway, that the two jobs never run
                concurrently at all.

                **A deployment may wire either, both or neither** (ADR-0142 §1).
                Neither collaborator is conditioned on the other's presence, and
                :meth:`ingest_email` refusing says nothing whatever about the
                calendar's state — §6's rule that no ingestion operation reports
                another source's state, applied at the constructor that could
                breach it.
            upcoming: ADR-0132's upcoming-event producer, or ``None`` where this
                deployment configured no calendar source. **Its own reader
                instance, and not ``calendar_ingestion``'s** (ADR-0132 §3): the two consumers
                read at their own cadence and neither derives its answer from the
                other's reading, and ADR-0093 §7's one-outstanding-worker
                reservation is per instance, so a shared reader would let one job's
                read suppress the other's.

                **It holds the notification seam this engine does not hand it.**
                The stage is given a ``NotificationWriter`` by the composition
                root — over the *same* store ``notifications`` names, or a ruled
                notification would be unreadable through the surfaces the user has
                (ADR-0028 §4) — because ADR-0130 §1 puts the seam with the producer
                and this façade is not one.

                Optional for ``calendar_ingestion``'s reason exactly, and
                :meth:`notice_upcoming_events` refuses rather than reporting an
                empty success for the same one.
            consolidation: The chunked consolidation stage (ADR-0106, ADR-0111), or
                ``None`` where this deployment wires none. It writes through the
                *same* write stage every other producer here uses — ADR-0106 §6
                obliges it by name, because a job calling ``MemoryWriter.ingest``
                directly would rule ``ASK_USER`` on a thousand consolidations and
                persist not one question — and it walks the **same ``MemoryStore``
                instance** ``memory`` names, or it would propose beliefs citing
                records the write path cannot resolve.

                **Optional for ``calendar_ingestion``'s reason**, one job over: the
                consolidation job ships disabled, so an engine without the stage is
                an ordinary deployment rather than a half-built one. And
                :meth:`consolidate` refuses rather than reporting an empty success,
                for the same reason again.
            notifications: The durable home of held notifications and the user's
                standing settings (ADR-0130 §9), or ``None`` where this deployment
                wires none — which every deployment does today, the ADR ratifying
                the contract surface ahead of a store to serve it. The five
                ``AssistantEngine`` methods behind it refuse with
                :class:`~ai_assistant.core.errors.ConfigurationError` in that
                state, on ``ingest_calendar``'s shape: "no store is wired" and "no
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
            routing: The operation-routing stage (ADR-0197 §1, §2), or ``None`` on a
                deployment that routes nothing — where the pipeline is exactly what it was
                before this decision, and every ask plans. **One parameter and not two**:
                ADR-0197 §9 puts the write-only ``RoutingRecorder`` on the *stage*, so the
                façade never holds a trail seam of any width and cannot be wired into the
                half-configured state where a stage could route without recording.
            transcriber: The speech-recognition seam ``converse_spoken`` transcribes
                through (ADR-0200 §1, §2), already wrapped in whatever deadline
                decorator the composition root wired (ADR-0118 §2) — ``None`` on a
                deployment with no speech engines, where ``converse_spoken`` refuses
                with a ``ConfigurationError`` rather than failing as though a seam
                had. Held here and nowhere else: no adapter in ``interfaces/`` calls
                either speech Protocol, and the whole composition is this engine's
                (ADR-0200 §2).
            synthesizer: The speech-synthesis seam, its sibling, under the same
                clauses. Wired or unwired **together** with ``transcriber``: half a
                pipeline can transcribe an utterance and never say the answer, which
                is a deployment nobody chose, so the constructor refuses it.
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
                §6), in bytes of **decoded** audio. The same figure both ways, for
                the reason ADR-0085 §8's limit is symmetric; what differs is the
                outcome, an oversized utterance being refused before any I/O and an
                oversized rendering degrading the turn.
            routed_confirmation_ttl: ``Settings.routed_confirmation_ttl`` (ADR-0197 §7).
                How long a routed park stays answerable before it is evicted and its
                ceiling slot released. Positive and finite, with no spelling for "never":
                a routed park is invisible — nothing enumerates it and no durable store
                recovers it — so without a lifetime a client that disconnected between the
                park and its token would hold a slot nothing could ever free. Elapse is
                measured against ``now``, never a wall clock read at the seam, so a test
                advances it rather than waits.
            recovery: ADR-0014 §4's startup scan, or ``None`` where a deployment
                composes none. Built by the composition root over the **same**
                plan store and audit store this façade holds, and driven once from
                :meth:`start` — which is where "at startup" lands in this system,
                the hub calling it at step 4 and accepting at step 6, so the
                precondition §4 states ("no executor is live for those states")
                is a fact about the listener rather than a promise made here. It
                is held as ``orchestration``'s own
                :class:`~ai_assistant.orchestration.recovery.RecoveryScan` because
                it is this subsystem's act: the scan reads the trail and the
                completer (ADR-0192 §9) and commits through the plan store, and
                nothing in `core` describes the composite.
            max_notification_budget: ADR-0131 §5a's
                ``hub_max_notification_budget``, the ceiling a poll's ``budget``
                is refused above. Not nullable, for §5a's reason.
            notification_policy: The deterministic ruling of ADR-0130 §4 and §5,
                wired **together with** ``notifications`` or not at all. §3 puts
                the ruling inside the store's critical section, so this façade
                only ever hands it over — it never rules anything itself, and a
                policy without a store would have nothing to rule about.
            closers: The resources the façade owns, as async close callables, in
                the order :meth:`aclose` must run them. The composition root hands
                these over so the façade is the defined owner that releases every
                connection on shutdown (ADR-0042 §2). Empty when the façade owns
                nothing (its collaborators are all in-memory).
            id_factory: Supplies opaque continuation-token handles; injectable so
                a test can assert a stable handle.
            epoch_factory: Supplies this engine's handle epoch, read **once** at
                construction (#1644). **Its contract: return a value no other engine
                over the same durable stores has used** — fresh per engine and so per
                process life — which is what makes ADR-0198 §4's "a token from a
                previous process life yields ``UnknownContinuationError``" true, and
                what :meth:`_mint_handle` composes every handle with. Defaulted to a
                UUID, so a composition root that says nothing honours it; and
                **trusted**, exactly as ``now`` below is trusted to return the instant
                it was asked for. :func:`~ai_assistant.core.clock.checked_clock`
                guards *conformance* at that seam — aware, UTC, localizable — and
                never *honesty*, and an epoch has no counterpart guard because the
                only thing an engine could check a fresh epoch against is durable
                state, which ADR-0198 §4 rules out ("process-scoped and never
                persisted"). A factory that repeats a value across two engines breaks
                the seam and gets what it asked for: two engines minting one handle.
                Separate from ``id_factory`` rather than reusing
                it, because the epoch's whole job is to differ between two engines
                that share one factory — which is exactly what a repeating
                ``id_factory`` produces and exactly the case the epoch exists for, so
                drawing both from one source would make them agree at the moment they
                must not. Injectable because ``CONTRIBUTING`` → "Determinism" puts
                randomness behind a seam, and because a test proving restart isolation
                should do it with two epochs it chose rather than with two real UUIDs
                and the hope they differ.
            now: The clock :meth:`purge_expired` measures ``trace_retention`` back
                from, and the only reading this façade takes — every other instant
                on this surface is stamped by the stage that owns the write.
                Injectable so a sweep is deterministic
                (``CONTRIBUTING``, "Determinism"), and guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
                reading is this class's own failure rather than a horizon quietly
                displaced.
            max_outstanding_confirmations: The ceiling on **unanswered** parked
                confirmations held in memory at once. Each holds the turn's
                ``TurnResult``, and entries are removed only on resolution, so a
                client that requests confirmable actions and abandons every token
                would grow the table without bound — a memory-exhaustion vector in
                a long-lived front end (a short-lived CLI barely touches it). At the
                ceiling the engine applies **backpressure** (:meth:`_admit_and_reserve`).

                **This is a global step-execution throttle at saturation, not a
                selective one.** The engine cannot know before running a step
                whether it will park (that is the policy's ruling, reached inside
                ``run``), and letting it run and *then* dropping the park would
                strand a durably-parked step (#287, round 7). So at the ceiling it
                refuses to drive **any** further step — including one that would be
                auto-allowed or find no capable tool — until an outstanding
                confirmation is resolved. Selective admission (throttling only
                would-be confirmations) awaits the durable-resume lane that can
                recover a dropped continuation (#287, #242). The default is high
                enough that this bites only a genuinely saturated system; a caller
                that wants a different policy sets it here. Must be a positive
                integer.
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

        Raises:
            TypeError: If ``max_outstanding_confirmations``,
                ``max_spoken_audio_bytes`` or ``max_payload_bytes`` is not an
                **exact** ``int`` (:func:`_check_positive_int`, which carries the
                reasoning). A ``bool`` is the named case
                (it is an ``int`` subclass and a flag is not a count), and a
                ``float`` like ``1.5`` is refused rather than compared — the same
                guard shape ``LearningLoop`` uses for its own count. On the two
                *bounds* the refusal is what keeps them able to bind at
                all: ``float("nan")`` compares ``False`` against every ``>``, so an
                engine built with one would admit a recording of any length and
                return a rendering of any length while reporting health, and one
                built with it as the contract limit would measure every argument and
                every result against a ceiling nothing can exceed.
            ValueError: If any of the three is not positive.
        """
        _check_positive_int(max_outstanding_confirmations, name="max_outstanding_confirmations")
        # ADR-0200 §6's ceiling, guarded on the same terms and for a sharper reason.
        # ``Settings`` refuses a non-integer or a non-positive value at load, but this
        # is a *constructor* argument and a composition root is not the only caller —
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
        self._loop = loop
        self._runner = runner
        self._plans = plans
        self._trail = trail
        self._spend = spend
        self._reads = reads
        self._memory = memory
        self._archive = archive
        self._deferrals = deferrals
        self._traces = traces
        self._trace_retention = trace_retention
        self._clock = checked_clock(now, owner="Engine")
        # The one emitter, built here rather than injected: ADR-0119 §8 puts the
        # envelope at `_tracked`, so its lifetime is this engine's and nothing
        # else may hold it. It is given the *guarded* clock above, so the trace's
        # instant and the purge's horizon are read through one seam (ADR-0026 §7).
        self._operation_traces = OperationTraces(sink=trace_sink, now=self._clock)
        self._conversations = conversations
        self._composing = composing
        self._observation = observation
        self._questions = questions
        self._grants = grant_operations
        self._recipient_grants = recipient_grant_operations
        self._connections = connection_operations
        self._calendar_ingestion = calendar_ingestion
        self._email_ingestion = email_ingestion
        self._upcoming = upcoming
        self._consolidation = consolidation
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
        self._notification_outbox = notification_outbox
        self._recovery = recovery
        #: Whether this engine has already run ADR-0014 §4's recovery scan. The
        #: scan's whole premise is that "no executor is live for those states"
        #: (§4), and this method is **also** the hub scheduler's recurring
        #: conversation-sweep job (``service/scheduler.py``'s job table names
        #: ``engine.start``), so an unguarded scan would run on a timer against a
        #: process serving turns and complete a *live* invocation's claim
        #: ``INDETERMINATE`` — the exact misclassification ADR-0192 §3 relies on
        #: that precondition to exclude. Guarded here rather than in the scan for
        #: :meth:`_recover_leases_once`'s reason: the engine is what the hub
        #: starts, so the ownership chain instance lock → one hub process → one
        #: composition root → one engine → one recovery ends here.
        self._recovery_scanned = False
        #: Serialises the check-scan-set above. A bare flag is not a guard across
        #: an ``await``: two overlapping ``start`` calls both read ``False``, the
        #: first scans and returns, an executor then claims a step, and the second
        #: resumes its already-started scan and completes that live claim. Its own
        #: lock rather than ``_lease_recovery_lock`` or ``_recovery_lock``, for the
        #: reason stated on the first of those — coupling two unrelated startup
        #: exclusions makes each one's reasoning the other's problem.
        self._recovery_scan_lock = asyncio.Lock()
        #: Whether this engine has already voided the delivery leases it inherited
        #: (ADR-0131 §3). Held here rather than in the outbox because the engine is
        #: what the hub starts: instance lock → one hub process → one composition
        #: root → one engine → one recovery. An outbox guarding itself would be
        #: guarding per object, and a second object over the same database in the
        #: same live process would still void a lease a device is holding.
        self._leases_recovered = False
        #: Serialises the check-recover-set that reads the flag above, so two
        #: overlapping ``start`` calls cannot both pass it. Its own lock rather than
        #: ``_recovery_lock``: that one guards the confirmation table's recovery and
        #: resolution, is held across a different critical section, and coupling two
        #: unrelated startup exclusions would make each one's reasoning the other's
        #: problem.
        self._lease_recovery_lock = asyncio.Lock()
        if max_notification_budget <= timedelta(0):
            msg = (
                f"max_notification_budget must be positive, got {max_notification_budget!r}: a "
                f"hub serving delivery with no budget bound has the failure the clause naming "
                f"it exists to prevent, so 'off' is not an available value (ADR-0131 §5a)"
            )
            raise ConfigurationError(msg)
        self._max_notification_budget = max_notification_budget
        if routed_confirmation_ttl <= timedelta(0):
            msg = (
                f"routed_confirmation_ttl must be positive, got {routed_confirmation_ttl!r}: a "
                f"zero or negative lifetime produces a card unusable the instant it is "
                f"rendered, and there is no spelling for 'never' (ADR-0197 §7)"
            )
            raise ConfigurationError(msg)
        if (transcriber is None) != (synthesizer is None):
            msg = (
                "a spoken turn needs both speech seams or neither: half a pipeline can "
                "transcribe an utterance and never say the answer, which is a deployment "
                "nobody chose. Wire a SpeechTranscriber and a SpeechSynthesizer together, "
                "or leave both unwired and converse_spoken refuses (ADR-0200 §1, §2)"
            )
            raise ConfigurationError(msg)
        self._routing = routing
        self._transcriber = transcriber
        self._synthesizer = synthesizer
        self._speakable_attested_sources = frozenset(speakable_attested_sources)
        self._max_spoken_audio_bytes = max_spoken_audio_bytes
        self._routed_ttl = routed_confirmation_ttl
        self._closers = tuple(closers)
        self._id_factory = id_factory
        self._max_outstanding = max_outstanding_confirmations
        self._max_payload_bytes = max_payload_bytes
        self._drain_timeout = drain_timeout
        self._parked: dict[str, _Parked] = {}
        self._routed_parks: dict[str, _RoutedPark] = {}
        #: The bindings this engine has **answered** and still retains, oldest
        #: settlement first (ADR-0198 §1, §4). Insertion order is settlement order —
        #: a handle settles at most once and a restatement never re-inserts — so the
        #: least recently settled record is the first key, which is what §4's bound
        #: discards. Bounded by ``max_outstanding_confirmations`` and by nothing
        #: else: no lifetime, no clock, and no setting of its own.
        self._settled: dict[str, _Settled] = {}
        #: The epoch and serial :meth:`_mint_handle` stamps every handle with
        #: (#1644). Two values, never a table: the serial makes a handle unique over
        #: this engine's whole life rather than over what is live now, and the epoch
        #: makes it unique across engines — the same pair, for the same reason, that
        #: ``InMemoryPlanStore`` and ``FakePlanStore`` mint ids from for ADR-0044
        #: §1's non-reuse guarantee, where "the sequence alone is process-local, so a
        #: restart would re-mint a prior id". Read once, here, so every handle this
        #: engine mints carries the same one.
        self._handle_epoch = epoch_factory()
        self._handle_serial = count(1)
        self._reserved: set[str] = set()
        self._reserved_routes: set[str] = set()
        self._recovery_lock = asyncio.Lock()
        self._inflight: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._shutdown: asyncio.Task[None] | None = None
        self._drain_phase = DrainPhase.NOT_RUN

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
        """Recover what a crash left in flight, then finish the sweeps (ADR-0014 §4, ADR-0076).

        **ADR-0014 §4's recovery scan first, and on the first call only.** A step
        left ``RUNNING`` by a process that died mid-call becomes ``INDETERMINATE``,
        and — since ADR-0192 §3 — every claim still open under that step's
        ``approval_ref`` is completed ``INDETERMINATE`` **before** the step's
        transition is committed. §4 puts the scan "at startup" and presumes no
        executor is live for those states, and that presumption is what the guard
        below keeps true: this method is *also* the hub scheduler's recurring
        conversation sweep, so a scan on every call would eventually run against
        this process's own live steps (:meth:`_recover_scan_once`). Skipped where
        no scan is wired.

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
            MemoryStoreError: If an episode a deletion must destroy could not be.
            NotificationOutboxError: If the outbox or the records it reconciles
                against cannot be read or written.
        """
        self._reject_if_closing()
        return await self._tracked(self._start(), "start")

    async def _start(self) -> None:
        """Recover what a dead process left in flight, then sweep, then reconcile.

        The recovery scan runs **first** of the four, and — unlike the two sweeps
        beside it — **only on the first call** (:meth:`_recover_scan_once`).
        Nothing else here reads planning state or the trail's invocation rows, so
        no ADR orders it against the sweeps; what running it first buys is that a
        step a previous process left ``RUNNING`` — and every claim open under its
        authorisation — is resolved before this engine does anything a caller can
        observe.
        """
        await self._recover_scan_once()
        await self._conversations.sweep_deletions()
        await self._conversations.reclaim()
        if self._notification_outbox is not None:
            await self._recover_leases_once()
            await self._notification_outbox.reconcile()

    async def _recover_scan_once(self) -> None:
        """Run ADR-0014 §4's recovery scan, once per engine (ADR-0192 §3).

        **Once, and that is what makes it a *startup* scan.** §4 authorises the
        scan because it "presumes no executor is live for those states" — true of a
        step the *previous* process left ``RUNNING``, false of one this process
        claimed a moment ago. :meth:`start` promises it is safe to call more than
        once and the hub's scheduler takes that promise literally: its job table
        wires ``engine.start`` as the recurring conversation sweep, so an unguarded
        scan would run on a timer inside a hub that is serving turns. It would then
        complete a **live** invocation's claim ``INDETERMINATE`` and commit its step
        out of ``RUNNING`` — after which the tool's real completion is refused
        ``InvalidCompletionError``, its executor's terminal write is refused stale,
        and the record says an act that in fact succeeded may or may not have
        happened. That is the misclassification ADR-0034 §1 and ADR-0014 §4 both
        exist to refuse, reached by running recovery at a moment recovery is not
        for.

        **The check, the scan and the flag are one critical section**, because a
        bare flag is not a guard across an ``await`` — the same finding adversarial
        review made against :meth:`_recover_leases_once` on its tenth round, and
        the same remedy. Two overlapping ``start`` calls both read ``False``; the
        first scans and returns, an executor then claims a step, and the second
        resumes its already-started scan over that live claim.

        **The flag is set only after the scan returns.** A scan that raised
        completed nothing it had not already committed, and ADR-0192 §3's ordering
        makes a re-run idempotent by construction: the interrupted step is still
        ``RUNNING``, so the next scan finds it and completes whatever is still open.
        Marking a failed attempt done would strand that step for the life of the
        process. In the deployment this runs in the question does not arise — the
        exception leaves ``start`` and the hub's startup fails — but the flag is a
        property of this class rather than of that caller.
        """
        if self._recovery is None:
            return
        async with self._recovery_scan_lock:
            if self._recovery_scanned:
                return
            await self._recovery.recover()
            self._recovery_scanned = True

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
        """Physically reclaim what the two Tier 1 stores and the trace store owe.

        The **maintenance surface** ADR-0083 §8 says this façade grows: "new
        *concrete* surface on a class in ``orchestration``, not ``core`` contract
        surface". Its only caller is the hub's scheduler (ADR-0083 §7), which holds
        an ``Engine`` and nothing else — no concrete store, no subsystem import —
        so it is a client of the same façade the CLI is a client of, which is what
        makes ADR-0076 §5's "a scheduler is a second caller of the same read"
        literally true rather than approximately.

        **One operation over three stores, deliberately.** ADR-0078 §10 item 8:
        the deferral queue's purge "is wired wherever ``purge_expired`` is wired and
        inherits the same fate… Inventing a second sweeping mechanism for one store
        would be the thing that has to be undone at leg 5." One method calling both
        is that instruction taken literally, and it is why
        ``tests/app/test_composition.py``'s sweep guard now names *this* method's
        body as the one place either name may be called (ADR-0083 §11). ADR-0119
        §10 applies the same instruction to the seventh database rather than
        re-deciding it — "the trace purge becomes the third call behind that same
        operation. The scheduler's job table does not change, no job acquires new
        store surface" — so this method grew a third call and nothing else did.

        **Correctness does not depend on the first two running.** Both Tier 1 stores
        exclude what is past its deadline at *read* time — ADR-0007 §2 ("This holds
        regardless of whether ``purge_expired`` has run, so the privacy guarantee
        does not depend on a background job") and ADR-0078 §6 — so a missed or late
        sweep is never a correctness bug. What it buys is ADR-0078 §1's *exposure
        cap*: unswept, a lapsed question's proposal is the user's own words sitting
        on disk indefinitely.

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
        memory, then questions, then traces, and nothing depends on it: no sweep
        reads another's rows.

        Returns:
            How many rows each store reclaimed, and ``None`` for the traces where
            the horizon is "keep forever".

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8), which is what
                :data:`ENGINE_SHUTTING_DOWN` exists for.
            MemoryStoreError: If the memory store could not be swept. The two later
                sweeps do **not** run in that case: nothing sequences them, so the
                next tick simply re-runs all three, and swallowing the first failure
                to reach the rest would report a sweep that half happened.
            DeferralStoreError: If the deferral queue could not be swept. The trace
                sweep does not run in that case, for the same reason.
            TraceStoreError: If the trace store could not be swept, or the clock the
                horizon is measured back from returned a non-conforming reading
                (ADR-0026 §4, :meth:`_now`). The store failure *does* reach the
                caller, unlike an emission failure: ADR-0119 §5 subordinates the
                instrument to the work being observed, and a sweep is not the work
                being observed — "a purge that silently did nothing would let a
                store grow without bound behind a horizon an operator believes is
                enforced".
        """
        self._reject_if_closing()
        return await self._tracked(self._purge_expired(), "purge_expired", _purged)

    async def _purge_expired(self) -> PurgeReport:
        """Sweep all three stores — **the only place any purge is called**.

        ADR-0083 §11 pins that claim mechanically rather than by convention: the
        composition-root guard scans the whole package for a call to ``purge``,
        ``purge_expired`` or ``purge_before`` by those bare attribute names,
        receiver-blind, and requires the set it finds to be *exactly* these three
        lines (plus the canonical fakes' own delegations, which implement a seam
        rather than schedule a sweep). A sweep added anywhere else — under a
        different name, over a different store, by a second timer — still fails it.
        ADR-0119 §10 extends that instruction to the trace store by name, so the
        third name joined the scan with the third call.

        The horizon is computed here and not held: ``trace_retention`` is a
        duration, and the instant it means is only ever *this* sweep's. It
        saturates rather than overflowing, because the arithmetic runs on
        configuration this system accepts (:func:`_horizon`).
        """
        records = await self._memory.purge_expired()
        questions = await self._deferrals.purge()
        traces = (
            None
            if self._trace_retention is None
            else await self._traces.purge_before(_horizon(self._now(), self._trace_retention))
        )
        held = None if self._notifications is None else await self._notifications.purge()
        return PurgeReport(records=records, questions=questions, traces=traces, notifications=held)

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error of the sweep that read it.

        ADR-0026 §4: ``core`` raises a bare ``ValueError`` because it cannot know
        what its caller will do with the failure, and "each subsystem translates at
        its own boundary". `orchestration` has no error of its own, so a seam here
        borrows "the error of the stage that read the clock" — goal construction
        raises ``PlanningError``, expiry raises ``MemoryStoreError``, and this
        reading exists only to place the trace horizon, so it raises
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

    async def ingest_calendar(self) -> IngestionReport:
        """Read the configured source once and propose what it read (ADR-0093 §6).

        The **maintenance surface**'s second scheduled operation, and leg 6's:
        "``Engine`` grows an ingestion operation for the job to call: new concrete
        surface in ``orchestration``, not ``core`` contract surface". Its only
        caller is the hub's scheduler (ADR-0083 §7), whose job body is this bound
        method and "holds no store, no reader and no subsystem import" — a client
        of the same façade the CLI is a client of.

        **Nothing else calls it, and nothing may wire it into a turn** (§6). No
        request-time run proposes anything and there is no ambient trigger:
        ingestion has a model-free but unbounded-in-consequence tail — a policy
        ruling, a write, possibly a parked question — and nobody is waiting for any
        of it, which is ADR-0077 §8's "Nothing is waiting on it, and a turn is."
        The facet read §3 permits at assembly time is a separate path that proposes
        nothing, runs on ``context``'s own reader instance, and is gated on its own
        ``FACET`` grant (ADR-0096 §5, ADR-0097 §2).

        **Takes no argument, deliberately.** The reader is given its own source and
        its own bound (§1, §5), so ``read()`` takes none either: a caller able to
        widen the read is a caller able to defeat the bound. It also makes this a
        legal ``JobBody``, which the scheduler's table requires.

        **The engine rules on nothing and writes nothing itself.** It delegates to
        the :class:`~ai_assistant.orchestration.ingestion.IngestionStage`, which
        reads the injected ``Reader`` and puts each returned proposal through the
        write stage — conflict resolution, the ``MemoryPolicy``'s ruling, the
        write, and the durable question a deferral raises all happen behind that
        seam, exactly as :meth:`learn` and :meth:`observe` do it. A reader inherits
        no part of ADR-0075's capture exemption (§1).

        **Enabled is a deployment's choice and off is the default.** §6 permits a
        reader's job to ship enabled "once §9's gate is discharged", and ADR-0092 —
        which is that gate — is ratified; so unlike observation, whose job is
        disabled for a reason no configuration can answer (ADR-0083 §7, §13),
        this one runs whenever the operator arms it. What it is *not* is on by
        default: §7 is emphatic that "nothing may read a user's personal files
        because a default said so", and ``calendar_reader_interval`` is ``None``
        until someone sets it (§7a).

        Tracked like every other public method, so shutdown drains the write it is
        in the middle of before closing the connections it is writing through
        (ADR-0042 §2).

        Returns:
            What the source proposed and what memory did with it. Every count zero
            is a **successful** pass over a source that had nothing to say within
            the bound, and no caller may read it as a failure (ADR-0093 §8).

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8), which is what
                :data:`ENGINE_SHUTTING_DOWN` exists for.
            ConfigurationError: If this engine was built with no ingestion stage,
                which after ADR-0102 §7 means exactly one thing: no configured
                reader. **The message named two conditions until ADR-0102**, the
                second being "no grant seam to gate it on" — a real state while
                nothing could construct a ``SourceGrantStore`` and ``build_engine``
                took a ``grants`` parameter its one production caller never filled
                (#684). ``build_engine`` now opens the store itself, so an engine
                either has a grant seam or does not build, and naming that
                condition here would send an operator looking for something that
                cannot be missing. Refusing is still the point: an empty report
                would be
                indistinguishable from a source that had nothing to say, so a
                deployment whose stage failed to wire would look healthy forever
                while ingesting nothing — the shape ADR-0022 §4a refuses, and the
                same reason §8 makes a failed *read* raise rather than return an
                empty reading. The message names **both** conditions, because they
                are different facts and an operator told the wrong one looks in the
                wrong place.
            SourceNotGrantedError: If no live ``INGEST`` grant covers the source at
                the moment of the read, or if one is revoked while the read is in
                flight (ADR-0097 §5). Distinct from the error above: that one is a
                deployment that cannot ask, this one is a user who has not said
                yes. The scheduler logs it and retries at the next due instant, so
                a revoked grant left beside a configured interval logs a refusal
                every interval — configuration and consent disagreeing out loud,
                which is the state ADR-0093 §7's clause exists to make visible.
            ReaderError: If the read could not complete because of its source. The
                scheduler logs it with its class and retries at the next due
                instant, and never takes the process down (§6, ADR-0083 §7) — a
                reader's source is a file the system does not own, so
                unreadability is an ordinary state of the world rather than a
                defect. Its message is payload-free by contract, which is what
                keeps the source's path out of the operational log (§8, ADR-0004
                §5).
            MemoryStoreError: If the write path failed. A partially applied reading
                is left as it stands and nothing claims success for it (ADR-0022
                §4); ``beliefs`` shows exactly what landed.
            DeferralStoreError: If a deferred question could not be parked.
        """
        self._reject_if_closing()
        if self._calendar_ingestion is None:
            msg = (
                "no calendar ingestion stage is wired, so there is nothing to "
                "ingest from the calendar; it needs a configured source "
                "(ASSISTANT_CALENDAR_READER_PATH, ADR-0093 §7a). Configuration says "
                "where a source is; a grant says whether it may be read, and "
                "neither stands in for the other"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._calendar_ingestion.ingest(), "ingest_calendar", _ingested)

    async def ingest_email(self) -> IngestionReport:
        """Read the configured mail store once and propose what it read (ADR-0140).

        The **maintenance surface**'s scheduled operation for the system's second
        ingestion source, added *beside* :meth:`ingest_calendar` rather than through
        it. It carries no ordinal because the surface has stopped being a list and
        started being a list *plus one entry per source*, which is ADR-0142 §8's
        counted cost: five enumerated artefacts per source until ADR-0093 §11's
        registry fires at the third. ADR-0142 §4: "Each configured ingestion source is driven by its
        **own** public operation on the concrete ``orchestration`` engine, returning
        that source's ``IngestionReport``. No ingestion operation takes a source
        argument, a source name, or any argument at all."

        **Why not one operation taking a source, which is the option that had to be
        argued down.** ``functools.partial(engine.ingest, "email")`` satisfies
        ``JobBody`` structurally and is, in a sense, a public ``Engine`` call. §4
        refuses it on four grounds, and the one no care repairs is the trace: the
        ``seam`` this method hands :meth:`_tracked` is the ``OPERATION`` record's
        one wiring point (ADR-0119 §8), and a single parameterised operation emits
        one seam for every source. Putting the source in the trace instead is
        already foreclosed — :func:`_ingested` records that
        ``IngestionReport.source`` "is deliberately left off" because ADR-0119 §2
        admits no runtime-read string into a trace — so under a discriminator no
        ``OPERATION`` record could say which source ran or which one is failing.
        Two literal seams is what buys that back, and it is why this method exists
        rather than a parameter.

        **Its own stage, its own reader, its own grant** (ADR-0142 §3, §7). The
        stage is a second construction of the same
        :class:`~ai_assistant.orchestration.ingestion.IngestionStage` the calendar's
        uses — zero new machinery, which is the strongest available evidence that
        the seam was cut in the right place at leg 6 — over an ``EmailReader``
        instance the composition root builds for this consumer alone (ADR-0096 §5).
        The read is gated on a live ``INGEST`` grant for *this* source's declared
        identity: "No grant on one source authorises a read of another, whatever
        its scope."

        **Independent of the calendar's in both directions** (ADR-0142 §1). This
        source is armed on ``email_reader_interval`` and on nothing else; arming or
        retuning it changes the calendar's cadence in no way, and arming the
        calendar's arms no mail read. A deployment may run either, both or neither.
        The direction worth naming is the one a default would breach: nothing here
        falls back to ``calendar_reader_interval``, because that would silently arm
        a read of the user's mail because they had armed a read of their calendar.

        **Takes no argument, deliberately** — :meth:`ingest_calendar`'s reason
        unchanged: the reader is given its own source and its own bound, so a caller
        able to widen the read is a caller able to defeat the bound. It is also what
        makes this a legal ``JobBody``, which the scheduler's table requires.

        **Nothing else calls it, and nothing may wire it into a turn** (ADR-0093
        §6). The facet read a request-time assembly performs is a separate path on
        ``context``'s own reader instance, gated on its own ``FACET`` grant, and it
        proposes nothing.

        **Arming it is three independent acts and the recipe is not here.** The
        operator sets ``ASSISTANT_EMAIL_READER_INTERVAL`` (unset, this operation has
        no caller), the user grants the source ``ingest``, and a fetcher outside
        this system keeps the store current. All three are written out, with the
        command forms that exist and the duration forms the first one accepts, in
        :mod:`ai_assistant.readers.email`'s module docstring — beside the source's
        own deployment recipe, because that is where an operator connecting a mail
        store is already reading and this project has no operator-facing docs tree
        to hold it (#887, #981).

        Returns:
            What the mail store proposed and what memory did with it. Every count
            zero is a **successful** pass over a source that had nothing to say
            within the bound, and no caller may read it as a failure (ADR-0093 §8).
            It is also indistinguishable from a fetcher that stopped running, which
            ADR-0140 §1 accepts rather than patches: the fetcher is monitored where
            the operator monitors processes, never through this system's surfaces.

        Raises:
            RuntimeError: If the engine is shutting down, exactly as
                :meth:`ingest_calendar` raises it.
            ConfigurationError: If this engine was built with no **email** ingestion
                stage, which means one thing: no configured mail store. The message
                names ``ASSISTANT_EMAIL_SOURCE_PATH`` and no other source's
                configuration (ADR-0142 §6) — one shared message is the trap here,
                because an operator told "no ingestion stage is wired" by an engine
                ingesting the calendar every hour looks in the wrong place.
            SourceNotGrantedError: If no live ``INGEST`` grant covers **this**
                source at the moment of the read, or if one is revoked while the
                read is in flight (ADR-0097 §5). A grant on the calendar authorises
                nothing here. Distinct from the error above: that one is a
                deployment that cannot ask, this one is a user who has not said yes.
            ReaderError: If the read could not complete because of its source — a
                missing, unreadable, non-regular or oversized store, a store framing
                more messages than the cap, proposals past the content budget, or a
                deadline expiry. The scheduler logs it with its class and retries at
                the next due instant, and the calendar's job is neither disarmed nor
                affected (ADR-0142 §7). Its message is payload-free by contract,
                which is what keeps the mail store's path out of the operational log.
            MemoryStoreError: If the write path failed, as
                :meth:`ingest_calendar` raises it.
            DeferralStoreError: If a deferred question could not be parked.
        """
        self._reject_if_closing()
        if self._email_ingestion is None:
            msg = (
                "no email ingestion stage is wired, so there is nothing to ingest "
                "from email; it needs a configured source "
                "(ASSISTANT_EMAIL_SOURCE_PATH, ADR-0140 §12). Configuration says "
                "where a source is; a grant says whether it may be read, and "
                "neither stands in for the other"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._email_ingestion.ingest(), "ingest_email", _ingested)

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

        **Takes no argument, deliberately** — ``ingest_calendar``'s reason unchanged: the
        reader is given its own source and its own bound, so a caller able to widen
        the read is a caller able to defeat the bound. It is also what makes this a
        legal ``JobBody``.

        **The engine concludes nothing itself.** It delegates to
        :class:`~ai_assistant.orchestration.upcoming.UpcomingEventStage`, which
        gates the read on a live ``NOTIFY`` grant (ADR-0133 §5), walks the
        reading's per-occurrence proposals, and offers what falls inside the lead
        window through ADR-0130 §3's seam. The disposition is that seam's and the
        policy's; nothing here selects, ranks or influences one (ADR-0132 §8).

        **Independent of ingestion in both directions** (ADR-0132 §3, §4). It has
        its own reader instance, its own interval and its own grant scope, so
        arming or retuning it changes ingestion's cadence in no way and arming
        ingestion arms no producer. A deployment may run either, both or neither.

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
                rules the three uses independent, so a live ``INGEST`` grant on this
                calendar authorises this read no more than a ``FACET`` one does.
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

    async def consolidate(self) -> ConsolidationReport:
        """Distil stored records into durable beliefs, one bounded run (ADR-0106).

        The **maintenance surface**'s third scheduled operation. ADR-0083 §8 already
        settled that this is "new *concrete* surface on a class in
        ``orchestration``, not ``core`` contract surface", and ADR-0085 §1 fixes the
        promoted ``AssistantEngine`` Protocol at fifteen *request* methods with
        lifecycle deliberately off it — "a Protocol constrains what an
        implementation must have, not what it may not". :meth:`purge_expired` and
        :meth:`ingest_calendar` are the standing proof, and ADR-0114 §9 records this as a
        non-decision so the implementing lane does not relitigate it.

        **Takes no argument, deliberately**, which is what makes it a legal
        ``JobBody`` and keeps the whole of the chunking below the façade where
        ADR-0111 §1 put the cursor. The scheduler holds an ``Engine`` and nothing
        else — no store, no cursor, no subsystem import — and "neither reads it,
        writes it, nor passes it".

        **One run, not a walk to exhaustion.** It commits chunks until its work is
        exhausted or its run budget is spent, then returns; the scheduler re-arms it
        from completion plus its interval exactly like a job that finished, because
        it is not told which happened and does not need to be (ADR-0111 §4). A run
        that halts at a chunk it could not record as done is a **completed run that
        did not exhaust its work**, never a failure — recording it as one would make
        a queue at its cap indistinguishable from a broken store (ADR-0111 §9).

        Tracked like every other public method, so shutdown drains the write it is
        in the middle of before closing the connections it is writing through
        (ADR-0042 §2).

        Returns:
            What the run did, in Tier 2 counts and two dispositions. Every count
            zero is a **successful** pass over material that justified nothing, and
            no caller may read it as a failure.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8), which is what
                :data:`ENGINE_SHUTTING_DOWN` exists for.
            ConfigurationError: If this engine was built with no consolidation
                stage, for :meth:`ingest_calendar`'s reason: an empty report would be
                indistinguishable from material that justified nothing, so a
                deployment whose stage failed to wire would look healthy forever
                while consolidating nothing — the shape ADR-0022 §4a refuses.
            MemoryStoreError: If the store could not be read or the write path
                failed. The cursor is left where it was, so the chunk in flight is
                re-processed on the next run (ADR-0111 §3).
            ModelError: Propagated unwrapped from the provider, its classification
                intact (ADR-0013 §5). Same disposition: nothing is recorded as done.
            DeferralStoreError: If a deferred question could not be parked.
        """
        self._reject_if_closing()
        if self._consolidation is None:
            msg = (
                "no consolidation stage is wired, so there is nothing to consolidate; "
                "it needs a model provider and the memory store the write stage "
                "persists to (ADR-0106 §6, ADR-0111 §4)"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._consolidation.run(), "consolidate", _consolidated)

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam which owns the deadline (ADR-0029 §4)
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Run one turn and drive the step it produces (ADR-0042 §3, ADR-0074 §2).

        The adapter passes the user's raw utterance — unrewritten; intent is the
        engine's, not the adapter's (ADR-0042 §3). The turn is planned, then its
        **first** step is driven through :class:`StepRunner`; a multi-step plan
        has only that step driven today, the rest awaiting the plan-driving stage
        (module docstring).

        **Every turn runs under a conversation, and the outcome reports which**
        (ADR-0074 §2). Passing no id starts one; passing one continues it. The
        conversation is resolved **before** the turn's work, so its id exists
        independently of whether the turn succeeds and so a continuation is not
        racing the reclaim that would drop an idle conversation. A turn that fails
        outright therefore leaves an empty conversation, which is harmless and
        reclaimable. The conversation's recent turns are then handed to the planner
        ahead of the relevance-retrieved beliefs (§5), and the exchange is captured
        as one ``EpisodicMemory`` once the outcome exists (§3).

        Args:
            utterance: What the user said, passed through untouched.
            timeout: The **per-attempt** budget (ADR-0029 §4, ADR-0042 §3),
                keyword-only and required — the contract has no spelling for
                "forever". Threaded to the executor for the one authorised call a
                driven step makes. It is *not* an overall wall-clock deadline for a
                multi-step request; that is a follow-on decided with the
                plan-driving stage (ADR-0042 §3).
            conversation_id: The conversation to continue, or ``None`` to start a
                fresh one. Untrusted input from an adapter: an id the store does
                not know is **refused, not silently started**, because silently
                starting one turns a typo or a stale copy-paste into "my
                conversation vanished" and lands the user's continuation somewhere
                they cannot find (ADR-0074 §1).

        Returns:
            The turn's result and the disposition of the step it drove — including
            a parked confirmation to render and relay (ADR-0042 §4) — plus the
            conversation it ran under, whether recording it degraded, and the
            composed answer (ADR-0170 §3). ``step`` is ``None`` when the plan had no
            step. ``reply`` carries prose on every shape but a park, where what the
            user must answer is the confirmation, and a pass whose composition
            failed, which sets ``reply_degraded`` instead (ADR-0170 §4). The
            adapter renders the answer **in addition to** the step account, never
            instead of it: where the two disagree the step account is correct by
            construction (ADR-0170 §6).

        Raises:
            RuntimeError: If the engine is shutting down (:meth:`aclose` has been
                entered), so no new work is accepted.
            UnknownConversationError: If ``conversation_id`` names no conversation
                this store holds, or names one the user deleted.
            PlanningError: If the utterance is blank, a transition is rejected, or
                a clock reading is non-conforming — as the stages raise.
            ContextError: If context assembly failed outright.
            AuditError: If the trail would not accept or hand back a decision.
            ToolBindingError: If an authorised call fails its own revalidation.
        """
        self._reject_if_closing()
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments(
            "converse",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        return await self._tracked(
            self._converse(utterance, timeout=timeout, conversation_id=selected),
            "converse",
            checked=True,
        )

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Run one turn as :meth:`converse` does, streaming the answer (ADR-0173 §4).

        Every clause :meth:`converse` declares binds here: the same arguments in the
        same shape, the same conversation resolution, the same refusals and the same
        failures. What differs is that the composed answer is yielded as it arrives,
        as zero or more :class:`~ai_assistant.core.types.ReplyChunk` values followed
        by exactly one :class:`~ai_assistant.core.types.TurnOutcome`.

        **The local refusals are raised from the call, not from the iteration**, as
        they are on :meth:`converse` and as ``StreamingCompleter.stream`` raises its
        own: a caller that never iterates still learns that its utterance had no
        encoding or its conversation id was blank, and ADR-0085 §9's "refused
        locally, before any I/O" stays true of a method whose I/O has not started.

        **A client that goes away does not abandon the turn** (ADR-0173 §9). The
        turn runs inside a tracked task of its own, so abandoning or closing this
        iterator leaves it running to its ordinary completion — including its
        capture — and the undelivered chunks and outcome are simply discarded. A
        turn may already have approved and executed a non-idempotent tool before a
        single word was composed; abandoning it would leave that effect committed
        and the exchange uncaptured, whose natural retry can perform it twice.

        Args:
            utterance: What the user said, passed through untouched.
            timeout: The per-attempt budget, as :meth:`converse`.
            conversation_id: The conversation to continue, or ``None``.

        Returns:
            An async iterator over the answer's chunks and then the turn's outcome.
            Close it if you stop reading part-way (:func:`contextlib.aclosing`).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``conversation_id`` is blank or the utterance has no
                UTF-8 encoding.
            OversizedValueError: If the arguments exceed the contract limit.
        """
        self._reject_if_closing()
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments(
            "converse_streaming",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        return self._streamed(utterance, timeout=timeout, conversation_id=selected)

    async def _streamed(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        conversation_id: str | None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Drive the turn in a tracked task and relay what it publishes.

        **The turn runs beside this generator rather than inside it**, and that
        split is what ADR-0173 §9 costs. An async generator's cleanup runs while it
        is being *closed*, so a turn driven inside one would have to finish its
        capture during ``GeneratorExit`` — which cannot await — or be abandoned
        mid-flight, which §9 forbids. Running it as an ordinary task lets a client
        walk away while the turn completes, and puts it in ``_inflight`` so
        :meth:`aclose` still drains it (ADR-0042 §2).

        **The queue is unbounded, and it is bounded all the same.** ADR-0173 §3
        caps the published answer at the room the terminal frame has, and nothing
        else is ever put here — so the queue holds at most one more copy of a
        payload the outcome already carries. A bounded queue would be the wrong
        trade: a client that stopped reading would block the producer forever, and
        the turn §9 promises to finish would never finish.
        """
        chunks: asyncio.Queue[ReplyChunk] = asyncio.Queue()
        turn = self._track(
            self._checked_result(
                self._converse_streaming(
                    utterance, timeout=timeout, conversation_id=conversation_id, chunks=chunks
                ),
                "converse_streaming",
            ),
            "converse_streaming",
        )
        # A turn nobody reads still fails legibly rather than as asyncio's
        # "Task exception was never retrieved" on the next collection: §9 makes an
        # abandoned stream ordinary, so its failure has to be *observed* somewhere
        # even when no caller is left to be told.
        turn.add_done_callback(_note_failure)
        # **A settled getter is buffered output, and the loop treats it as such.**
        # It holds the *oldest* chunk — it took the head of the queue — so it is
        # drained before the queue itself, and the loop ends only when all three
        # are empty: the getter, the queue, and the turn. The obvious shape, which
        # exits on ``turn.done() and chunks.empty()``, is correct only if a settled
        # getter can never coexist with a queue this loop is still draining; that
        # happens to hold today, because ``put_nowait`` schedules a parked getter's
        # wake before anything that could resume this coroutine — but it is an
        # argument about ready-queue order, and a chunk the terminal ``reply``
        # repeats and nobody was yielded is too sharp an edge to leave resting on
        # one (ADR-0173 §3).
        waiting: asyncio.Task[ReplyChunk] | None = None
        try:
            while True:
                if waiting is not None and waiting.done():
                    yield waiting.result()
                    waiting = None
                    continue
                if not chunks.empty():
                    yield chunks.get_nowait()
                    continue
                if turn.done():
                    break
                if waiting is None:
                    waiting = asyncio.ensure_future(chunks.get())
                await asyncio.wait({waiting, turn}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            # Cancelling a parked ``Queue.get`` cannot lose an item: ``put_nowait``
            # appends before it wakes a getter, so anything already queued is still
            # there for the drain above. The turn itself is deliberately **not**
            # cancelled — §9 again.
            if waiting is not None and not waiting.done():
                waiting.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiting
        # ``result()`` re-raises whatever the turn raised, which is the terminal
        # error frame's value one layer down (ADR-0173 §1).
        yield turn.result()

    async def converse_spoken(
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget for the whole call, threaded to each stage (ADR-0029 §4)
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Run one turn from a recording and speak its answer (ADR-0200 §3, ADR-0205 §1).

        **The whole composition is here** (ADR-0200 §2): transcribe, decide whether
        anything was said, run the ordinary turn with its answer composed for a
        channel of unbounded audience, pick a format, render. No adapter performs any
        part of it and none calls either speech Protocol at all.

        **Every refusal below is local and comes before transcription**, which is
        I/O — so a malformed ``conversation_id``, an empty ``plays``, a recording in
        a container the transcriber cannot decode and a recording over ADR-0200 §6's
        bound are each settled before a seam is called and before there is any
        transcript to be blank. Base64 decoding is not I/O, which is what lets the
        size check sit here rather than after the seam (ADR-0200 §6).

        **A recording that carried no words is not an error** (ADR-0200 §4). Where
        the transcript is blank — empty, or whitespace only — no turn runs, no
        episode is captured, no conversation is created, and the result is four
        members saying so.

        **A turn that parks on a confirmation is spoken, not silent** (ADR-0207 §1).
        On both of §1's shapes — a step the permission gate parked and a confirm-owed
        route the routing stage parked — no answer is composed and ``outcome.reply``
        stays ``None``, and what is rendered is the one fixed sentence §2 fixes,
        synthesised by this same stage under the same bounds and the same degradation
        ladder as an answer. Silence on a push-to-talk surface is indistinguishable
        from a hub that is down (#1699). The park itself is unchanged: the same
        confirmation is minted and carried on the same result, and the order in which
        a caller presents the card and the audio is the caller's own.

        Args:
            utterance: The recording.
            plays: What the caller can render, in **preference order**. Required,
                non-empty, and read as a codec capability rather than as a claim
                about who can hear (ADR-0200 §3): nothing on the disclosure path
                reads it.
            timeout: The budget for the whole call — transcription, the turn and
                synthesis together — threaded to each stage.
            conversation_id: The conversation to continue, or ``None``.
            delivery: What a device played of an **earlier** turn of this
                conversation, naming that turn by the ``episode_id`` a previous call
                disclosed (ADR-0205 §1). Recorded before anything else this call
                does; discarded where the conversation carries no turn under that
                id, or where that turn is already stamped.

        Returns:
            The transcript, the turn it drove, the rendering of its answer — or of
            ADR-0207 §2's sentence where the turn parked — whether speaking it
            degraded, and the id of the episode recording the turn.

        Raises:
            RuntimeError: If the engine is shutting down, exactly as
                :meth:`converse` refuses.
            ConfigurationError: If this engine was built with no speech seams. **A
                property of this object's wiring rather than of the contract**, in
                the shape :meth:`ingest_email` refuses an unconfigured source and
                for the reason ``AssistantEngine``'s own docstring gives for a
                shutting-down engine's ``RuntimeError``: it is not a declared
                failure of the promoted method, and an implementation that has
                speech never raises it. Deliberately **not**
                :class:`~ai_assistant.core.errors.TranscriptionFailedError`, which
                would report a deployment fact as a seam failure and invite a retry
                that cannot succeed.
            ValueError: If ``conversation_id`` is blank, ``plays`` is empty, the
                transcriber's ``formats`` does not name the recording's
                ``media_type``, a ``delivery`` was supplied beside a
                ``conversation_id`` of ``None``, or a supplied ``delivery`` carries a
                state of ``UNKNOWN`` — each refused locally, before any I/O
                (ADR-0205 §1, §2).
            OversizedValueError: If the recording's decoded length exceeds
                ``max_spoken_audio_bytes``, refused locally and before any I/O; or if
                the result breaches ADR-0085 §8c even with no rendering in it.
            TranscriptionFailedError: If transcription failed, carrying this
                project's own classification and raised ``from None``.
            UnknownConversationError: If ``conversation_id`` names no conversation
                this store holds — and only where a turn actually ran.
        """
        self._reject_if_closing()
        transcriber, synthesizer = self._speech_seams()
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        if not plays:
            msg = (
                "plays must name at least one format the caller can render; an empty "
                "preference order is a call that could not be answered whatever the "
                "synthesizer produces (ADR-0200 §3)"
            )
            raise ValueError(msg)
        self._check_report(delivery, conversation_id=selected)
        check_arguments(
            "converse_spoken",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            plays=plays,
            timeout=timeout,
            conversation_id=selected,
            delivery=delivery,
        )
        self._check_recording(utterance, transcriber=transcriber)
        return await self._tracked(
            self._converse_spoken(
                utterance,
                plays=plays,
                timeout=timeout,
                conversation_id=selected,
                transcriber=transcriber,
                synthesizer=synthesizer,
                delivery=delivery,
            ),
            "converse_spoken",
            checked=True,
        )

    @staticmethod
    def _check_report(
        delivery: SpokenDeliveryReport | None, *, conversation_id: str | None
    ) -> None:
        """Refuse a report no conversation can hold, and one that reports nothing.

        ADR-0205 §1's and §2's two local refusals, **before any I/O** and before the
        recording is looked at, on ADR-0085 §3's convention for a malformed argument.

        A report beside no conversation names a turn that cannot exist — a fresh
        conversation contains none — and an ``UNKNOWN`` report is a value this hub
        writes at capture and never one a caller supplies: a device that does not
        know reports nothing, and the absence of a report is spelled by omitting the
        argument.

        Args:
            delivery: The report, or ``None``.
            conversation_id: The conversation named, already validated.

        Raises:
            ValueError: If either refusal applies.
        """
        if delivery is None:
            return
        if conversation_id is None:
            msg = (
                "a delivery report names a turn of a conversation, and a fresh "
                "conversation contains no turn one could name; supply the conversation "
                "this report is about, or no report (ADR-0205 §1)"
            )
            raise ValueError(msg)
        if delivery.delivery.state is SpokenDeliveryState.UNKNOWN:
            msg = (
                "a device that does not know reports nothing: UNKNOWN is what this hub "
                "writes for an unreported turn, and the absence of a report is spelled "
                "by omitting the argument (ADR-0205 §2)"
            )
            raise ValueError(msg)

    def _speech_seams(self) -> tuple[SpeechTranscriber, SpeechSynthesizer]:
        """The two seams, or a refusal naming what this deployment lacks.

        Returns:
            The transcriber and the synthesizer.

        Raises:
            ConfigurationError: If this engine was built with neither.
        """
        if self._transcriber is None or self._synthesizer is None:
            msg = (
                "no speech seams are wired, so there is nothing to transcribe with and "
                "nothing to speak through; a spoken turn needs both a SpeechTranscriber "
                "and a SpeechSynthesizer from the composition root (ADR-0200 §1, §2)"
            )
            raise ConfigurationError(msg)
        return self._transcriber, self._synthesizer

    def _check_recording(self, utterance: SpokenAudio, *, transcriber: SpeechTranscriber) -> None:
        """Refuse a recording this engine will not hand to a seam (ADR-0200 §6, §9).

        Both refusals are **local and before any I/O**, which base64 decoding is
        not. The container is checked against the transcriber's own ``formats``
        rather than against the enum, because ADR-0200 §1 has the engine read that
        property before it calls — so a conforming engine never provokes the seam's
        own ``ValueError``.

        **Neither message carries the recording.** ADR-0200 §8 keeps audio out of
        every log and every surfaced error, and a refusal is exactly where a length
        or a fragment would otherwise be interpolated for helpfulness. What is named
        is the limit, the field and the measured size — which is
        :class:`~ai_assistant.core.errors.OversizedValueError`'s own structured
        state, the same three values every other oversized refusal carries.

        Args:
            utterance: The recording.
            transcriber: The seam it would go to.

        Raises:
            ValueError: If the container is one this transcriber cannot decode.
            OversizedValueError: If the decoded audio is over the bound.
        """
        if utterance.media_type not in transcriber.formats:
            readable = ", ".join(sorted(member.value for member in transcriber.formats))
            msg = (
                f"this hub's transcriber decodes {readable or 'nothing'}, and the "
                f"recording is {utterance.media_type.value}; a container it did not "
                f"declare is refused rather than guessed at (ADR-0200 §1, §9)"
            )
            raise ValueError(msg)
        size = len(utterance.decoded())
        if size > self._max_spoken_audio_bytes:
            msg = (
                f"the recording decodes to {size} bytes, over the "
                f"{self._max_spoken_audio_bytes}-byte hub_max_spoken_audio_bytes limit "
                f"(ADR-0200 §6)"
            )
            raise OversizedValueError(
                msg,
                limit=self._max_spoken_audio_bytes,
                size=size,
                field="hub_max_spoken_audio_bytes",
            )

    async def _converse_spoken(  # noqa: PLR0913 — the call's five arguments plus the two seams it was checked against
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to each stage (ADR-0029 §4)
        conversation_id: str | None,
        transcriber: SpeechTranscriber,
        synthesizer: SpeechSynthesizer,
        delivery: SpokenDeliveryReport | None,
    ) -> SpokenTurn:
        """Compose the three stages under one budget (ADR-0200 §3, §4).

        **The budget is threaded rather than divided** (ADR-0029 §4). Each stage is
        given what is left of the caller's, so the effective bound on a speech stage
        is the lesser of that and the decorator's own — a stage never outlives the
        call, and a generous deployment setting never overrides a tight caller. A
        budget already exhausted when a stage is reached is that stage's expiry and
        is not a separate case.

        **The translation is total and stated both ways** (ADR-0200 §4). A
        ``SpeechError`` out of ``transcribe`` — and nothing else — becomes
        :class:`~ai_assistant.core.errors.TranscriptionFailedError`; a
        ``SpeechError`` out of ``synthesize`` — and nothing else — degrades. Every
        other exception propagates unchanged, so each stage catches ``SpeechError``
        and neither catches ``Exception``: a stage that could be wholly broken while
        every call reported the same classified-looking degradation is the state
        hardest to notice (ADR-0170 §8's own shape). A delivered cancellation is
        neither, and propagates.

        **The report is recorded first of all** (ADR-0205 §1). It is a fact about a
        turn that has already happened and it does not depend on this one, so it is
        written before the transcription seam is reached and therefore before the
        turn plans — which is what keeps a transcription failure, a blank recording,
        a degradation, an expiry or a cancellation from losing it. The one
        consequence worth naming is that a report supplied against a conversation
        this hub does not hold is refused *before* the no-words shape can be
        returned, where a call carrying no report would have returned it: the id is
        wrong either way, and the refusal is the one :meth:`_run_turn` would have
        raised a moment later.

        Returns:
            The spoken turn.

        Raises:
            TranscriptionFailedError: If transcription failed.
            OversizedValueError: If the result breaches ADR-0085 §8c with no
                rendering in it.
            UnknownConversationError: If a report was supplied against a
                conversation this store does not hold.
        """
        loop = asyncio.get_running_loop()
        started = loop.time()
        budget = timeout.total_seconds()

        def remaining() -> float:
            return budget - (loop.time() - started)

        if delivery is not None:
            # `conversation_id` is not None here: `_check_report` refused that pair
            # before any I/O.
            await self._conversations.record_delivery(str(conversation_id), delivery)
        heard, failed = await self._transcribed(transcriber, utterance, seconds=remaining())
        if failed is not None:
            # Raised **outside** the ``except`` block that caught the seam's failure,
            # which is stricter than ``from None`` alone. ``from None`` sets
            # ``__cause__`` to ``None`` and suppresses the context in a rendered
            # traceback, but leaves the seam's exception reachable as ``__context__``
            # — and a ``SpeechError`` takes arbitrary text, so an implementation that
            # interpolated the clip it could not decode would still have put the
            # recording somewhere a caller can read (ADR-0200 §4, §8). Raising with no
            # exception in flight leaves nothing to attach.
            msg = (
                f"the recording could not be transcribed; this hub classifies the "
                f"failure as {failed.value} (ADR-0200 §4)"
            )
            raise TranscriptionFailedError(msg, failure=failed) from None
        if not heard.strip():
            # ADR-0200 §4: nothing was asked, so nothing was answered. No turn, no
            # capture, no conversation, and no exception — and ``heard`` is typed
            # ``NonBlankEncodableText | None``, so a blank transcript has nowhere
            # else to go.
            return SpokenTurn()
        # ADR-0203 §1: this operation declares its channel audience unbounded
        # (ADR-0200 §3), so the withholding binds the supply the **whole turn** runs
        # over. One applier is minted per call — as the capacity handle is — and it is
        # threaded twice: into the turn, where it subtracts between retrieval and
        # planning, and into the composer, which reads the bare fact off it afterwards
        # (ADR-0199 §5's third clause).
        supply = UnboundedAudienceSupply(
            speakable_attested_sources=self._speakable_attested_sources
        )
        # ADR-0205 §4: every turn of *this* operation is stamped `UNKNOWN` at
        # capture, and no turn of any other is. One handle is minted per call, as the
        # applier above is and as the capacity handle is, and it carries the value
        # capture writes down and the episode id capture allocated back up — so the
        # fact that this call ran on `converse_spoken` reaches the capture point as
        # data rather than as a flag `_run_turn` would have to read.
        recorded = _SpokenCapture()
        outcome = await self._run_turn(
            heard,
            timeout=timedelta(seconds=max(remaining(), 0.0)),
            conversation_id=conversation_id,
            compose=partial(self._composed_spoken, supply=supply),
            compose_routed=self._composed_routed_spoken,
            supply=supply,
            # ADR-0228 §4: this operation declares **no** budget, so no turn of it
            # iterates whatever its audience — stated on the member rather than as a
            # `None` this call site chose.
            operation=ConversationalOperation.CONVERSE_SPOKEN,
            spoken=recorded,
        )
        # Measured **before** a rendering is spent on it, because ADR-0200 §4 rules
        # that an outcome over ADR-0085 §8c on its own raises exactly as it does on
        # ``converse``: "Dropping a rendering cannot rescue it, and no implementation
        # tries."
        self._checked(outcome, "converse_spoken")
        spoken, degraded = await self._spoken_rendering(
            _spoken_text(outcome), plays=plays, synthesizer=synthesizer, seconds=remaining()
        )
        return self._within_payload_limit(
            SpokenTurn(
                heard=heard,
                outcome=outcome,
                spoken=spoken,
                spoken_degraded=degraded,
                episode_id=recorded.episode_id,
            )
        )

    async def _transcribed(
        self, transcriber: SpeechTranscriber, utterance: SpokenAudio, *, seconds: float
    ) -> tuple[str, SpeechFailure | None]:
        """Transcribe, and classify a seam failure rather than raising one.

        The failure is **returned** so its raise can happen with no exception in
        flight (:meth:`_converse_spoken`). Everything that is not a ``SpeechError``
        propagates from here unchanged, which is ADR-0200 §4's "every other
        exception propagates" and the reason this catches one class rather than
        ``Exception``.

        Args:
            transcriber: The seam.
            utterance: The recording, already checked against ``formats`` and §6's
                bound.
            seconds: What is left of the call's budget.

        Returns:
            The transcript and ``None``, or ``""`` and this project's own
            classification of what the seam raised.
        """
        try:
            return await transcribe_within(transcriber, utterance, seconds=seconds), None
        except SpeechError as exc:
            failure = classify_speech_failure(exc)
        # The seam's own words are never written down — not here, not to either log
        # tier, not into the refusal (ADR-0200 §8). What is logged is this project's
        # classification of it.
        _log.warning("spoken_transcription_failed", failure=failure.value)
        return "", failure

    async def _spoken_rendering(
        self,
        text: str | None,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        synthesizer: SpeechSynthesizer,
        seconds: float,
    ) -> tuple[SpokenAudio | None, bool]:
        """Render what this pass has to say, or say that speaking it did not complete.

        Three of ``spoken_degraded``'s four cases live here (ADR-0200 §4) — an empty
        format intersection, a synthesis failure, and a rendering over ADR-0200 §6's
        bound — and the fourth is the payload measurement one level up, which needs
        the whole result to make its judgement. ADR-0207 §4 reads the same ladder over
        a wider subject and adds no case to it: the antecedent on a park is §2's fixed
        sentence rather than an answer, and every consequent is untouched.

        **Nothing to say is still not a degradation.** A composition failure and a
        resume recovered from durable state leave nothing for :func:`_spoken_text` to
        return, and nothing is invented to fill the silence: ``spoken`` is ``None``
        and ``spoken_degraded`` is ``False``.

        **This stage never learns which of the three it is rendering.** It is handed
        a string, so an answer and ADR-0207 §2's constant reach the seam by exactly
        one path and under exactly one ladder — and no part of a park can arrive here
        to be interpolated into either.

        **The format is the first member of ``plays`` this synthesizer names**
        (ADR-0200 §3) — the caller's preference honoured as far as the seam can, and
        never a substitution outside what the caller said it could play. An empty
        intersection is discovered *before* the call rather than reported by one,
        which is why nothing is spent on it.

        Args:
            text: What this pass says — the composed answer, or ADR-0207 §2's
                sentence on a live confirmation park, or ``None`` where it says
                nothing. Handed to the seam byte for byte, with nothing derived from
                it and no second copy anywhere.
            plays: The caller's preference order.
            synthesizer: The seam.
            seconds: What is left of the call's budget.

        Returns:
            The rendering and whether speaking degraded, in the pairing
            :class:`~ai_assistant.core.types.SpokenTurn`'s validator admits.

        Raises:
            Exception: Anything that is not a ``SpeechError``. ADR-0200 §4 keeps the
                degradation set closed, so a defect propagates rather than arriving
                as an ordinary "it could not be spoken".
        """
        if text is None:
            return None, False
        chosen = next((member for member in plays if member in synthesizer.formats), None)
        if chosen is None:
            _log.warning("spoken_rendering_degraded", reason="no_shared_format")
            return None, True
        try:
            rendering = await synthesize_within(
                synthesizer, text, media_type=chosen, seconds=seconds
            )
        except SpeechError as exc:
            # The classification is logged; the seam's message is not (ADR-0200 §8).
            _log.warning(
                "spoken_rendering_degraded",
                reason="synthesis_failed",
                failure=classify_speech_failure(exc).value,
            )
            return None, True
        size = len(rendering.decoded())
        if size > self._max_spoken_audio_bytes:
            # Not refused, unlike an oversized *utterance*: the answer already exists
            # and still travels as ``outcome.reply`` (ADR-0200 §6).
            _log.warning("spoken_rendering_degraded", reason="over_audio_bound", size=size)
            return None, True
        return rendering, False

    def _within_payload_limit(self, spoken: SpokenTurn) -> SpokenTurn:
        """Apply ADR-0200 §4's fourth degradation case, and its one re-measure.

        **Measured on the whole projected result, not on the rendering alone.**
        ADR-0200 §6 bounds the recording and the rendering each on its own; ADR-0085
        §8c bounds the *serialised whole*. A ``TurnOutcome`` lawful alone plus a
        one-byte rendering can be over §8c, so a rendering well inside §6 can still
        be the byte that breaks the frame — and without this case that result had no
        legal value at all, since returning it would breach §8c and dropping the
        rendering would contradict §4's own "exactly when".

        **It degrades rather than refusing**, because an answer the caller can read
        is worth more than a rendering that would make the whole result unsendable —
        ADR-0170 §8's argument reaching a fourth stage.

        **And it has exactly one step.** Where the result carrying ``spoken``
        ``None`` still breaches §8c, that is §8c's oversized result and raises.
        Nothing further is dropped: ``heard`` is owed to the caller by §4's
        disclosure clause and ``outcome`` is the answer, so there is no third thing
        to give up, and shortening either would be truncating a result rather than
        degrading a rendering.

        Args:
            spoken: The result as the stages produced it.

        Returns:
            It, or the same result with its rendering dropped.

        Raises:
            OversizedValueError: If it is over the limit with no rendering in it.
        """
        if spoken.spoken is None:
            return self._checked(spoken, "converse_spoken")
        try:
            check_payload(
                spoken,
                max_bytes=self._max_payload_bytes,
                subject="the result of converse_spoken()",
            )
        except OversizedValueError:
            _log.warning("spoken_rendering_degraded", reason="over_payload_limit")
            return self._checked(
                SpokenTurn(
                    heard=spoken.heard,
                    outcome=spoken.outcome,
                    spoken_degraded=True,
                    # Carried through the one degradation that rebuilds the result:
                    # `episode_id` is bounded and is never what is dropped to make a
                    # result fit (ADR-0205 §10b), so the ladder still has exactly one
                    # step.
                    episode_id=spoken.episode_id,
                ),
                "converse_spoken",
            )
        return spoken

    async def _composed_spoken(  # noqa: PLR0913 — the turn, the step, the conversation, the delivery facts, the hop's reach, ADR-0228 §10's stop fact and the supply applier; every one is a distinct fact about the pass
        self,
        turn: TurnResult | None,
        step: StepOutcome | None,
        conversation: str,
        deliveries: Mapping[str, SpokenDelivery],
        hop_reached: Sequence[str],
        stopped_while_asking: bool,
        *,
        supply: UnboundedAudienceSupply,
    ) -> ComposedReply | None:
        """Compose this pass's answer for a channel of unbounded audience (ADR-0200 §7).

        :meth:`_composed_whole` with two differences and no others, both of them
        ADR-0199's rather than this method's.

        **The withholding is at supply, and the supply is the whole turn's**
        (ADR-0203 §1). ``orchestration.disclosure`` reduced what this turn ran over to
        what ADR-0199 §3 places as speakable on a channel of unbounded audience —
        between retrieval and planning, deciding each class from recorded origin and
        never by inspecting a word of content — so ``turn`` **is** the narrowed supply
        and there is nothing left for this method to subtract. No stage composes a
        reply and then removes, masks, blanks or rewrites part of it, and nothing here
        filters, redacts or post-processes ``outcome.reply`` on any ground (ADR-0199
        §5, ADR-0200 §7).

        **The** :class:`~ai_assistant.core.types.TurnResult` **this stage is given is
        the one the turn produced**, and the outcome carries that same one back. Until
        ADR-0203 this method narrowed a copy for the stage and handed the wider turn
        back, which ADR-0199 §5's second clause required; §1 of ADR-0203 replaces that
        clause for an operation of this class, and the copy does not move — it ceases
        to exist. ADR-0200 §4's "no second difference" is replaced for the same case
        by ADR-0203 §3, which admits the turn, the plan, the step the plan drives and
        the values computed from those, and bounds the difference to exactly them.

        **The audience reaches the stage from the operation being executed** and
        from nothing else — not from an argument, a session, a transport or a device
        (ADR-0200 §3, §7). It is the only input ADR-0200 adds to that stage; the
        withholding *fact* is ADR-0199 §5's, which obliges the stage to be told
        **that** a withholding occurred so it can compose an answer that states it.
        That fact is read off ``supply`` — the one applier this call minted, which
        recorded it several stages earlier — and it is the **bare fact**: this stage is
        never told what was withheld and never sees a span of it. The stage gains no
        ``ContextProvider``, no ``MemoryStore``, no second context assembly and no
        second retrieval, and its context and memories still reach it from the turn
        (ADR-0170 §2, ADR-0203 §2).

        **The tail's delivery facts are the second supplied input, and they are
        paired with the episodes that reached this stage** (ADR-0205 §5). Where a
        turn of the tail carries one, the stage is told it — the state, and where a
        report was received the two durations — so a turn whose episode is in front
        of it carrying words the device did not play arrives with the fact that it
        did not. Where a supply site withheld a record, no delivery fact for that
        turn reaches here either: ``_paired_deliveries`` intersects them before this
        method is called, so the withholding removes both together (ADR-0199 §5's
        fourth clause). The stage gains no ``ContextProvider``, no ``MemoryStore``,
        no second context assembly and no second retrieval for them — they ride the
        tail ``ConversationLifecycle.history`` already read.

        Args:
            turn: What the turn produced, over the subtracted supply. ``None`` on a
                pass that owes no answer.
            step: What became of the driven step.
            conversation: Accepted and dropped, as :meth:`_composed_whole` drops it.
            deliveries: What a device reported playing of each surviving turn of the
                tail, keyed by the episode it qualifies (ADR-0205 §5).
            hop_reached: Which records this turn's citation hop reached (ADR-0227
                §3). **Always empty here**: ADR-0226 §5 declines to service a read
                request on an operation whose output channel's audience is unbounded,
                so this operation's supply stays the three groups ADR-0203 §1
                narrowed and no hop has reached anything. It is accepted rather than
                dropped so that :data:`_Composer`'s shape is one shape, and passed on
                rather than replaced with ``()`` so that no site here holds a second
                statement of §5's scoping.
            stopped_while_asking: Whether the turn stopped looking while still asking
                (ADR-0228 §10). **Always ``False`` here**, and for the carrier above's
                reason one clause further on: ADR-0228 §2(c) admits a revision only on
                a turn whose request was *serviced*, and ADR-0226 §5 declines to
                service one on this operation — so no turn of it reaches either guard.
                ADR-0228 §4 makes that doubly true by declaring **no** planning budget
                for ``converse_spoken`` (§2(a)). Accepted and passed on rather than
                replaced with ``False``, for the same reason.
            supply: The applier this call minted, read for the bare fact of whether
                anything was held back. Bound by :meth:`converse_spoken` rather than
                passed by :meth:`_run_turn`, which knows nothing of disclosure.

        Returns:
            What the stage composed, or ``None`` where no answer was owed.
        """
        del conversation
        if turn is None or (step is not None and step.confirmation is not None):
            return None
        undriven = (
            () if step is None else tuple(one for one in turn.plan.steps if one.id != step.step_id)
        )
        return await self._composing.compose(
            turn=turn,
            step=step,
            undriven=undriven,
            unbounded_audience=True,
            withheld=supply.withheld,
            deliveries=deliveries,
            hop_reached=hop_reached,
            stopped_while_asking=stopped_while_asking,
        )

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam (ADR-0029 §4)
        remember_recipients_until: UtcInstant | None = None,
    ) -> TurnOutcome:
        """Answer a parked confirmation and continue its step (ADR-0042 §3, §4).

        The adapter relays the opaque ``token`` and the human's yes/no; it does
        **not** author the outcome. ``ActionPolicy.resolve`` — inside
        `permissions`, reached through the engine — is what turns ``approved`` into
        an ``ALLOW`` or ``DENY``, and only ``approved=False → DENY`` is guaranteed:
        ``approved=True`` may still be refused by the policy (ADR-0042 §4). The
        adapter conveys consent; the policy rules; the engine records and executes.

        **A token whose binding this engine has already settled and still retains is
        answered rather than refused** (ADR-0198 §§1-3). Such a call **restates** the
        recorded answer: it returns an outcome describing the settled binding, it
        consults no policy and drives no runner, and its own ``approved`` is not
        consulted at all — a park is answered once (ADR-0044 §2b), so a second answer
        is never honourable whatever it says, and the engine states what was decided
        rather than refusing to say. That is what lets a surface whose first answer's
        fate is unknown ask "did it land?" and be told (#1621); before it, the second
        call met ``UnknownContinuationError``, whose ratified remedy — enumerate and
        re-mint — is the one remedy a replay cannot use, since ADR-0052 §1 step 2
        never lists a settled binding. Retention is bounded by
        ``max_outstanding_confirmations``, holds no slot at that ceiling, has no
        lifetime, is never enumerated and never persisted (§4).

        **This takes no conversation id, and that is a decision** (ADR-0074 §9 item
        5). It recovers the parked turn's conversation from the binding the parking
        turn durably recorded, because a resume that *accepted* an id could be
        handed the wrong one, and one that defaulted to starting a conversation
        would file every recovered resolution under a brand-new conversation,
        orphaned from the exchange that asked the question. The resume path cannot
        be told which conversation it is in: the adapter relays an opaque token and
        nothing else, and after a restart that token is reconstructed from durable
        state with no live turn behind it.

        A resumption is captured as **its own episode** in the conversation that
        parked — a park is an answer, and the unit is what the user saw. If nothing
        resolves, the resumption is simply not captured and the degradation is
        reported: recording it under a conversation invented for the purpose would
        assert a conversation the user never had.

        Args:
            token: The opaque continuation the parking :meth:`converse` returned.
                Its contents are the engine's; the adapter never inspects them.
            approved: The human's answer. ``True`` conveys consent, which the
                policy may still refuse; ``False`` is a decision that yields
                ``DENY``.
            timeout: The per-attempt budget, as :meth:`converse`.
            remember_recipients_until: The instant the user asked this call's
                recipients be remembered until, supplied **in the same act** as the
                answer (ADR-0193 §2, ADR-0235 §1). ``None`` — the default and the
                ordinary outcome — is a user who approved a call and asked for
                nothing standing. Honoured only beside ``approved=True`` and only on
                a resolving ``ALLOW``; what became of it is on the outcome's
                ``recipient_grant`` and is never read off a later listing.

        Returns:
            The resumed turn: the parked turn's own result, the step's resolved
            disposition (``EXECUTED`` or ``DENIED``), and the answer composed for
            it. A resume driven from a **recovered** park composes nothing —
            ``turn`` is ``None`` there, so context and memories were never persisted
            and there is nothing to compose from, which ADR-0170 §4 makes a ``None``
            ``reply`` with ``reply_degraded`` ``False``. A **restatement** is that
            same shape and carries it for its own reason (ADR-0198 §2): ``turn``
            ``None``, ``routed`` ``None``, ``reply`` ``None`` and ``reply_degraded``
            ``False``, beside a ``step`` carrying the settled binding's disposition,
            step id and tool id, and its execution state **re-read now** rather than
            snapshotted at settlement.

        Raises:
            RuntimeError: If the engine is shutting down.
            PlanningError: If ``token`` names neither a parked step this engine holds
                nor an answer it still retains — a token from a previous process, one
                reconciled away under ADR-0052 §2, or one whose settled record has
                aged out of ADR-0198 §4's bound. Its lifetime is process-scoped
                (ADR-0042 §4; the Revisit-if clause ties durable resume to #242).
                Also where the plan store no longer holds the execution a settled
                record names, which is an outcome this engine cannot read and so may
                not state (ADR-0198 §2).
            PermissionDeniedError: If the recorded decision is not a ``CONFIRM``
                about this parked step (``StepRunner`` refuses it).
            UngrantableActError: If ``remember_recipients_until`` was supplied beside
                ``approved=True`` and the act may not ride this confirmation, or the
                instant is not strictly after the one the answer would carry. Raised
                before any ruling is sought, so nothing is recorded, nothing is
                executed, and the step stays parked and answerable (ADR-0235 §1, §2,
                §6).
            AuditError, ToolBindingError: As the stages raise.
        """
        self._reject_if_closing()
        check_arguments(
            "resume",
            max_bytes=self._max_payload_bytes,
            token=token,
            approved=approved,
            timeout=timeout,
            remember_recipients_until=remember_recipients_until,
        )
        return await self._tracked(
            self._resume(
                token,
                approved=approved,
                timeout=timeout,
                remember_recipients_until=remember_recipients_until,
            ),
            "resume",
            checked=True,
        )

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Fold one piece of feedback back into memory (ADR-0042 §3; the correction leg).

        The adapter hands the engine the correction or stated preference the user
        gave, and receives an ``orchestration``-level summary of what memory did
        with it. Delegates to the
        :class:`~ai_assistant.orchestration.loop.LearningLoop`, whose ``learn``
        processes the event into proposals and ingests each through the injected
        ``MemoryWriter`` (ADR-0028 §4) — conflict resolution, the policy's ruling
        and the write all happen behind that seam.

        Tracked like :meth:`converse`/:meth:`resume`: the write path touches the
        connection-owning memory store, so shutdown must drain it before closing
        that connection (ADR-0042 §2).

        Args:
            event: The correction or stated preference the user gave.

        Returns:
            A :class:`LearnOutcome` summarising, per proposal, how memory folded it
            — translated from the loop's raw ingest results so no ``core`` type
            reaches the adapter (ADR-0042 §1).

        Raises:
            RuntimeError: If the engine is shutting down (:meth:`aclose` has been
                entered), so no new work is accepted.
            MemoryStoreError: If the writer failed to read conflicts or write a
                record, as the loop raises.
        """
        self._reject_if_closing()
        check_arguments("learn", max_bytes=self._max_payload_bytes, event=event)
        return await self._tracked(self._learn(event), "learn", checked=True)

    async def observe(self, *, conversation_id: Identifier | None = None) -> ObservationReport:
        """Distil beliefs from a conversation's recent turns (ADR-0077 §8).

        The accumulation leg, and an **explicit operation**: it is not wired into
        the turn, and nothing runs it on a timer unless a deployment asks. Four
        reasons, in the order they bind (ADR-0077 §8): nothing is waiting on an
        observation while a turn is, and a one-shot process has no "after the
        answer" to hide the round trip in; §8 sequences the epistemic-soundness work
        ahead of the observer running at volume, and a per-turn trigger *is* volume
        on the day it merges; the first producer that sends accumulated history to a
        model should not run without the user knowing; and the hub's scheduler
        becomes a second caller of this same operation, so cadence becomes
        configuration rather than a contract change.

        That last one has landed, and it changed nothing here: the scheduler's
        observation job ships **disabled** (``Settings.observation_interval`` is
        ``None`` by default), because without a durable cursor a periodic run
        re-reads the same recent window and spends a model call each time while
        never reaching the turns the window has already passed (ADR-0083 §7, §13).

        Delegates to the
        :class:`~ai_assistant.orchestration.observation.ObservationStage`, which
        selects the batch, hands it to the injected ``Observer``, and puts each
        returned proposal through the ``MemoryWriter`` — conflict resolution, the
        policy's ruling and the write all happen behind that seam, exactly as
        :meth:`learn` does it. The engine rules on nothing and writes nothing
        itself.

        Tracked like :meth:`converse`/:meth:`learn`: it reads both durable stores
        and writes to one, so shutdown must drain it before closing those
        connections (ADR-0042 §2). **And read onto its own trace by
        :func:`_observed`** (ADR-0222 §9), which is the counting hook that decision
        owes: a hand-run pass used to record empty metrics while a scheduled run
        recorded twelve, so the denominator of any per-pass figure was readable for
        the scheduler and not for the user.

        Args:
            conversation_id: The conversation to observe, or ``None`` for the most
                recently active one (ADR-0077 §8). Relayed untouched: whether it
                names a conversation is the store's question, and an unknown id
                comes back as an ``AssistantError`` rather than as a silently empty
                observation.

        Returns:
            An :class:`~ai_assistant.orchestration.observation.ObservationReport`:
            what was proposed and what became of each proposal, what the producer
            and the write path threw away, and **which route read the episodes** —
            the report ADR-0013 §6 records as owed, made on the one call where it
            matters most. The route is absent when no observer was called, which is
            what a window whose episodes have all gone yields.

        Raises:
            RuntimeError: If the engine is shutting down.
            UnknownConversationError: If ``conversation_id`` names nothing, or names
                a conversation the user deleted.
            ConversationStoreError: If the conversation index cannot be read.
            MemoryStoreError: If an episode cannot be read, or the write path
                failed. A partially applied batch is left as it stands and nothing
                claims success for it (ADR-0022 §4); ``beliefs`` shows exactly what
                landed.
            ModelError: If the observing call failed, unwrapped and with its
                classification intact. It is never re-sent to a second provider
                (ADR-0077 §3).
        """
        self._reject_if_closing()
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments("observe", max_bytes=self._max_payload_bytes, conversation_id=selected)
        return await self._tracked(
            self._observation.observe(selected), "observe", _observed, checked=True
        )

    async def observe_due(self) -> ObservationRunReport:
        """Observe every conversation that is due, one bounded run (ADR-0218 §3).

        The **maintenance surface**'s fourth scheduled operation, and the scheduled
        trigger ADR-0083 §7's observation row now calls. ADR-0083 §8 settled that
        this kind of method is "new *concrete* surface on a class in
        ``orchestration``, not ``core`` contract surface", and :meth:`consolidate`
        is the standing precedent in each respect: it is **not** on the
        ``AssistantEngine`` Protocol, **not** a wire operation, and **not** a reason
        to move ``PROTOCOL_VERSION``.

        **A new operation rather than an argument on :meth:`observe`, and the reason
        is not taste** (§3). ``observe`` is a wire operation that
        ``core/protocols.py`` declares, so an argument on it moves
        ``PROTOCOL_VERSION`` under ADR-0124 §9 — a protocol bump bought to express a
        cadence. The second reason is stronger: ADR-0120 §3 attributes a write by
        the seam of the operation that caused it, so one seam serving both callers
        would make an armed job's writes indistinguishable from a user's deliberate
        ones. The third is the return shape — ``ObservationReport`` describes one
        pass and a run performs many. :meth:`observe` is untouched by this method
        existing: same signature, same seam, same behaviour.

        **Takes no argument, deliberately**, which is what makes it a legal
        ``JobBody`` and keeps the due test, the candidate listing and the passes
        behind this façade. The scheduler holds an ``Engine`` and nothing else, and
        learns nothing about watermarks, quiet windows or spans.

        **Its seam is ``observe_due`` and it is in ADR-0120 §3's machine set**, which
        is what stops every measure over the user set stepping on the day this job is
        armed — the precise confound §3 exists to prevent, produced by the precise
        act it was written about. Every pass a run performs happens inside *this*
        call's :meth:`_tracked` scope and is never a nested :meth:`observe`, so every
        trace a run emits carries the run's correlation and attributes to this seam.

        Returns:
            What the run did, in Tier 2 counts and one disposition. Every count zero
            is a **successful** run over a listing that held nothing due, and no
            caller may read it as a failure.

        Raises:
            RuntimeError: If the engine is shutting down. The scheduler treats this
                as *stop* rather than as a job failure (ADR-0083 §8).
            ConversationStoreError: If the candidate listing, a page or an advance
                could not be read or written.
            MemoryStoreError: If an episode could not be read, or the write path
                failed.
            ModelError: Propagated unwrapped from a pass's provider, its
                classification intact (ADR-0013 §5). The run halts; ADR-0111 §6
                retries the job at its next due instant with no backoff.
            DeferralStoreError: If a deferred question could not be parked.
        """
        self._reject_if_closing()
        return await self._tracked(self._observation.run(), "observe_due", _observed_due)

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """Enumerate the beliefs the assistant holds right now (ADR-0073 §1, §7).

        The read half of "the user can read the assistant's beliefs about them".
        It relays the filters to :meth:`~ai_assistant.core.protocols.MemoryStore.list_beliefs`
        and translates each record into a :class:`Belief`, which is where
        :func:`~ai_assistant.core.types.band_of` is applied (ADR-0073 §7).

        Everything about *what* comes back is the store's ratified contract, not
        this façade's: live beliefs only (a retired record is history, reachable
        through ``export`` alone), newest revision first with ``id`` breaking ties,
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
            kinds: If given, restrict it to these memory kinds, same convention. The
                two compose by conjunction: a belief is listed when its band is
                selected *and* its kind is.
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
        """Read the one belief ``record_id`` names, or ``None`` (ADR-0073 §5, §7).

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

        Returns:
            The belief, or ``None`` when no live belief has that id.

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
        :meth:`~ai_assistant.core.protocols.MemoryStore.delete` and nothing more.
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

        **It reaches the transcript archive first, and it attempts that discard
        whether or not a live record stands at the id** (ADR-0225 §5). Both halves are
        the decision. *First*, because the residue of a partial failure must be the
        one the user can still reach and destroy: a failure between the two leaves a
        record they can forget again rather than text they were told was gone. *Whether
        or not*, because §3 keeps an entry's address valid after its episode has
        expired, been reclaimed or been destroyed — so short-circuiting on an absent
        memory record would make the transcript of an expired turn permanently
        unreachable by this operation, which is ADR-0004 §6's right made conditional on
        a horizon. A second attempt at the same id therefore reaches the entry however
        the first one failed.

        Args:
            record_id: The id the user named, taken as opaque.

        Returns:
            ``True`` if a record was destroyed, ``False`` if no record had that id —
            which the adapter renders and maps to an exit code (ADR-0073 §7). The
            archive discard does not enter the answer: the question this operation
            answers is "was there a belief at that id", and reporting a destroyed
            transcript as a destroyed record would tell the user something else.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If memory cannot be written.
            TranscriptArchiveError: If the transcript entry could not be destroyed.
                The memory record is left standing, deliberately (ADR-0225 §5).
        """
        self._reject_if_closing()
        named = identifier(record_id, name="record_id")
        check_arguments("forget", max_bytes=self._max_payload_bytes, record_id=named)
        return await self._tracked(self._forgotten(named), "forget", checked=True)

    async def _forgotten(self, record_id: str) -> bool:
        """Discard the transcript entry, then destroy the record (ADR-0225 §5).

        One coroutine rather than two tracked calls, so the pair is a single unit of
        in-flight work: a shutdown drain that let the discard land and cancelled the
        deletion would produce exactly the residue §5 orders the sequence to avoid.
        """
        await self._archive.discard(record_id)
        return await self._memory.delete(record_id)

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

    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the deferred questions awaiting an answer (ADR-0078 §8 reach 2).

        The reach for a question no ``learn`` call was in flight to render, which is
        every question a background producer raises. Relayed to the question stage
        and returned as :class:`~ai_assistant.orchestration.questions.Question`
        DTOs, which is where ``band_of`` is applied — once, here — so no adapter
        classifies anything (ADR-0073 §7).

        **Answerable questions only.** One whose answer was begun and never recorded
        is a different question and comes back from
        :meth:`interrupted_questions`; the two never merge into one list, because
        offering an interrupted question beside the answerable ones would present a
        claim that cannot be taken.

        **No total count is offered**, for ADR-0073 §7's reason: "is there more" is
        answered by asking for the next page.

        Args:
            limit: Page size, bounded by default (ADR-0073 §2, §8).
            offset: How many ordered rows to skip.

        Returns:
            The page, oldest first — the head of the queue being the question whose
            admission is blocking a newer one.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``limit`` or ``offset`` falls outside ``[0, 2**63)``, as
                the store refuses rather than clamps. Not an ``AssistantError``, so
                an adapter that lets a user supply either must refuse an
                out-of-range value at its own parse boundary.
            DeferralStoreError: If the queue cannot be read.
            MemoryStoreError: If a conflict's content cannot be read.
        """
        self._reject_if_closing()
        self._check_page("questions", limit=limit, offset=offset)
        return await self._tracked(
            self._questions.questions(limit=limit, offset=offset), "questions", checked=True
        )

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions whose answer was begun and never recorded (§8, §9).

        A **second enumeration**, separate all the way to the surface. It exists
        because a process that died inside a claim leaves the question ``APPLYING``
        forever — unclaimable, never swept, and, after a restart, holding no id
        anything could look it up by. Without this read the stranded question is
        unreachable, which is the vanishing ADR-0078 is about, one state along.

        What the surface must say about one of these is that **an answer was begun
        and its outcome is not recorded** — not that it failed and not that it can be
        retried, because the system does not know whether the memory write landed.
        The recovery is two steps in order: :meth:`forget_question`, then read the
        belief (:meth:`beliefs`) and ``learn`` it again if it is missing.

        Args:
            limit: Page size, bounded by default as :meth:`questions` is.
            offset: How many ordered rows to skip.

        Returns:
            The page, in :meth:`questions`' order and disjoint from it.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: As :meth:`questions` refuses a malformed page argument.
            DeferralStoreError: If the queue cannot be read.
            MemoryStoreError: If a conflict's content cannot be read.
        """
        self._reject_if_closing()
        self._check_page("interrupted_questions", limit=limit, offset=offset)
        return await self._tracked(
            self._questions.interrupted_questions(limit=limit, offset=offset),
            "interrupted_questions",
            checked=True,
        )

    async def answer(self, question_id: Identifier, *, accept: bool) -> AnswerOutcome:
        """Answer one deferred question (ADR-0078 §5, §9).

        The write half of the deferred-question surface. An accept **claims** the
        question, re-submits its proposal through the same write path ``learn`` uses
        — carrying the authority the claim mints, which is what lets it retire an
        assertion the ordinary path may not — and records the outcome. A rejection
        needs no claim, because it writes nothing.

        **Answering is binary, and there is no third "neither — here's the real
        answer".** An amendment is a new proposal and ``learn`` already is one
        (ADR-0073 §6), so a free-text answer would be a second correction path
        wearing a confirmation's clothes. There is likewise **no retry verb**
        anywhere on this surface (ADR-0078 §2, §8).

        Args:
            question_id: The question the user named, taken as opaque.
            accept: The user's answer. ``True`` re-submits the proposal under the
                claim's authority; ``False`` declines it and retains the record so
                the same question is not asked again.

        Returns:
            An :class:`~ai_assistant.orchestration.questions.AnswerOutcome` saying
            which of the five outcomes happened — including a re-deferral, which
            carries the successor question so the user is handed the next question
            rather than being told their answer went nowhere.

        Raises:
            RuntimeError: If the engine is shutting down.
            MemoryStoreError: If the write path failed. The claim is left
                ``APPLYING`` and reachable through :meth:`interrupted_questions`;
                nothing is "repaired", because the engine cannot tell whether the
                write landed and stamping a terminal state would be a lie.
            UnresolvedEvidenceError: If the proposal's cited evidence was deleted
                between the question and the answer. Likewise stranding.
            DeferralStoreError: If the queue cannot be read or written.
        """
        self._reject_if_closing()
        named = identifier(question_id, name="question_id")
        check_arguments(
            "answer", max_bytes=self._max_payload_bytes, question_id=named, accept=accept
        )
        return await self._tracked(
            self._questions.answer(named, accept=accept), "answer", checked=True
        )

    async def forget_question(self, question_id: Identifier) -> bool:
        """Destroy one deferred question (ADR-0078 §8, §9; ADR-0007).

        Relays ``DeferralStore.delete``. **Unconditional**, like every other
        deletion on this façade — including on a question whose answer is in flight,
        because a data right conditional on an internal state the system assigned is
        the mistake ADR-0073 §9 declines with a different label, and a refusal would
        be *permanent* for a stranded claim.

        It is also step 1 of the recovery a stranded answer has, and the ordering is
        the whole point: while the row lives it holds its question key, so a
        re-``learn`` of the same correction would collide with it and be handed back
        an id nothing can claim. Deleting destroys the key with the content.

        Args:
            question_id: The question the user named, taken as opaque.

        Returns:
            ``True`` if a question was destroyed, ``False`` if the id named nothing
            — which the adapter renders and maps to an exit code, exactly as
            :meth:`forget` does for a belief.

        Raises:
            RuntimeError: If the engine is shutting down.
            DeferralStoreError: If the queue cannot be written.
        """
        self._reject_if_closing()
        named = identifier(question_id, name="question_id")
        check_arguments("forget_question", max_bytes=self._max_payload_bytes, question_id=named)
        return await self._tracked(
            self._questions.forget_question(named), "forget_question", checked=True
        )

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

        ADR-0007's data right in :meth:`forget_question`'s shape, and
        unconditional like every other deletion on this façade. Beside
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
            NotificationStoreError: If the store cannot be read or written.
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

        Args:
            page: How many due records one store read takes.

        Returns:
            How many were re-ruled.
        """
        store = self._notification_surface()
        assert self._notification_policy is not None  # noqa: S101 — wired together (see __init__)
        policy = self._notification_policy
        seen: set[str] = set()
        ruled = 0
        while due := await store.due(limit=page):
            fresh = [record for record in due if record.id not in seen]
            if not fresh:
                break
            before = ruled
            for record in fresh:
                seen.add(record.id)
                ruling = await store.reconsider(record.id, policy=policy)
                if ruling is not None:
                    ruled += 1
                    await self._hand_off(ruling, record.candidate)
            if ruled == before:
                break
        return ruled

    def _notification_surface(self) -> NotificationStore:
        """The wired notification store, or a legible refusal.

        Returns:
            The store.

        Raises:
            ConfigurationError: If none is wired, in :meth:`ingest_calendar`'s shape — a
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
        return await self._tracked(
            self._recent_conversations(limit=limit, offset=offset),
            "recent_conversations",
            checked=True,
        )

    async def _recent_conversations(
        self, *, limit: int, offset: int
    ) -> tuple[ConversationSummary, ...]:
        """Relay the listing to the stage and project each record."""
        listed = await self._conversations.recent(limit=limit, offset=offset)
        return tuple(conversation_summary(one) for one in listed)

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
        return await self._tracked(self._conversations.digest(named), "conversation", checked=True)

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy a conversation and every episode it recorded (ADR-0074 §8).

        ADR-0004 §6's right at the unit the user thinks in. Unconditional, like
        every other deletion on this façade: the store deletes what it is told to
        delete, and no kind- or band-conditional refusal is added, because a store
        that can refuse a data-rights operation is one where that right is
        conditional on its own classification.

        Three ordered steps, and the ordering is a **protocol rather than a
        preference** (§8): stamp the conversation, which is durable and refuses
        every later append; destroy every episode the index names, including one
        whose write is still in flight; then drop the index and the record, once
        nothing is left that resolves and the grace has passed. If this process
        dies part-way the tombstone survives, still naming every episode involved,
        and :meth:`start` finishes it on the next run.

        Args:
            conversation_id: The conversation the user named, taken as opaque.

        Returns:
            ``True`` if this call stamped it; ``False`` if it was already stamped
            or the id names nothing — which the adapter renders and maps to an exit
            code, exactly as :meth:`forget` does for a belief. The sweep behind the
            stamp is run either way, because §8's protocol is re-runnable.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the index cannot be read or written.
            MemoryStoreError: If an episode could not be destroyed. The tombstone
                stands and the next sweep finishes the job; reporting success over
                content the user asked to be gone would be the worse failure.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        return await self._tracked(
            self._conversations.delete(named), "forget_conversation", checked=True
        )

    # --- the transcript archive (ADR-0225 §5, §6, §7, §8) ------------------

    # **The seam is the wide one and it carries no ``append``** (ADR-0225 §10):
    # ``self._archive.append(...)`` fails ``mypy`` here, the declared type having no
    # such member, and `orchestration` may not import ``ai_assistant.archive`` (§4)
    # so there is no concrete class to widen a value back to. Writing is capture's,
    # on the ``TranscriptArchiveWriter`` ``ConversationLifecycle`` holds — which is
    # how §1's "no other producer writes to the archive" becomes a property of the
    # seam rather than a rule somebody is asked to keep.
    #
    # **Reached from this façade's user-facing operations and from no operation on
    # the turn path** (§4). Nothing below is called by :meth:`converse`,
    # :meth:`resume`, :meth:`observe`, or by any stage they drive; no stage holds an
    # archive seam at all. The seven exist for the surfaces §8 gives them, and
    # ADR-0225 §13's first test is what pins that a turn's prompts carry no archive
    # text.
    #
    # **Each is a single relay, deliberately.** The read-time retention predicate,
    # the matching predicate, the total order, the excerpt bound and both figures of
    # the size report are the *archive's* ratified guarantees (§6, §7), so an engine
    # that re-filtered, re-ordered, re-bounded or re-counted anything here would be a
    # second implementation of a rule the shared conformance suite could then only
    # compare against itself. What this layer owes is what ADR-0085 makes its own:
    # the argument refusal §9 requires be local and before any I/O, and the result
    # measurement §8 makes part of this contract rather than of a transport.

    async def transcript_search(
        self,
        query: NonBlankEncodableText,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[TranscriptHit, ...]:
        """Search the archive lexically, newest first (ADR-0225 §7).

        **The query is relayed exactly as the user wrote it.** It is validated
        non-blank and measured, and it is not stripped, trimmed, collapsed or
        otherwise normalised: ``NonBlankEncodableText`` rather than ``Identifier``
        is the whole point, since an ``Identifier`` would rewrite ``" hello"`` into
        ``"hello"`` before §7's predicate ever saw it. The NFC normalisation and the
        full case folding the predicate performs are the archive's, applied to both
        sides at the match and to neither value in storage.

        Args:
            query: What to look for, as the user wrote it.
            limit: Page size, defaulting to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE` and refused at
                zero (see the note above this method).
            offset: How many ordered hits to skip before the page begins.

        Returns:
            The page, newest first with the address breaking ties.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` or ``offset`` is not an integer, or is a ``bool``.
            ValueError: If ``query`` is blank, ``limit`` is not in ``[1, 2**63)``, or
                ``offset`` is not in ``[0, 2**63)``.
            OversizedValueError: If the page exceeds the contract limit.
            TranscriptArchiveError: If the archive cannot be read.
        """
        self._reject_if_closing()
        asked = non_blank_text(query, name="query")
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_search",
            max_bytes=self._max_payload_bytes,
            query=asked,
            limit=limit,
            offset=offset,
        )
        return await self._tracked(
            self._transcript_search(asked, limit=limit, offset=offset),
            "transcript_search",
            checked=True,
        )

    async def _transcript_search(
        self, query: str, *, limit: int, offset: int
    ) -> tuple[TranscriptHit, ...]:
        """Relay the search and freeze the page into this surface's own shape."""
        return tuple(await self._archive.search(query, limit=limit, offset=offset))

    async def transcript_conversation(
        self,
        conversation_id: Identifier,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[TranscriptEntry, ...]:
        """Read one conversation's transcript, in the order it was said (§7).

        **Ordinal order rather than newest-first**, which is the one read on this
        surface that is not recency-ordered: a transcript's order is the order it was
        said in.

        **It consults no index and no conversation record** (§5). ADR-0074 §7
        reclaims an emptied conversation's index and record on the horizon and the
        archive keeps the transcript, so an id :meth:`conversation` answers ``None``
        for still yields its transcript here. That is what "expiry evicts" means, and
        it is the steady state rather than an anomaly.

        Args:
            conversation_id: Which conversation, taken as opaque.
            limit: Page size, defaulting to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many ordered entries to skip before the page begins.

        Returns:
            The page, in ordinal order, entries whole. Empty where the conversation
            has no surviving entries — not distinguished from never having had any,
            because a surface that told them apart would report on transcripts it is
            meant to have evicted.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` or ``offset`` is not an integer, or is a ``bool``.
            ValueError: If ``conversation_id`` is blank, ``limit`` is not in
                ``[1, 2**63)``, or ``offset`` is not in ``[0, 2**63)``.
            OversizedValueError: If the page exceeds the contract limit.
            TranscriptArchiveError: If the archive cannot be read.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_conversation",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            limit=limit,
            offset=offset,
        )
        return await self._tracked(
            self._transcript_conversation(named, limit=limit, offset=offset),
            "transcript_conversation",
            checked=True,
        )

    async def _transcript_conversation(
        self, conversation_id: str, *, limit: int, offset: int
    ) -> tuple[TranscriptEntry, ...]:
        """Relay the conversation read and freeze the page."""
        return tuple(await self._archive.conversation(conversation_id, limit=limit, offset=offset))

    async def transcript_entry(self, address: Identifier) -> TranscriptEntry | None:
        """Read one entry whole, by its address (§3, §7).

        The second act of §7's show-a-hit-then-read-the-entry split, and the one
        that makes §3's address stability exercised rather than asserted: an address
        stays a valid name for its entry after the episode it names has expired,
        been reclaimed or been destroyed.

        **The address is a name and never a capability**, and reaching an entry here
        is not citation resolution reaching one. That an expired episode's id is also
        a live archive address is a property of §3's reuse and is not a fallback: no
        citation resolution reads the archive (§4), and what a belief whose cited
        episode has expired renders is unchanged by this operation existing.

        Args:
            address: The entry's address, taken as opaque.

        Returns:
            The entry, whole, or ``None`` where nothing is held at that address —
            never held, past a finite ``transcript_archive_retention``, or destroyed,
            and the three are deliberately not distinguished.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``address`` is blank or whitespace-only.
            OversizedValueError: If the entry exceeds the contract limit.
            TranscriptArchiveError: If the archive cannot be read.
        """
        self._reject_if_closing()
        named = identifier(address, name="address")
        check_arguments("transcript_entry", max_bytes=self._max_payload_bytes, address=named)
        return await self._tracked(self._archive.entry(named), "transcript_entry", checked=True)

    async def transcript_entries(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[TranscriptEntry, ...]:
        """Enumerate every entry the archive holds — the archive's export (§7).

        A paged, ordered, unfiltered read of every entry *is* a portable snapshot of
        everything a store of pure text holds, so ADR-0004 §6's export right for the
        archive is satisfied by a read rather than by a second serialisation nobody
        would gain anything from. It is also why the archive is the first Tier-1
        store whose export exists on day one rather than deferred.

        Args:
            limit: Page size, defaulting to
                :data:`~ai_assistant.core.types.DEFAULT_PAGE_SIZE`.
            offset: How many ordered entries to skip before the page begins.

        Returns:
            The page, whole entries, newest first with the address breaking ties.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` or ``offset`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)`` or ``offset`` is not in
                ``[0, 2**63)``.
            OversizedValueError: If the page exceeds the contract limit.
            TranscriptArchiveError: If the archive cannot be read.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_entries", max_bytes=self._max_payload_bytes, limit=limit, offset=offset
        )
        return await self._tracked(
            self._transcript_entries(limit=limit, offset=offset),
            "transcript_entries",
            checked=True,
        )

    async def _transcript_entries(self, *, limit: int, offset: int) -> tuple[TranscriptEntry, ...]:
        """Relay the unfiltered enumeration and freeze the page."""
        return tuple(await self._archive.entries(limit=limit, offset=offset))

    async def forget_transcript_entry(self, address: Identifier) -> bool:
        """Destroy the transcript entry at ``address`` (§5).

        The archive's **own** address-scoped destroy, and not the cascade
        :meth:`forget` performs on its way to destroying a belief. This one destroys
        the transcript and touches no memory record, which is what gives a user whose
        conversation was reclaimed on the horizon a way to destroy text they can
        still read — ADR-0004 §6's right kept unconditional on a sweep.

        **It reaches what the reads hide.** An entry past a finite
        ``transcript_archive_retention`` and not yet physically reclaimed still yields
        here: a destruction is never refused on the ground that a read would not have
        shown it.

        Args:
            address: The entry's address, taken as opaque.

        Returns:
            ``True`` if an entry was destroyed, ``False`` if nothing was at that
            address — idempotent, so a second call at the same address is a no-op.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``address`` is blank or whitespace-only. No spelling of
                this argument means "everything" (ADR-0101 §9).
            TranscriptArchiveError: If the archive cannot be written.
        """
        self._reject_if_closing()
        named = identifier(address, name="address")
        check_arguments("forget_transcript_entry", max_bytes=self._max_payload_bytes, address=named)
        return await self._tracked(
            self._archive.discard(named), "forget_transcript_entry", checked=True
        )

    async def forget_transcript_conversation(self, conversation_id: Identifier) -> int:
        """Destroy every transcript entry of one conversation (§5).

        Resolved inside the archive against its own entries, so it needs neither the
        conversation index, the conversation record nor the memory store — which is
        what closes the hole ADR-0074 §7's reclaim would otherwise open, and why the
        scope the user names is the scope the archive resolves, forever.

        **Not** :meth:`forget_conversation`, which stamps the conversation and
        destroys its episodes, discarding these entries as the first action of
        ADR-0074 §8's step 2. This one destroys the transcript alone, and reaches a
        conversation that operation can no longer see.

        Args:
            conversation_id: Which conversation, taken as opaque.

        Returns:
            How many entries were destroyed. Total and idempotent: a conversation
            with no entries is a no-op returning ``0``, which is the conforming
            answer rather than a failure.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``conversation_id`` is blank or whitespace-only. The
                argument is required and positional, and no spelling of it widens
                what is destroyed (ADR-0101 §9).
            TranscriptArchiveError: If the archive cannot be written.
        """
        self._reject_if_closing()
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_transcript_conversation",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
        )
        return await self._tracked(
            self._archive.discard_conversation(named),
            "forget_transcript_conversation",
            checked=True,
        )

    async def transcript_archive_size(self) -> TranscriptArchiveSize:
        """What the archive holds and what it costs on disk (§6).

        The figure every surface rendering an archive read renders beside it,
        unasked, so the size cap ADR-0225 §6 defers has a trigger somebody actually
        has — ADR-0162 §5's lesson that a trigger with no instrument never fires.

        **Both figures are the archive's own and neither is derived here.**
        ``entries`` is what the reads would return and ``stored_bytes`` is what is on
        the disk, and they are allowed to disagree: an entry hidden by a finite
        retention has left the first and its bytes stay in the second until something
        physically reclaims them. An engine that netted them would hide exactly the
        growth the deferred cap exists to catch.

        Returns:
            The two figures, as they stand at the moment of the call.

        Raises:
            RuntimeError: If the engine is shutting down.
            TranscriptArchiveError: If the archive cannot be measured.
        """
        self._reject_if_closing()
        return await self._tracked(self._archive.size(), "transcript_archive_size", checked=True)

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Recover, from durable state, every confirmation a user may still answer (ADR-0052 §1).

        The durable counterpart to the in-process ``_parked`` table. A restarted
        process has an empty table, and a park whose process-scoped token was
        dropped — or that :meth:`converse` never handed back because it raised after
        the runner durably parked the step — is likewise unreachable in memory
        (#287). This reconstructs each such confirmation from state that *is*
        durable: the parked executions in the :class:`PlanStore` and the recorded
        ``CONFIRM`` in the :class:`AuditTrail`.

        It enumerates ``plans.active_executions()``, finds each ``AWAITING_APPROVAL``
        step, recovers its still-pending ``CONFIRM`` by the ``(execution_id,
        step_id)`` binding (``trail.pending_confirmation``; a binding already
        resolved returns ``None`` and is skipped — the #257 hazard ADR-0044 §2b
        closes is not re-presented), and reads the raw parameters from the plan step
        (the trail holds only a digest). Each recovered confirmation is assigned a
        continuation token and registered in ``_parked`` so a subsequent
        :meth:`resume` resolves it through the ordinary path — routed, because the
        entry carries ``confirmation_id=None``, through the runner's restart
        recovery (ADR-0044 §3) rather than a cached id.

        **Idempotent and bounded.** A binding already named by a ``_parked`` entry
        reuses that entry's token rather than minting a second, and every entry whose
        binding is *no longer* pending — recovered or in-process, resolved since a
        previous call, here or by another engine over the same durable stores — is
        evicted (:meth:`_reconcile`). So repeated calls return stable tokens, the
        table stays bounded by the number of distinct durably-parked bindings, and a
        resolution out of this engine's sight strands nothing (it neither leaks an
        entry nor pins the confirmation ceiling with a dead in-process park).
        Recovered entries are additionally **excluded from the confirmation ceiling**
        (:meth:`_admit_and_reserve`): they are bounded by durable state, not by client
        behaviour. Recovery presents parks that already happened and are already
        durable — refusing to surface one would strand it (ADR-0052 §2).

        **A settled binding is neither listed nor minted for, and the retained
        records are not reached at all** (ADR-0198 §4). The skip above is what does
        it and it is unchanged: a binding whose ``CONFIRM`` the trail no longer holds
        pending is exactly a settled one, and re-presenting it would be the #257
        hazard ADR-0044 §2b closes. The reconciliation below likewise ranges over
        ``_parked`` alone — a settled record is not a park, so it is neither evicted
        by it nor treated as one — which is why the answer to "did my answer land?"
        is :meth:`resume` and not this listing: an enumeration carrying settled
        bindings would put a resolved action back in front of a user in the type
        whose whole purpose is "what you may still answer".

        Returns:
            One :class:`Confirmation` per durably-parked, still-unresolved step,
            each carrying an opaque token to relay on :meth:`resume`. Empty when no
            execution is parked awaiting an answer.

        Raises:
            RuntimeError: If the engine is shutting down.
            PlanningError: If the store cannot be read.
            AuditError: If the trail cannot be read.
        """
        self._reject_if_closing()
        # Tracked like converse/resume: recovery reads the plan store and the audit
        # trail, so shutdown must drain it before closing those connections (§2).
        return await self._tracked(
            self._pending_confirmations(), "pending_confirmations", checked=True
        )

    async def _pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Enumerate the durably-parked confirmations and reconcile the table.

        **Serialized against recovery *and* resolution** (``_recovery_lock``):
        enumeration spans several ``await``s and ends in :meth:`_reconcile`,
        reading both the trail (``pending_confirmation``) and ``_parked`` and then
        minting into ``_parked`` — all state :meth:`_resume` also mutates when it
        resolves a binding (it records the resolving decision through the runner and
        evicts the binding's ``_parked`` entry). Both :meth:`_pending_confirmations`
        and :meth:`_resume` take this one lock, so a resolution can neither run
        *during* an enumeration nor leave it half-observed: recovery never reads a
        live ``CONFIRM`` that a concurrent resume then resolves before recovery mints
        its token (which would hand back a stale, unanswerable confirmation), and a
        prune only ever runs against the bindings the same call observed. Without the
        shared lock this held only *incidentally*, by the await placement between the
        read and the mint here and between the resolve and the evict in
        :meth:`_resume` — an invariant a later edit could silently break (round 3
        review). Recovery and resolution are both off the latency-critical path
        (human-paced confirmations, a cold restart path), so serializing them costs
        nothing that matters.

        **A routed park is not listed here, and is not recovered across a restart**
        (ADR-0197 §7). ADR-0052 §1's algorithm walks ``plans.active_executions()`` and
        reads the pending ``CONFIRM`` out of the audit trail; a routed park has neither, so
        recovery would mean a second durable park store built for this one shape. What a
        lost routed park costs is one repeated sentence: **nothing has happened yet** — the
        operation has not run, no side effect is pending, and the resolution is a lookup
        the next ask redoes in the same way. An enumeration is refused rather than merely
        omitted, because it would have to render the card again and §7's card is
        engine-assembled from a resolution this process still holds.

        What this call *does* do for a routed park is evict the expired ones, which
        reclaims their ceiling slots earlier. That is opportunistic housekeeping and is
        never what makes an expired park unusable — :meth:`_claim_routed_park`'s check,
        inside the claim and under this same lock, is.
        """
        async with self._recovery_lock:
            self._evict_expired_routes()
            recovered: list[Confirmation] = []
            live: set[tuple[str, str]] = set()
            for state in await self._plans.active_executions():
                plan = await self._plans.get_plan(state.plan_id)
                if plan is None:  # pragma: no cover — an execution without its plan is corrupt
                    continue
                for step in state.steps:
                    if step.status is not StepStatus.AWAITING_APPROVAL:
                        continue
                    confirmed = await self._trail.pending_confirmation(
                        execution_id=state.id, step_id=step.step_id
                    )
                    if confirmed is None:
                        # The binding is already resolved (ADR-0044 §3 step 1), or holds
                        # no CONFIRM; either way there is nothing to present.
                        continue
                    planned = next((s for s in plan.steps if s.id == step.step_id), None)
                    if planned is None:  # pragma: no cover — a step not in its plan is corrupt
                        continue
                    live.add((state.id, step.step_id))
                    recovered.append(
                        self._recovered_confirmation(
                            state.id, step.step_id, planned.parameters, confirmed
                        )
                    )
            await self._reconcile(live)
            return tuple(recovered)

    async def _reconcile(self, live: set[tuple[str, str]]) -> None:
        """Evict every ``_parked`` entry whose durable binding is no longer pending (ADR-0052 §2).

        A ``_parked`` entry — recovered (``turn is None``) *or* an in-process converse
        park (``turn is not None``) — becomes dead once its ``(execution_id,
        step_id)`` binding is resolved, and that resolution can happen out of this
        engine's sight: another engine over the same durable stores answers it (the
        durable-resume topology this whole feature exists for). A dead entry the
        table never removes would leak — and, for a converse park, keep counting
        toward the confirmation ceiling forever, refusing every later turn (#287,
        round 5). So both kinds are reconciled here.

        **The check is authoritative per binding, not a snapshot difference.** An
        entry whose binding is in ``live`` was just observed pending, so it is kept
        without a re-query. Any *other* entry is re-checked directly against the
        trail: a binding that returns ``None`` has been resolved (or holds no
        ``CONFIRM``) and its entry is evicted; one that still returns a ``CONFIRM`` is
        kept. Re-checking rather than trusting "absent from the enumeration snapshot"
        is what makes pruning a converse park **safe against a concurrent
        ``converse``** that parked *after* this call read ``active_executions``: that
        fresh park is not in ``live``, but its binding is genuinely pending, so the
        re-query keeps it. ``converse`` does not take ``_recovery_lock``, so without
        this authoritative re-check a snapshot-difference prune would strand it.

        Runs under ``_recovery_lock`` (its caller holds it), and a same-engine
        ``resume`` — the only path that also evicts — takes the same lock, so no
        eviction races this reconciliation.
        """
        candidates = [
            (handle, parked)
            for handle, parked in self._parked.items()
            if (parked.execution_id, parked.step_id) not in live
        ]
        for handle, parked in candidates:
            pending = await self._trail.pending_confirmation(
                execution_id=parked.execution_id, step_id=parked.step_id
            )
            if pending is None:
                self._parked.pop(handle, None)

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

        **This method holds no** ``MemoryStore`` **and no** ``ContextProvider``
        **while answering** (ADR-0206 §3). The placement is decided from three
        recorded fields of the candidate the outbox handed over, and nothing on this
        path issues a store query of any kind, resolves ``references``, or reads a
        record — which is what keeps ADR-0204 §3's test where ADR-0204 §5 puts it,
        on the producer, rather than on a delivery that has nothing in hand.

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
        return await self._tracked(
            self._poll(outbox, named, wanted, budget),
            "next_notification",
            checked=True,
            shielded=False,
        )

    @staticmethod
    def _check_plays(plays: tuple[SpokenAudioFormat, ...]) -> tuple[SpokenAudioFormat, ...]:
        """Refuse a ``plays`` naming a format that does not exist, and normalise it.

        **An empty one is admitted rather than refused**, unlike ``converse_spoken``'s
        (ADR-0200 §3), and the asymmetry is ADR-0206 §1's: there, an empty preference
        order is a call that could not be answered whatever the synthesizer produces;
        here it is the ordinary state of every caller that cannot play audio, and it
        asks for no rendering rather than for an impossible one.

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
        else** (§7). ``synthesize`` is called directly rather than through
        :func:`~ai_assistant.orchestration.speech.synthesize_within`, because that
        helper exists to thread a *caller's* budget into a stage and this stage has no
        caller's budget to thread: ADR-0135 §3 gives the poll's ``budget`` to the
        waiting alone.

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
        refused empty or duplicated. Both are local refusals before any I/O
        (ADR-0085 §9), so a wire client refuses exactly what this refuses.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``source`` is blank or unwritable, or ``scope`` is empty
                or names a use twice.
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

    # --- the recipient-grant surface (ADR-0235 §3, §7) ----------------------

    async def grantable_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """List the recorded ``CONFIRM``s an establishing act may ride (ADR-0235 §3).

        ``limit`` is refused when it is **not strictly positive**, on
        ``recent_decisions``' reason and in every implementation (ADR-0186 §3): it
        bounds the trail rows read as well as the rows returned, so a non-positive
        one reaches ``AuditTrail.recent`` as an unbounded read of a Tier 1 store.

        **This is history and never a queue.** Nothing it returns is a park, holds a
        turn, blocks anything or expires under a sweep, and no surface presents one
        as outstanding work (ADR-0231 §9's third limb, ADR-0235 §3).

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            AuditError: If the trail cannot be read.
            PlanningError: If the injected clock's reading is not conforming.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("grantable_decisions", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            self._recipient_grants.grantable_decisions(limit=limit),
            "grantable_decisions",
            checked=True,
        )

    async def establish_recipient_grant(
        self, decision_id: DurableIdentifier, *, expires_at: UtcInstant
    ) -> RecipientGrant:
        """Answer a recorded ``CONFIRM`` no park holds and record the grant (ADR-0235 §3).

        ``decision_id`` undergoes :data:`~ai_assistant.core.types.Identifier`
        validation before any I/O, as every identifier argument on this surface does
        (ADR-0085 §3c) — it both refuses a blank value and strips the one the
        implementation then uses, so a client cannot make ``" id "`` and ``"id"``
        disagree at the seam.

        **This resumes nothing and services nothing.** The ``ALLOW`` it records
        authorises a call that has already been abandoned; no lane executes it,
        re-composes the turn it belonged to, or treats the recorded answer as making
        anything runnable (ADR-0231 §9's first limb).

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``decision_id`` is blank or unwritable.
            UngrantableActError: If the act may not ride this decision — any of
                ADR-0235 §3's seven conditions, at the check or late against the
                trail's own resolution invariant, or an expiry that is not strictly
                after the instant the answer would carry. **No answer is recorded.**
            PermissionDeniedError: If the policy answered other than an ``ALLOW``.
                That answer **is** recorded and the confirmation is thereby settled.
            AuditError: If the trail cannot be read or refused the answer.
            InvalidRecipientGrantError: If the store refused the grant. The answer
                stays recorded and nothing is evicted to make room.
            RecipientGrantError: If the grant store cannot be written.
            OversizedValueError: If the arguments or the record exceed the limit.
        """
        self._reject_if_closing()
        named = identifier(decision_id, name="decision_id")
        check_arguments(
            "establish_recipient_grant",
            max_bytes=self._max_payload_bytes,
            decision_id=named,
            expires_at=expires_at,
        )
        return await self._tracked(
            self._recipient_grants.establish_recipient_grant(named, expires_at=expires_at),
            "establish_recipient_grant",
            checked=True,
        )

    async def standing_recipient_grants(self) -> tuple[RecipientGrant, ...]:
        """List every standing recipient grant that is live now (ADR-0235 §7).

        Delegated whole; what this layer adds is the drain tracking and the result
        measurement. **It takes no ``limit``**, for ``standing_grants``' reason one
        store over: a truncated answer to "what do I authorise" is a false answer
        rather than a partial one, so a live set that does not fit the frame is an
        ``OversizedValueError`` and no set at all.

        Raises:
            RuntimeError: If the engine is shutting down.
            RecipientGrantError: If the grant store cannot be read.
            OversizedValueError: If the live set does not fit the contract limit.
        """
        self._reject_if_closing()
        return await self._tracked(
            self._recipient_grants.standing_recipient_grants(),
            "standing_recipient_grants",
            checked=True,
        )

    async def recent_recipient_grants(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecipientGrant, ...]:
        """List the recipient-grant store's own history, newest first (ADR-0235 §7).

        Granting and revoking records alike, and **no liveness**: a record here says
        an act happened, never that it still stands. ``limit`` is refused when it is
        not strictly positive, on ``recent_grants``' reason and in every
        implementation.

        Raises:
            RuntimeError: If the engine is shutting down.
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
            RecipientGrantError: If the grant store cannot be read.
            OversizedValueError: If the page exceeds the contract limit.
        """
        self._reject_if_closing()
        positive_page_argument(limit, name="limit")
        check_arguments("recent_recipient_grants", max_bytes=self._max_payload_bytes, limit=limit)
        return await self._tracked(
            self._recipient_grants.recent_recipient_grants(limit=limit),
            "recent_recipient_grants",
            checked=True,
        )

    async def revoke_recipient_grant(self, grant_id: DurableIdentifier) -> RecipientGrant | None:
        """Withdraw one standing recipient grant, or report there was none (ADR-0235 §7).

        **Never refused for the ceiling**, whatever the outstanding count: a ceiling
        that could block a revocation would trap a user above it with no way down
        (ADR-0193 §1). It is the recourse the ceiling's own refusal names, so nothing
        stands between the user and it.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``grant_id`` is blank or unwritable.
            InvalidRecipientGrantError: If the store refused the revoking record on
                any ground other than the grant having been revoked in the interval.
            RecipientGrantError: If the grant store cannot be read or written.
            PlanningError: If the injected clock's reading is not conforming.
            OversizedValueError: If the argument or the record exceeds the limit.
        """
        self._reject_if_closing()
        named = identifier(grant_id, name="grant_id")
        check_arguments("revoke_recipient_grant", max_bytes=self._max_payload_bytes, grant_id=named)
        return await self._tracked(
            self._recipient_grants.revoke_recipient_grant(named),
            "revoke_recipient_grant",
            checked=True,
        )

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
        work itself, not merely the public call: a client cancelling its own
        ``converse()`` mid-call abandons the awaiting coroutine but not the work it
        started, which keeps using the connection a subsequent ``close()`` would
        shut. Each public call therefore runs as a **shielded** task this engine
        holds a reference to, so cancelling the caller leaves the underlying task
        running and tracked, and this drain still awaits it. Only then are the
        owned resources closed, in the order the composition root handed them.

        **The drain-and-close is one memoised task, and every caller awaits it
        shielded.** So cancelling *this* ``aclose`` — not only a ``converse`` —
        cannot abandon the closures half-done: the shutdown task keeps running to
        completion, and a subsequent ``aclose`` awaits the same task rather than
        returning early over resources that were never closed (ADR-0042 §2). This
        is what makes ``aclose`` idempotent *and* cancellation-safe; the closers
        run exactly once.
        """
        self._closing = True  # stop accepting new work at once (§2)
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
        step ``RUNNING`` with its classification unwritten.

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
        _log.info("shutdown_drain_budget_exceeded", cancelling=len(pending))
        for task in pending:
            task.cancel()
        # Unbounded, and `return_exceptions=True` so a cancelled task's
        # `CancelledError` is a *result* here rather than something that aborts the
        # gather and skips its siblings. Every one must complete before a closer runs.
        await asyncio.gather(*pending, return_exceptions=True)

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
        here, so none can be racing a store call when :meth:`aclose` closes it —
        recovery reads the plan store and the audit trail, so it is tracked too. The
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

        The half of :meth:`_tracked` that does not await, extracted because
        :meth:`_streamed` needs the task itself: a streaming turn runs *beside* the
        iterator relaying it, so that abandoning the iterator leaves the turn
        running to completion (ADR-0173 §9) and still inside the drain ADR-0042 §2
        obliges.

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
        task: asyncio.Task[_T] = asyncio.ensure_future(
            self._operation_traces.observing(seam, work, observe) if traced else work
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
        task: asyncio.Task[_T] = asyncio.ensure_future(coro)
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

    def _admit_and_reserve(self) -> str:
        """Admit one step for driving under the confirmation ceiling, reserving its slot.

        The backpressure that keeps the outstanding-confirmation table bounded
        **without** ever dropping a live continuation (ADR-0042 §4; #287): at the
        ceiling the engine refuses to drive another step rather than parking one
        and having to strand it. A refusal parks nothing and strands nothing — the
        caller resolves an outstanding confirmation and retries.

        **Admission and reservation are one atomic step.** This runs to completion
        with no ``await``, so concurrency cannot bypass the ceiling: capacity counts
        the in-process parks *and* the slots reserved by turns still in flight
        (``_reserved``), and the reserving write happens before this returns, so the
        Nth concurrent turn sees the N-1 already-reserved slots and is refused once
        they fill the ceiling. This is why the limit is **hard**, not merely a
        post-hoc check that several turns could pass together. The slot is released
        by :meth:`_converse` once the turn parks (moving into ``_parked``, which
        then counts it) or does not.

        **A routed park counts, and it takes no exemption** (ADR-0197 §7). It is exactly
        the shape the ceiling exists for — "a client that requests confirmable actions and
        abandons every token would grow the table without bound" — so it is counted here,
        the ceiling gets no second setting and no routed-only variant, and a route that
        cannot reserve a slot meets the same backpressure a step-driving turn does, in the
        same form. Expired routed parks are evicted first, which reclaims their slots
        earlier; that is opportunistic housekeeping and is never what makes an expired park
        unusable, which is :meth:`_claim_routed_park`'s check under the lock.

        **Recovered entries do not count.** The ceiling bounds the memory a client
        can pin by requesting confirmable actions and abandoning their tokens — the
        *converse* path, whose entries carry the turn (``turn is not None``). An
        entry recovered from durable state (``turn is None``,
        :meth:`pending_confirmations`) is bounded by durable state and reconciled on
        each recovery, so counting it would let durably-parked work apply false
        backpressure to new turns (a resolution by another engine could otherwise
        leave a stale entry that blocks forever). So capacity counts only
        turn-carrying parks.

        **A settled record does not count either, and it is the clearest case**
        (ADR-0198 §4). This ceiling bounds *unanswered* parks; a settled record is the
        opposite of one, and counting it would let a client that answered every
        confirmation meet backpressure for having done so. The retained set is bounded
        separately, by the same number, in :meth:`_retain`.

        Called *before* the runner can park and before the turn is persisted, so a
        refusal leaves neither durable execution state nor a durable goal/plan.

        Raises:
            RuntimeError: If ``max_outstanding_confirmations`` confirmations are
                already outstanding or reserved.
        """
        self._evict_expired_routes()
        outstanding = sum(1 for parked in self._parked.values() if parked.turn is not None)
        outstanding += len(self._routed_parks)
        if outstanding + len(self._reserved) >= self._max_outstanding:
            msg = (
                f"{self._max_outstanding} confirmations are already awaiting an answer; resolve "
                "some before starting another action"
            )
            raise RuntimeError(msg)
        return self._mint_handle()

    def _mint_handle(self) -> str:
        """Reserve and return a handle no continuation of this process has ever used.

        The injected factory supplies the opacity; the engine supplies the
        *uniqueness*, and it supplies it by **stamping a serial on every handle**
        rather than by checking the candidate against anything. One integer of state,
        no scan, no collision, and no way for two continuations of this process to
        share a name whatever the factory does.

        **Uniqueness has to be over the process's whole life, not over what is live
        now**, which is the defect #1644 records. Testing a candidate against the live
        tables made a handle mintable again the moment nothing named it — after a
        resolution, after a reconciliation, or after a settled record was discarded
        under ADR-0198 §4's bound. A repeating factory would then hand a new park a
        handle an earlier caller still holds a token for, and presenting that stale
        token would resolve the **new** park: an old confirmation authorising an
        action nobody offered it for.

        **A serial rather than a set of spent handles, and the reason is this
        method's caller.** :meth:`_admit_and_reserve` mints *before* the runner knows
        whether the step will park at all, so a handle is minted for every turn that
        drives a step — including every turn that parks nothing and hands no token to
        anybody. Remembering them would grow one string per turn for the life of the
        hub, unbounded and reachable by a client that holds no confirmation at all,
        which the confirmation ceiling cannot bound because it counts parks. It would
        also be a second in-memory table beside ADR-0198 §4's, and an *un*bounded one
        beside a decision whose whole answer was "a count is the whole of the bound".
        The serial buys the same guarantee for one integer, so no such table exists
        and §4's account of what the engine holds stays exactly true.

        This subsumes ADR-0198 §4's mint clause strictly rather than dropping it: "a
        handle naming a settled record is not minted for a new park … while the record
        is retained" holds because no handle is ever minted twice, and it goes on
        holding after the record is discarded, which is where the live-table test
        stopped.

        **The epoch is what makes the process scope a fact rather than an assertion**
        (ADR-0084 §7, ADR-0198 §4). The serial restarts with the engine, exactly as
        the parked, routed and settled tables do — so on a serial alone a restarted
        hub with a repeating ``id_factory`` would mint a *previous* process's handle
        for a new park, and that process's token would resolve it: the very aliasing
        this method exists to refuse, moved one lifetime over. A fresh epoch per engine
        closes it, which is what ADR-0198 §4's "a token from a previous process life
        yields ``UnknownContinuationError``" needs in order to be true of every
        ``id_factory`` rather than only of a random one.

        **That is the whole of the claim, stated at its real width: the epoch bounds
        what ``id_factory`` can do, and nothing bounds the epoch but its own seam's
        contract.** Two engines handed an ``epoch_factory`` that repeats a value share
        an epoch, and one's token can then name the other's park — just as an engine
        handed a ``now`` that lies about the instant sweeps against the wrong horizon.
        Both are injected seams whose contract the composition root honours rather
        than ones this class polices; :meth:`__init__` states this one, and its
        default is a UUID precisely so that honouring it takes no act.

        The epoch comes from its **own** injected factory, defaulting to a UUID.
        Randomness lives behind a seam (``CONTRIBUTING`` → "Determinism"), and it is a
        second seam rather than a reuse of ``id_factory`` because drawing the epoch
        from that factory would make two engines sharing one agree on it — the very
        case the epoch exists to separate. Recovering an answerable confirmation
        across a restart stays ``pending_confirmations``' job, and it re-mints through
        this method (ADR-0052 §1).

        The suffix is not a secret and does not need to be: the factory's value is
        what makes a handle unguessable, and the token stays opaque to every caller
        (ADR-0042 §4) — an adapter may not interpret it, and nothing in the engine
        reads the serial back.

        **Reservation is atomic against concurrency.** This method runs to completion
        with no ``await`` between minting and recording the reservation, so two
        concurrent turns cannot both take one handle. The reservation is released by
        :meth:`_converse` once the turn is known to park (moved into the parked table)
        or not. Called *before* the runner can park, so a raising factory fails with
        no durable state yet committed.
        """
        handle = f"{self._id_factory()}#{self._handle_epoch}#{next(self._handle_serial)}"
        self._reserved.add(handle)
        return handle

    async def _converse(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        conversation_id: str | None,
    ) -> TurnOutcome:
        """Run one whole turn, composing its answer atomically (ADR-0170 §1).

        **This operation's output channel has a bounded audience**, so ADR-0203 §1's
        last clause governs it and the turn runs over its whole supply. What it mints
        is ADR-0204 §2's evaluation of that supply — made on every conversational
        operation, subtracted from none but a spoken one — so its capture records
        whether content ADR-0199 §3 withholds stood in this turn's warrant (§4).
        """
        return await self._run_turn(
            utterance,
            timeout=timeout,
            conversation_id=conversation_id,
            compose=self._composed_whole,
            compose_routed=self._composed_routed_whole,
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            # ADR-0228 §4: which operation this is, and nothing about how long it may
            # spend. `ConversationalOperation.CONVERSE` prices itself.
            operation=ConversationalOperation.CONVERSE,
        )

    async def _converse_streaming(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        conversation_id: str | None,
        chunks: asyncio.Queue[ReplyChunk],
    ) -> TurnOutcome:
        """Run one whole turn, publishing its answer as it composes (ADR-0173 §4).

        **The same turn, and deliberately the same code.** Everything before the
        composing stage — resolving the conversation, reading its tail, planning,
        the confirmation ceiling, driving the step, and the capture afterwards — is
        :meth:`_run_turn`'s, unchanged. ADR-0173 adds a stage to nothing and moves
        no other stage; what it changes is which seam the composing stage spends the
        turn's one model call at (§7) and where the answer goes on its way to the
        outcome.

        Args:
            utterance: What the user said.
            timeout: The per-attempt budget.
            conversation_id: The conversation to continue, or ``None``.
            chunks: Where each composed :class:`~ai_assistant.core.types.ReplyChunk`
                is put as it is produced. The relaying iterator owns reading it, and
                a reader that has gone away does not stop this turn (ADR-0173 §9).

        Returns:
            The turn's outcome, whose ``reply`` is the join of whatever was put on
            ``chunks`` (ADR-0173 §3).
        """

        async def compose(  # noqa: PLR0913 — :data:`_Composer`'s six, and each is a distinct fact about the pass
            turn: TurnResult | None,
            step: StepOutcome | None,
            conversation: str,
            deliveries: Mapping[str, SpokenDelivery],
            hop_reached: Sequence[str],
            stopped_while_asking: bool,
        ) -> ComposedReply | None:
            return await self._compose_streaming(
                turn, step, conversation, chunks, deliveries, hop_reached, stopped_while_asking
            )

        async def compose_routed(
            routed: RoutedOperation, conversation: str
        ) -> ComposedReply | None:
            return await self._compose_routed_streaming(routed, conversation, chunks)

        return await self._run_turn(
            utterance,
            timeout=timeout,
            conversation_id=conversation_id,
            compose=compose,
            compose_routed=compose_routed,
            # A bounded audience, exactly as :meth:`_converse`'s: this operation
            # differs from it in where the composed answer goes and in nothing this
            # evaluation reads (ADR-0173 §4, ADR-0204 §2).
            supply=BoundedAudienceSupply(
                speakable_attested_sources=self._speakable_attested_sources
            ),
            # ADR-0228 §4: its own member, which happens to price itself the same as
            # `converse` — these two differ in where the answer goes rather than in
            # how long a user waits for it, and §4 keys the budget on the operation.
            operation=ConversationalOperation.CONVERSE_STREAMING,
        )

    async def _composed_whole(  # noqa: PLR0913 — :data:`_Composer`'s six, and each is a distinct fact about the pass
        self,
        turn: TurnResult | None,
        step: StepOutcome | None,
        conversation: str,
        deliveries: Mapping[str, SpokenDelivery],
        hop_reached: Sequence[str],
        stopped_while_asking: bool,
    ) -> ComposedReply | None:
        """Compose atomically, ignoring the conversation the streaming twin needs.

        ``conversation`` is what :meth:`_compose_streaming` measures its ceiling
        against; the whole-answer path has no ceiling of its own — ADR-0170 §8 makes
        an over-ceiling answer a refusal, because nothing has been published — so it
        is accepted and dropped rather than making :meth:`_run_turn` carry two
        composer shapes.

        **The tail's delivery facts reach this stage too, and that is deliberate**
        (ADR-0205 §5). A turn on ``converse`` whose tail carries one is a real case —
        the owner speaks, is interrupted, and then types — and an answer that was not
        heard is one no turn should build on, whatever channel the next turn arrives
        by. The facts are about the tail's deliveries, not about this turn's channel.

        **And so does ADR-0227 §3's carrier**, for a reason of the same shape: what it
        says is which records this turn's citation hop reached, which is a fact about
        how those records were fetched and not about where the answer is going. So
        does ADR-0228 §10's, which says the turn stopped looking while it was still
        asking — a fact about this turn's own planning and not about its channel.
        """
        del conversation
        return await self._compose(
            turn,
            step,
            deliveries=deliveries,
            hop_reached=hop_reached,
            stopped_while_asking=stopped_while_asking,
        )

    async def _persist_plans(self, plans: Sequence[ActionPlan]) -> None:
        """Persist every plan the turn produced, oldest first (ADR-0228 §5).

        **The one site that persists a plan**, which is what makes this a change at a
        single place rather than a second writer: ``save_plan`` was called from
        exactly here, once per turn, and now takes the whole sequence.

        **Oldest first**, so no partially-persisted turn leaves a ``supersedes``
        pointing at a plan the store does not hold — the successor's reference is
        already resolvable by the time it is written, which is the order
        ``PlanStore.save_plan``'s own rejection needs to be satisfiable.

        **All of them, and not only the one the turn drove.** ADR-0226 §9 rests its
        whole minimisation argument on one sentence — "The ask stays durable on the
        frozen ``ActionPlan`` (§4) and the record neither copies it nor points at it"
        — and ADR-0226 §10 rests the persisted-plan fire rate on "every turn's plan is
        persisted". Under iteration the ask that was actually **serviced** is on the
        *first* plan, which the turn then replaces: a design persisting only the plan
        it drove would silently delete the record of why the turn read what it read,
        and would make ADR-0226 §9's argument false the day this milestone ships.

        **A turn that ends before this method is reached persists nothing, exactly as
        it did before** (§5). A turn whose second planner call raised, one rejected
        for capacity and one that failed before the planner was reached are alike in
        that and were alike before ADR-0228 — the loop is given no ``PlanStore`` and
        no plan is carried out of a failing turn in order to write it. What such a
        turn still owes is ADR-0226 §9's record, which is emitted from ``respond``'s
        ``finally`` and conditioned on nothing.

        Args:
            plans: Every plan the turn produced, oldest first — one member on a turn
                that did not revise, two on one that did.

        Raises:
            PlanningError: As ``save_plan`` raises it. This adds no failure mode and
                no degradation posture: a ``save_plan`` that raises on a superseded
                plan fails the turn exactly as one raising on any other plan does
                today, and nothing here swallows it. A turn whose first plan persisted
                and whose second raised leaves a plan with no successor, which is a
                complete record of what that turn decided and is not a dangling
                reference — the link points backwards.
        """
        for plan in plans:
            await self._plans.save_plan(plan)

    async def _run_turn(  # noqa: PLR0913 — the utterance, the budget, the conversation, the two composers, the supply filter and the spoken capture; every one is a distinct fact about the pass, and collapsing any pair would put a flag where a value belongs
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        conversation_id: str | None,
        compose: _Composer,
        compose_routed: _RoutedComposer,
        supply: TurnSupply,
        operation: ConversationalOperation,
        spoken: _SpokenCapture | None = None,
    ) -> TurnOutcome:
        """Route the ask, or resolve the conversation, plan the turn and drive its step.

        ``compose`` is how this pass's answer is produced — atomically for
        :meth:`converse`, as a stream for :meth:`converse_streaming` — and
        ``compose_routed`` is its twin for a pass that took a route, which composes from
        ADR-0197 §6's two enum values instead of from a turn. Both are parameters rather
        than a flag because the streaming and whole paths differ in nothing else: a second
        copy of this method would be two places for the confirmation ceiling, the
        reservation's release and the capture point to drift apart.

        **The routing stage runs first, and a taken route ends the pipeline there**
        (ADR-0197 §1). Nothing after it runs on such a pass: no history is read, no goal is
        minted, no context is assembled, no memories are retrieved, no plan is made or
        persisted, and no step is driven. A **declined** route is not a failure and is not
        reported as one — the pass proceeds exactly as it does today and the outcome it
        returns carries no trace of the stage having run.

        **The conversation is resolved before the route is taken**, which ADR-0197 §1
        neither requires nor forbids and ADR-0074 §2 does require: "every turn runs under a
        conversation, and the outcome reports which", resolved "**before** the turn's
        work". A routed pass is a turn — it is captured (§10) and its row names the
        conversation (§9) — so an unknown ``conversation_id`` is refused before anything is
        routed, exactly as it is refused before anything is planned.

        **``supply`` is how an operation whose channel audience is unbounded subtracts
        what ADR-0199 §3 withholds** (ADR-0203 §1). It is handed to the turn stage, which
        applies it between retrieval and planning, so everything below this line — the
        plan, the persisted plan, the step this pass drives, the origin the authoriser
        evaluates, the answer composed and the episode captured — is over the subtracted
        supply, and there is no wider turn anywhere in this method. An operation whose
        channel audience is bounded hands the twin that subtracts nothing, and plans over
        everything it retrieved exactly as before (ADR-0204 §4). A **routed** pass reaches
        no retrieval and no planner, so there is nothing there for it to subtract from.

        **And it is the same object the capture point reads its stamp off** (ADR-0204
        §2). The evaluation is made once per turn, between retrieval and planning, on
        **every** conversational operation — what varies by audience is whether its
        subtraction is applied, never whether it is made — and the boolean it recorded
        travels to capture as a value the pipeline computed rather than one capture
        judges. A turn that parks carries it onto the parked entry too, because the
        park's *second* capture renders that same turn's goal and plan (§2's fourth
        clause) from a pass that retrieves nothing of its own.

        **A planner-emitted read is serviced on this pass only where that same
        object says the audience is bounded** (ADR-0226 §5), and the turn stage reads
        that off ``supply`` itself rather than off a second argument this method
        would have to keep in step. So the operation that hands the unbounded twin is
        the operation whose request is declined, its supply stays the three groups
        ADR-0203 §1 narrowed, and its audit records the emission and that it was not
        serviced. Everything below this line — the plan is already made, but the step
        this pass drives, the origin the authoriser evaluates, the answer composed
        and the episode captured — is over the four groups on a bounded pass that
        fired, which is ADR-0226 §7's fourth group reaching the turn rather than a
        second turn.

        **``spoken`` is how ADR-0205 §4's "on this operation and no other" is
        mechanical rather than remembered.** ``converse_spoken`` hands one; every
        other conversational operation hands ``None``, so the capture point below
        writes a ``delivery`` exactly where one is owed and this method never asks
        which operation it is running under. It is also where the episode id the
        capture allocated is written back, for ``SpokenTurn.episode_id`` to disclose
        (§1) — a routed pass included, since a routed spoken pass is a turn of this
        operation and is captured as one.

        **The tail's delivery facts ride to the composing stage off the history this
        method already read** (ADR-0205 §5). ``ConversationLifecycle.history`` walks
        the index rows for the records themselves and holds every one of them, so the
        facts cost no second store call, no second context assembly and no second
        retrieval — and they are paired down to the episodes that **survived** the
        supply filter, so a turn whose episode was withheld under ADR-0199 §3 or
        ADR-0204 §3 contributes no delivery fact either.
        """
        # Before the turn's work (ADR-0074 §2), so the id exists whatever the turn
        # does and a continuation marks the conversation active before a reclaim
        # could judge it idle.
        conversation = await self._conversations.begin(conversation_id)
        route = None if self._routing is None else await self._routing.route(utterance)
        if route is not None:
            return await self._routed_pass(
                utterance,
                route,
                conversation=conversation.id,
                compose=compose_routed,
                spoken=spoken,
            )
        history = await self._conversations.history(conversation.id)
        # ADR-0227 §3: the turn and, beside it, which of its records this turn's
        # citation hop reached. Supplied by the loop — the servicer under it is the
        # one component that can distinguish the two kinds — and carried to the
        # composing stage exactly as the delivery facts below are, never inferred
        # here and never read off `turn.memories`.
        responded = await self._loop.respond(
            utterance,
            history=history.records,
            history_degraded=history.degraded,
            narrow=supply,
            operation=operation,
        )
        turn = responded.turn
        hop_reached = responded.hop_reached
        # ADR-0228 §5: **every** plan the turn produced, oldest first, and
        # `turn.plan` is the last of them. Read here beside the turn so that the two
        # `save_plan` sites below take the whole sequence rather than the driven plan
        # alone — "a turn that persists a plan at all persists all of them".
        plans = responded.plans
        # ADR-0228 §10's carrier, threaded to the composing stage exactly as the hop
        # set above is and never inferred here — not from the plan, not from the
        # supply's length, and not from the audit.
        stopped_while_asking = responded.stopped_while_asking
        # ADR-0205 §5: the fact travels with the episode it qualifies and never
        # without it. `turn.memories` is the supply as `narrow` returned it, so
        # intersecting here is what makes a withheld record's delivery unreachable by
        # construction rather than by the renderer happening not to look for it.
        deliveries = _paired_deliveries(history.deliveries, turn.memories)
        # ADR-0204 §2: read once, immediately after the one evaluation that set it,
        # so every capture below stamps the same turn's own value and no branch can
        # recompute it from a supply that has moved on.
        withheld = supply.withheld
        # ADR-0221 §5's first case, decided once for this pass: the episode renders
        # this pass's own user material, and `SPEECH` goes exactly where `_capture` is
        # given a `_SpokenCapture` — the passes of `converse_spoken` and no other.
        # Nothing is inferred and nothing is asked; this method is told which
        # operation it is running under, exactly as it is for the delivery.
        modality = Modality.TEXT if spoken is None else Modality.SPEECH
        # ADR-0223 §2, hoisted here beside `withheld` and `modality` for their reason
        # and read once: this pass's own disjunction of
        # `rests_on_recorded_external_content` over the selection it actually made.
        # ADR-0181 §2, §4 already put computing it on this component — `turn.memories`
        # **is** that selection, carried on the turn as data `LearningLoop.respond`
        # assembled (the conversation's recent turns, then the relevance-retrieved
        # beliefs, then the episodic supplement), so one argument here is already the
        # disjunction over every selection that fed this pass. Computed **before
        # anything is driven** and above the branch, so the no-step branch below
        # stamps it too — the branch a threading from the old call site, which sat
        # inside the branch that has a step, would have lost. One computation, two
        # consumers: the episode's stamp and the `SelectionOrigin` the runner is
        # given, which makes them the same boolean rather than two that agree.
        origin = SelectionOrigin.over(turn.memories)
        external = origin.planned_with_external_content
        self._check_plan_is_for_goal(turn)
        if not turn.plan.steps:
            # A no-action decision is still a decision, and drives nothing that
            # could park — so it needs no capacity slot, and its goal and plan are
            # persisted as an auditable record (ADR-0014 §2).
            await self._plans.save_goal(turn.goal)
            await self._persist_plans(plans)
            composed = await compose(
                turn, None, conversation.id, deliveries, hop_reached, stopped_while_asking
            )
            return await self._capture(
                conversation.id,
                turn=turn,
                step=None,
                resumed=False,
                composed=composed,
                # ADR-0225 §1's first case: the pass carried a turn, so the user's
                # own words are that turn's goal statement — the value before
                # `_exchange_of` folds it into a rendering.
                asked=turn.goal.statement,
                supplied_withheld=withheld,
                modality=modality,
                # ADR-0223 §3's first case on the branch §2 exists for: the pass
                # produced the turn this episode renders, so the value is that turn's
                # own — the same one an otherwise identical pass with a step stamps.
                derived_from_external=external,
                spoken=spoken,
            )
        first = turn.plan.steps[0]
        # Admit-and-reserve *before* anything is persisted or driven, atomically
        # (no await), so a backpressure refusal at the ceiling writes no durable
        # goal/plan and no execution — a flood of refused turns leaves no
        # inaccessible plan state behind (round 8) — and the ceiling is a hard bound
        # even under concurrency (:meth:`_admit_and_reserve`). The reserved handle
        # is also the continuation token, minted here before the runner can park so
        # a raising id factory fails with no durable state committed (#287).
        handle = self._admit_and_reserve()
        try:
            await self._plans.save_goal(turn.goal)
            # ADR-0228 §5: the **whole** sequence of `save_plan` calls precedes
            # `start_execution`, so a turn whose second `save_plan` raises has driven
            # nothing — no execution is open, no capacity slot is spent on a step and
            # no side effect has been reached. The naive extension writes each plan as
            # it is produced, which would put a `save_plan` failure *after* a step had
            # run: the failure a persistence error should produce is a turn that
            # decided and recorded nothing, not one that acted and then lost the
            # record of why.
            await self._persist_plans(plans)
            state = await self._plans.start_execution(turn.plan.id)
            # ADR-0181 §2, §4: the origin the authoriser evaluates — the value
            # hoisted above, handed on rather than recomputed here. Until ADR-0223 §2
            # it was computed at this line, inside the branch that has a step to
            # drive; a lane adding a second model call over a second selection adds
            # an argument to that one call (§4's third clause) rather than replacing
            # it or reinstating a second one here.
            disposition = await self._runner.run(state, first.id, timeout=timeout, origin=origin)
            step = self._step_outcome(
                turn,
                disposition,
                step_id=first.id,
                handle=handle,
                supplied_withheld=withheld,
                modality=modality,
                derived_from_external=external,
            )
        finally:
            # The reservation held the slot across the awaits. It is now either in
            # the parked table (the step parked, which counts it) or unused (it did
            # not); either way the in-flight reservation is released.
            self._reserved.discard(handle)
        # A turn that parked records the binding it parked on, which is the *only*
        # thing a later resumption — possibly in another process, with no live turn
        # behind its token — has to find its way back to this conversation
        # (ADR-0074 §3).
        parked = (
            ParkedBinding(execution_id=step.state.id, step_id=first.id)
            if step.confirmation is not None
            else None
        )
        # The terminal composing stage, after execution and before the exchange is
        # recorded (ADR-0170 §1). Ordering against capture is free — ADR-0170 §9
        # leaves whether the answer joins the captured episode to `track:memory`
        # (#1314) — so composing first is chosen for the reason that the capture
        # point is the single place a ``TurnOutcome`` is built, and folding one more
        # already-computed value into it beats threading a second construction site.
        composed = await compose(
            turn, step, conversation.id, deliveries, hop_reached, stopped_while_asking
        )
        return await self._capture(
            conversation.id,
            turn=turn,
            step=step,
            resumed=False,
            parked=parked,
            composed=composed,
            # ADR-0225 §1's first case, as on the branch above and for its reason.
            asked=turn.goal.statement,
            supplied_withheld=withheld,
            modality=modality,
            # ADR-0223 §3's first case: this pass's own value, carried unchanged from
            # the one computation above — the same boolean the runner's
            # ``SelectionOrigin`` carried to the egress seam on this very pass.
            derived_from_external=external,
            spoken=spoken,
        )

    # --- ADR-0197's routing stage, driven --------------------------------

    async def _routed_pass(
        self,
        utterance: str,
        route: RoutedRoute,
        *,
        conversation: str,
        compose: _RoutedComposer,
        spoken: _SpokenCapture | None = None,
    ) -> TurnOutcome:
        """Drive one taken route to its end (ADR-0197 §1, §5, §7, §9).

        **A taken route ends the pipeline here.** No goal is minted, no context is
        assembled, no memories are retrieved, no plan is made or persisted, no step is
        driven and no ``ToolRegistry``, ``ActionPolicy`` or ``ToolInvoker`` is reached.
        The composing stage still runs, on ADR-0197 §6's two inputs — unless the route
        parks, which owes no answer at all.

        **The two resources a route holds are taken together and released together**
        (§7, §9): a ceiling slot, on a confirm-owed route that may park, and a
        ``route_id``, on every route including a read-only one. Both are reserved in one
        synchronous section with no ``await`` in it, and both are released in a
        ``finally`` — the row failing to write, the id factory raising, the resolution
        raising, the pass being cancelled at any await between the reservation and the
        registration, and any defect in the code between them. "A slot that can be
        reserved and never released is the memory-exhaustion vector the ceiling exists to
        close, reintroduced through the ceiling itself."
        """
        operation = route.operation
        reservation = self._admit_route(operation)
        if reservation is None:
            # §9's retry budget exhausted: nothing reserved, nothing parked, no row
            # written, no token minted and the operation never called.
            _log.warning("route_unrecorded", reason="no_route_id", operation=operation.value)
            return await self._finish_route(
                conversation,
                utterance,
                RoutedOperation(operation=operation, outcome=RouteOutcome.UNRECORDED),
                compose=compose,
                spoken=spoken,
            )
        registered = False
        try:
            outcome = await self._drive_route(
                route, conversation=conversation, reservation=reservation
            )
            registered = outcome.outcome is RouteOutcome.AWAITING_CONFIRMATION
            if registered:
                # §10: a routed park is not composed for. The confirmation is what the
                # user must answer, and prose beside it competes with the question.
                return await self._finish_route(
                    conversation, utterance, outcome, compose=None, spoken=spoken
                )
            return await self._finish_route(
                conversation, utterance, outcome, compose=compose, spoken=spoken
            )
        finally:
            # Held across every await above and released here on every path, which is
            # what `_run_turn` already does with the handle it reserves before driving a
            # step — and released the same way round. The **slot reservation always
            # goes**: a registered park is in `_routed_parks`, which `_admit_and_reserve`
            # counts, so leaving the handle in `_reserved` too would spend one ceiling
            # slot twice and never give either back. The **identity** is the one a live
            # park keeps, because its answer will be written under it and no second route
            # may take it while it can still be claimed.
            self._release_route(reservation, identity=not registered)

    async def _drive_route(
        self,
        route: RoutedRoute,
        *,
        conversation: str,
        reservation: _RouteReservation,
    ) -> RoutedOperation:
        """Resolve, record and then act — in that order, always (ADR-0197 §9).

        **The row is written before the act it precedes**, which is this repository's own
        pattern rather than a new one: ``ConversationTurn``'s index entry lands before the
        episode it names for the same reason. The alternative ordering cannot be made true
        by any amount of care — the two writes are to two stores, and a failure or a
        cancellation between them leaves a destroyed belief with no row. Ordering it this
        way inverts the residual into the safe direction: a cancellation between the write
        and the call leaves a **row for an operation that did not happen**, and an
        over-recorded trail is one an operator can reconcile where an under-recorded one
        is a trail nobody can trust.
        """
        operation = route.operation
        if not operation.confirm_owed:
            if not await self._record_route(
                reservation.route_id,
                operation=operation,
                approval=RouteApproval.NOT_OWED,
                subject=None,
                conversation_id=conversation,
            ):
                return RoutedOperation(operation=operation, outcome=RouteOutcome.UNRECORDED)
            return await self._perform_route(operation, argument=None)
        resolution = await resolve_route(self._routed_surface(), operation, _query_of(route))
        if not isinstance(resolution, Resolved):
            # §5: ambiguity and absence both end the route. Nothing is performed, nothing
            # is confirmed, and §9 writes no row — the route decided nothing to do.
            return RoutedOperation(
                operation=operation, outcome=resolution.outcome, listing=resolution.listing
            )
        if not await self._record_route(
            reservation.route_id,
            operation=operation,
            approval=RouteApproval.OWED,
            subject=resolution.argument,
            conversation_id=conversation,
        ):
            return RoutedOperation(operation=operation, outcome=RouteOutcome.UNRECORDED)
        return self._register_routed_park(
            operation, resolution, reservation=reservation, conversation=conversation
        )

    def _register_routed_park(
        self,
        operation: RoutableOperation,
        resolution: Resolved,
        *,
        reservation: _RouteReservation,
        conversation: str,
    ) -> RoutedOperation:
        """Move the reservation into a live park and mint its card (ADR-0197 §7).

        Runs to completion with no ``await``, so the entry is in the table before any
        other caller can observe the slot as free. The handle was reserved and is now
        spent: it is the continuation token the adapter relays back, and nothing else
        resolves this park.

        **The card carries no model-written text.** Its content is the operation and the
        resolved subject as a typed value, and every word the user reads around them is
        the adapter's own, selected by the enum member. No free text the router produced —
        the query included — reaches it.
        """
        handle = reservation.handle
        if handle is None:  # pragma: no cover — a defect: a confirm-owed route reserves one
            msg = f"a routed {operation.value} reached its park with no reserved handle"
            raise AssertionError(msg)
        self._routed_parks[handle] = _RoutedPark(
            operation=operation,
            subject=resolution.subject,
            argument=resolution.argument,
            route_id=reservation.route_id,
            conversation_id=conversation,
            registered_at=self._now(),
        )
        return RoutedOperation(
            operation=operation,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=OperationConfirmation(
                operation=operation,
                subject=resolution.subject,
                token=ContinuationToken(handle=handle),
            ),
        )

    async def _perform_route(
        self, operation: RoutableOperation, *, argument: str | None
    ) -> RoutedOperation:
        """Call the operation and classify what came back (ADR-0197 §2, §8).

        ``FAILED`` means the operation was **called and raised**, and nothing is asserted
        about whether it took effect — which is the opposite statement from ``UNRECORDED``,
        where the row was not written so the operation was never called at all. A surface
        that rendered the two alike would tell a user their belief might be gone when this
        decision guarantees it is not.

        Every exception is classified, ``BaseException`` deliberately excluded: a
        cancellation is not an operation that failed, and swallowing one here would break
        ADR-0060 §1's propagation clause.
        """
        try:
            listing = await perform_route(self._routed_surface(), operation, argument)
        except Exception:
            _log.warning("route_failed", operation=operation.value, exc_info=True)
            return RoutedOperation(operation=operation, outcome=RouteOutcome.FAILED)
        return RoutedOperation(operation=operation, outcome=RouteOutcome.PERFORMED, listing=listing)

    async def _record_route(
        self,
        route_id: str,
        *,
        operation: RoutableOperation,
        approval: RouteApproval,
        subject: str | None,
        conversation_id: str | None,
    ) -> bool:
        """Write one row of ADR-0197 §9's trail, and say whether the act may proceed.

        The row's own id is minted **here**, from the id factory the engine already holds
        injected, before ``record`` is called: the store mints nothing, because a store
        that minted the id could not be handed a frozen record and a retry could not name
        the row it was retrying. ``decided_at`` comes from the injected clock (ADR-0009),
        never from the store.

        **The write itself goes through the stage**, which is where ADR-0197 §9 puts the
        ``RoutingRecorder`` capability: the engine builds the row and the stage is the only
        object that can append one, so no seam here can read or ``clear`` the trail whose
        rows are about this engine's own acts.

        Returns:
            Whether the row landed. ``False`` is ADR-0197 §9's refuse-to-act: the pass ends
            in ``UNRECORDED``, the operation is not called, no park is registered and no
            token is minted. It applies to read-only members as well as confirm-owed ones
            — one ordering, one failure mode, and no partial mode in which some routed
            operations are recorded and others are not.
        """
        stage = self._routing
        if stage is None:  # pragma: no cover — a route is taken only where one is wired
            msg = "a route was taken with no routing stage wired"
            raise AssertionError(msg)
        return await stage.record(
            RoutedOperationRecord(
                id=self._id_factory(),
                route_id=route_id,
                decided_at=self._now(),
                operation=operation,
                approval=approval,
                subject=subject,
                conversation_id=conversation_id,
            )
        )

    def _admit_route(self, operation: RoutableOperation) -> _RouteReservation | None:
        """Reserve this route's ceiling slot and its identity, atomically (§7, §9).

        **One synchronous section with no** ``await`` **in it**, which is how
        :meth:`_admit_and_reserve` already obtains the ceiling's atomicity on a single
        event loop: the two resources a route holds are taken under one acquisition, and
        the Nth concurrent route sees the N-1 already reserved.

        **A check that is not atomic with the registration is not a check, and the window
        here is wide rather than theoretical** (ADR-0197 §9). Between deciding an id is
        free and registering the park sit §9's row write and the prune it performs — two
        awaits on a durable store — so two routes can each find an empty table, each be
        handed the same id by a repeating factory, and each register. Worse, the prune
        performed by the second is what removes the first's evidence, so the store's
        retained-row rule cannot catch what the in-memory check just missed. Reserving here
        closes the window without adding a second lock.

        **Liveness is checked where liveness lives.** The candidate is tested against every
        ``route_id`` currently *reserved* — those of registered parks and those of routes
        still in flight alike — because the trail's retained rows are not a census of live
        routes at a small ``routing_trail_max_rows``.

        **A read-only route reserves an identity and no slot.** It parks nothing, so it
        takes no capacity (ADR-0197 §1); it reserves an id anyway, because its ``NOT_OWED``
        row under a live park's id would collide with that park's own answer exactly as a
        second park's ``OWED`` row would.

        Returns:
            The reservation, or ``None`` where the retry budget was exhausted — which ends
            the pass in ``UNRECORDED`` with nothing held.

        Raises:
            RuntimeError: If the outstanding-confirmation ceiling is full and this route
                could park. The same backpressure a step-driving turn meets there, in the
                same form (ADR-0197 §7).
        """
        handle = self._admit_and_reserve() if operation.confirm_owed else None
        try:
            live = {park.route_id for park in self._routed_parks.values()}
            for _attempt in range(_ROUTE_ID_ATTEMPTS):
                candidate = self._id_factory()
                if candidate not in live and candidate not in self._reserved_routes:
                    self._reserved_routes.add(candidate)
                    return _RouteReservation(route_id=candidate, handle=handle)
        except BaseException:
            # **The slot is reserved before the identity is, so the identity's own
            # failure is a path the slot must be released on** (ADR-0197 §7, which names
            # "the id factory raising" among them). This runs before
            # :meth:`_routed_pass`'s ``try`` is entered, so nothing else would ever give
            # the handle back: at a ceiling of one, a single raising mint would refuse
            # every later routed confirmation for the life of the process, with no park
            # to evict — the memory-exhaustion vector the ceiling exists to close,
            # reintroduced through the ceiling itself.
            #
            # ``BaseException`` rather than ``Exception``, because a cancellation landing
            # on the injected factory strands the slot exactly as a defect in it would,
            # and the release is unconditional in both cases. Nothing is swallowed: the
            # bare ``raise`` propagates whatever arrived.
            self._release_slot(handle)
            raise
        self._release_slot(handle)
        return None

    def _release_slot(self, handle: str | None) -> None:
        """Give back a ceiling slot reserved for a park that will not exist.

        A no-op on a read-only route, which reserves none: it parks nothing, so it takes
        no capacity (ADR-0197 §1).
        """
        if handle is not None:
            self._reserved.discard(handle)

    def _release_route(self, reservation: _RouteReservation, *, identity: bool) -> None:
        """Release a route's reservations (ADR-0197 §7, §9).

        Called from a ``finally`` on **every** path, and the two halves come apart on
        exactly one of them. The **slot** reservation always goes: once the park is
        registered the ceiling counts the park itself, so a handle left in ``_reserved``
        beside it would spend one slot twice and never give either back — the shape
        :meth:`_run_turn` already avoids by discarding unconditionally once the step has
        either parked or not. The **identity** is released only where the route did not
        become a live park, because a live park's answer will be written under it and no
        second route may take it while it can still be claimed; the park's own claim or
        eviction is what releases it (:meth:`_claim_routed_park`,
        :meth:`_evict_expired_routes`).

        "A reservation that could leak would exhaust the retry budget for every later
        route, which is the ceiling's own failure mode arriving through the identity
        instead of the slot."

        Args:
            reservation: What this route reserved.
            identity: Whether to release the ``route_id`` as well — ``False`` on the one
                path that ends in a live park.
        """
        if identity:
            self._reserved_routes.discard(reservation.route_id)
        if reservation.handle is not None:
            self._reserved.discard(reservation.handle)

    def _evict_expired_routes(self) -> None:
        """Drop every routed park past its lifetime, releasing its slot (ADR-0197 §7).

        **Opportunistic housekeeping and never the thing that makes an expired park
        unusable.** That is :meth:`_claim_routed_park`'s check, inside the claim and under
        the same lock; this only reclaims slots earlier, when capacity is sought and when
        ``pending_confirmations`` runs its existing reconciliation. This decision adds no
        scheduler and no background job.

        Synchronous and with no ``await`` in it, so it composes with
        :meth:`_admit_and_reserve`'s own atomicity rather than opening a window inside it.
        """
        now = self._now()
        expired = [
            handle
            for handle, park in self._routed_parks.items()
            if now - park.registered_at >= self._routed_ttl
        ]
        for handle in expired:
            park = self._routed_parks.pop(handle)
            self._reserved_routes.discard(park.route_id)

    async def _answer_routed_park(
        self, token: ContinuationToken, *, approved: bool
    ) -> tuple[_RoutedPark, RoutedOperation] | None:
        """Claim the routed park ``token`` names and resolve it, in one critical section.

        Runs under ``_recovery_lock``, the same lock the engine's existing park resolution
        runs under, and **the claim is what evicts it**: the entry is removed before §9's
        row is written, before the operation is called, and before anything is composed. A
        second ``resume`` presenting the same token — concurrent or later, and whatever its
        ``approved`` value — resolves nothing and raises ``UnknownContinuationError``, so
        one park yields one answer, one row pair and at most one operation.

        **Expiry is checked inside the claim**, under the same lock and before the token
        resolves anything, so a park past its lifetime raises whether or not any capacity
        has been sought and whether or not ``pending_confirmations`` has run since.

        **The claim, the row, the operation and the identity's release are one critical
        section**, which is ADR-0197 §9's clause read literally: a confirm-owed route
        "holds its reservation for exactly as long as the park is live, and releases it in
        the same critical section that claims or evicts the park". Releasing it *within*
        the claim's own few statements and then writing the answer outside them would put
        the release in that section and the park's answer outside it — and a repeating id
        factory reaches the gap: a second route mints the same id, registers its own
        ``OWED`` row, and the approved park's ``GIVEN`` then collides with a row about a
        different subject and returns ``UNRECORDED``, spending the user's yes on nothing.
        §9 forbids exactly that outcome in terms — "a pruned row costs history and **never
        costs a resolution**" — so the section is the one that ends when the route does.
        A collision is then caught where §9 puts every other one, at the reserve rather
        than at the store, because at a small ``routing_trail_max_rows`` the retained rows
        are not a census of live routes.

        **What stays outside is the composing call**, exactly as it does for a parked step
        (:meth:`_resolve_park`): a resolution is human-paced and serialising it costs
        nothing that matters, while an arbitrarily slow provider held here would stand
        between a second, unrelated ``resume`` and its own park.

        Args:
            token: The continuation the adapter relayed back.
            approved: The human's answer.

        Returns:
            The park and what became of it, or ``None`` where this token names no routed
            park at all — the ordinary case for a token naming a parked *step*, and why
            this answers rather than raising.

        Raises:
            UnknownContinuationError: If the token names a routed park whose lifetime has
                elapsed. The entry is evicted and its slot released on the way out, as
                ADR-0084 §7 requires of every unresolvable token: never a denial.
        """
        async with self._recovery_lock:
            park = self._routed_parks.get(token.handle)
            if park is None:
                return None
            self._routed_parks.pop(token.handle, None)
            if self._now() - park.registered_at >= self._routed_ttl:
                # An **evicted** park releases its identity here: no answer is coming, so
                # nothing will be written under it and the next route may have it.
                self._reserved_routes.discard(park.route_id)
                msg = (
                    "this token names a routed confirmation that has expired; nothing has "
                    "happened yet — the operation was never performed — so ask for it again "
                    "rather than resuming this token"
                )
                raise UnknownContinuationError(msg)
            return park, await self._resume_routed(park, approved=approved)

    async def _resume_routed(self, park: _RoutedPark, *, approved: bool) -> RoutedOperation:
        """Record the answer and perform what it authorised, still under the lock (§7, §9).

        **The refusal is returned, never raised.** ``approved`` ``False`` yields
        ``RouteOutcome.REFUSED`` and **no** ``PermissionDeniedError``, because no
        ``ActionPolicy`` was consulted and no ``PermissionDecision`` recorded — so there is
        no ruling for a refusal to be, and a refusal is a ``REFUSED`` row rather than an
        exception. That is ADR-0197 §13's partial supersession of ADR-0042 §4, scoped to
        exactly this case: a ``resume`` continuing a parked *step* still raises.

        **The route's identity is released here, in a ``finally``**, once the answer has
        landed or failed to — inside :meth:`_answer_routed_park`'s critical section, which
        is where §9 puts it. Until then no second route may mint this id, which is what
        stops a repeating factory registering an ``OWED`` row that the approved park's
        ``GIVEN`` then collides with, the failure §9 forbids when it rules that a pruned
        row "never costs a resolution".

        **A row whose write fails ends in** ``UNRECORDED`` **with the park already
        claimed**, because §9 orders the write before the effect and §7 orders the claim
        before the write. The token is spent, the slot released, and nothing performed. The
        remedy is this section's own sentence: nothing has happened yet, and the operation
        is asked for again rather than resumed again — a surface that told the user to
        retry the token would be telling them to present one that now raises
        ``UnknownContinuationError``.
        """
        approval = RouteApproval.GIVEN if approved else RouteApproval.REFUSED
        try:
            if not await self._record_route(
                park.route_id,
                operation=park.operation,
                approval=approval,
                subject=park.argument,
                conversation_id=park.conversation_id,
            ):
                routed = RoutedOperation(operation=park.operation, outcome=RouteOutcome.UNRECORDED)
            elif not approved:
                routed = RoutedOperation(operation=park.operation, outcome=RouteOutcome.REFUSED)
            else:
                routed = await self._perform_route(park.operation, argument=park.argument)
        finally:
            # The identity the claim kept, given back once the answer has been written —
            # or once writing it has failed, which is equally the end of this route. Held
            # across the await above and released on every path out of it, including a
            # cancellation: an identity that could leak would exhaust the retry budget for
            # every later route (ADR-0197 §9).
            self._reserved_routes.discard(park.route_id)
        return routed

    async def _compose_and_capture_routed(
        self, park: _RoutedPark, routed: RoutedOperation
    ) -> TurnOutcome:
        """Compose the answered park's reply and capture it, outside the lock (§10).

        A resumption is captured as **its own episode** in the conversation that parked,
        and its content carries no part of the routed account — not the listing, not the
        display subject, not the scalar argument (ADR-0197 §10). The conversation is the
        park's own, recovered from the entry rather than passed by the adapter: a
        ``resume`` is handed an opaque token and nothing else.
        """
        composed = await self._composing.compose_routed(
            operation=routed.operation, outcome=routed.outcome
        )
        return await self._capture(
            park.conversation_id,
            turn=None,
            step=None,
            resumed=True,
            composed=composed,
            routed=routed,
            # ADR-0225 §1's third case: this pass received no user words at all — it
            # is handed an opaque token and a boolean — so the entry carries none.
            asked=None,
            # ADR-0204 §2's fifth clause: a pass that carries no turn carries
            # ``False``, and it is true of this episode rather than a default — its
            # content holds no goal statement and no plan rationale of any turn.
            supplied_withheld=False,
            # ADR-0221 §5's third case, at the site §12 names and drawn over the same
            # partition: this episode "carries neither a turn nor an utterance and
            # renders the bare fact of the resumption alone", so `TEXT` is true of
            # what it holds rather than a default it falls back on. It is `TEXT` even
            # where the pass that *parked* was spoken — the modality belongs to the
            # material the episode renders, and this one renders none.
            modality=Modality.TEXT,
            # ADR-0223 §3's third case, at the same site and over ADR-0204 §2's own
            # partition: the pass that parked was **routed**, so it reached no
            # retrieval and no planner and selected nothing for the predicate to find,
            # and this pass retrieves nothing of its own. There is no turn to retain a
            # value from, so `False` is a fact about what this episode holds rather
            # than a default it falls back on — stated in code exactly as
            # `origin.NOTHING_EXTERNAL` has a caller state it.
            derived_from_external=False,
        )

    async def _finish_route(
        self,
        conversation: str,
        utterance: str,
        routed: RoutedOperation,
        *,
        compose: _RoutedComposer | None,
        spoken: _SpokenCapture | None = None,
    ) -> TurnOutcome:
        """Compose what the pass owes, then capture the exchange (ADR-0197 §10).

        ``compose`` is ``None`` on a routed park, which owes no answer: the composing stage
        is not reached, originates no model call, and ``reply_degraded`` stays ``False``.

        ``spoken`` is carried for the same reason every other capture site carries it:
        a routed pass on ``converse_spoken`` is a turn of that operation, so ADR-0205
        §4's "unconditionally on that operation" reaches it, and the episode id it
        allocates is the one the caller is disclosed.
        """
        composed = None if compose is None else await compose(routed, conversation)
        return await self._capture(
            conversation,
            turn=None,
            step=None,
            resumed=False,
            composed=composed,
            routed=routed,
            utterance=utterance,
            spoken=spoken,
            # ADR-0225 §1's second case: a routed pass threads its utterance, which
            # is the user's own words for an episode that has no turn to read them
            # off (ADR-0197 §10).
            asked=utterance,
            # ADR-0221 §5's first case: this episode renders the utterance this pass
            # threads to the capture point, so the value is this pass's own —
            # `SPEECH` "whether or not that pass routed", which is what makes a routed
            # pass of `converse_spoken` record a transcript as one.
            modality=Modality.TEXT if spoken is None else Modality.SPEECH,
            # A routed pass reaches no retrieval and no planner, so there is no
            # supply for the predicate to find and nothing in the episode for a
            # stamp to be about (ADR-0204 §2's fifth clause).
            supplied_withheld=False,
            # ADR-0223 §3's third case, and the one site where its partition
            # **differs from ADR-0221 §5's deliberately**. `modality` above is this
            # pass's own, because a routed pass does have user material — the
            # utterance it threads to the capture point. This field is not about the
            # user material: it is about *the supply the turn ran over*, which is what
            # `supplied_withheld` is about, and a routed pass has none. So the routed
            # pass sits in the third case here and in the first case there, and the
            # two partitions are not one table.
            derived_from_external=False,
        )

    async def _composed_routed_whole(
        self, routed: RoutedOperation, conversation: str
    ) -> ComposedReply | None:
        """Compose a routed answer atomically, ignoring the room its streaming twin needs.

        ``conversation`` is what :meth:`_compose_routed_streaming` measures its ceiling
        against; the whole-answer path has no ceiling of its own — ADR-0170 §8 makes an
        over-ceiling answer a refusal, because nothing has been published — so it is
        accepted and dropped, exactly as :meth:`_composed_whole` does.

        **Only the two enum values reach the stage** (ADR-0197 §6): the listing this
        method is handed is what the *outcome* will carry, and it goes no further than
        here.
        """
        del conversation
        return await self._composing.compose_routed(
            operation=routed.operation, outcome=routed.outcome
        )

    async def _composed_routed_spoken(
        self, routed: RoutedOperation, conversation: str
    ) -> ComposedReply | None:
        """Compose a routed answer for a channel of unbounded audience (ADR-0200 §7).

        :meth:`_composed_routed_whole` with the audience told, and with nothing else
        different. A routed reply on a spoken turn is **spoken aloud** exactly as an
        ordinary one is, so ADR-0200 §7's clause — the composing stage is told the
        audience of the channel the answer is bound for — reaches this composition
        too; a path that skipped it would have the hub composing for a screen while
        the answer went to a loudspeaker, which is the one thing §2 says the gateway
        must not be allowed to cause and no less wrong for being caused here.

        **Nothing is withheld on this path and nothing is deflected.** ADR-0197 §6
        gives this stage two closed vocabularies this system owns, so ADR-0199 §3
        has no content to place and §5 has no withholding to shape. Telling the
        stage the audience is not the third *value* §6 forbids: that section's
        enumeration is about the routed result's data — "no query, no resolved
        argument, no candidate, no record, no listing and no count" — and its third
        clause forbids "rendering a routed result into text and supplying that text
        to a model". A statement about the channel is neither.

        Args:
            routed: What the routing stage did.
            conversation: Accepted and dropped, as :meth:`_composed_routed_whole`
                drops it.

        Returns:
            What the stage composed.
        """
        del conversation
        return await self._composing.compose_routed(
            operation=routed.operation, outcome=routed.outcome, unbounded_audience=True
        )

    async def _compose_routed_streaming(
        self,
        routed: RoutedOperation,
        conversation: str,
        chunks: asyncio.Queue[ReplyChunk],
    ) -> ComposedReply | None:
        """Stream a routed answer onto ``chunks`` (ADR-0173, ADR-0197 §10).

        The routed twin of :meth:`_compose_streaming`, measuring its ceiling against the
        outcome this pass will actually build — which carries ``routed`` and no ``turn``,
        so the room is genuinely different from a step-driving turn's.

        **The stage is still handed two enum values and nothing else** (ADR-0197 §6). The
        whole account arrives here because ADR-0173 §3's ceiling is measured against the
        terminal outcome, listing included; it reaches the room calculation and stops.

        Raises:
            RuntimeError: If the stage ended without reporting, which is a defect in it
                rather than a composition failure (ADR-0170 §8).
        """
        composed: ComposedReply | None = None
        stream = self._composing.compose_routed_streaming(
            operation=routed.operation,
            outcome=routed.outcome,
            room=self._routed_reply_room(routed, conversation_id=conversation),
        )
        async with closing_stream(stream) as composing:
            async for produced in composing:
                if isinstance(produced, ReplyChunk):
                    check_payload(
                        produced,
                        max_bytes=self._max_payload_bytes,
                        subject="a chunk of the reply to converse_streaming()",
                    )
                    chunks.put_nowait(produced)
                else:
                    composed = produced
        if composed is None:  # pragma: no cover — the stage always reports last
            msg = "the composing stage ended without reporting what it composed"
            raise RuntimeError(msg)
        return composed

    def _routed_reply_room(self, routed: RoutedOperation, *, conversation_id: str) -> int:
        """How many escaped bytes a routed outcome has left for its reply (ADR-0173 §3).

        :meth:`_reply_room`'s routed twin, measured rather than reused because the two
        outcomes differ in what they carry: this one has no ``turn`` at all and a
        ``routed`` member whose listing may be a page of the user's own records.

        **The probe carries the whole routed account, listing included**, and that is
        load-bearing rather than tidiness. ADR-0173 §3's reserve is computable only
        because the outcome's non-reply content is *settled* before composition begins,
        and on a routed pass it is: the operation has already run. A probe that omitted
        the listing would subtract less than the terminal frame will and so report **more**
        room than there is — the one direction that publishes a chunk the terminal frame
        then refuses, which is what §3's arithmetic exists to prevent.

        Both booleans are probed at their longer spelling, ``false`` being five bytes
        against ``true``'s four, for :meth:`_reply_room`'s reason exactly: capture has not
        run and the answer has not finished, and taking the longer one can only
        under-state the room.
        """
        probe = TurnOutcome(
            turn=None,
            conversation_id=conversation_id,
            capture_degraded=False,
            reply=_ROOM_PROBE,
            reply_degraded=False,
            routed=routed,
        )
        fixed = len(canonical_payload(probe)) - encoded_text_bytes(_ROOM_PROBE)
        return self._max_payload_bytes - fixed - JSON_STRING_QUOTE_BYTES

    def _routed_surface(self) -> _RoutedSurface:
        """The engine's own operations, as ADR-0197 §2's third clause reaches them.

        A thin adapter rather than ``self``, for one reason: ``AssistantEngine.beliefs``
        answers ``BeliefSummary`` rows and §5's ``forget`` lookup needs ``Belief`` records,
        which is the arm §8 gives that operation. Every other member relays the engine's
        own façade method untouched, so a routed ``forget`` and a typed-door ``forget``
        are one implementation behind one set of preconditions — which is what §2's third
        clause exists to keep true.
        """
        return _RoutedSurface(self)

    async def _routed_beliefs(self, *, limit: int, offset: int) -> tuple[Belief, ...]:
        """Enumerate live beliefs as §8's ``forget`` arm, for §5's lookup only.

        Reads the store ``forget`` itself reads (ADR-0197 §5), **enumerating the kinds
        ADR-0201 §1 names** rather than every kind, and projects each record exactly as
        :meth:`belief` does, so the candidate a card renders is the same value a user
        would have seen through the typed door. It is **not** a routable operation and
        reaches no surface: ``beliefs`` is deliberately outside §3's vocabulary, because
        "what do you know about me?" is milestone 17's ruled exit test and routing it
        would replace a ruled behaviour with a worse one.

        :data:`~ai_assistant.orchestration.routing.FORGET_LOOKUP_KINDS` is where the
        derivation and its reasons live, beside the lookup it is for. It is passed to the
        store rather than applied to what comes back, so the filter binds before the page
        cut (ADR-0073 §2) and an excluded record is never read here, never projected
        through :meth:`_project` — one ``get_many`` per record — and never discarded after
        the fact (ADR-0201 §3). Nothing about what :meth:`forget` destroys moves: it still
        relays ``MemoryStore.delete`` and still destroys an episodic record by id
        (ADR-0201 §2).
        """
        records = await self._memory.list_beliefs(
            bands=None, kinds=FORGET_LOOKUP_KINDS, limit=limit, offset=offset
        )
        return tuple([await self._project(record) for record in records])

    async def _compose(
        self,
        turn: TurnResult | None,
        step: StepOutcome | None,
        *,
        deliveries: Mapping[str, SpokenDelivery],
        hop_reached: Sequence[str] = (),
        stopped_while_asking: bool = False,
    ) -> ComposedReply | None:
        """Compose this pass's answer, or decline to on the shapes that owe none.

        ADR-0170 §4 gives ``reply`` three ``None`` shapes and §8 says what each
        costs. Two of them are decided **here, before the stage is reached**, so no
        prompt is assembled and no model is called on either — which is what keeps
        ``reply_degraded`` ``False`` there rather than leaving it to a stage that
        would have to know not to answer:

        - a pass whose step parked for confirmation, where what the user must answer
          is the ``Confirmation`` the adapter renders and relays. A second,
          model-written account of the same pending action beside it is where the
          two can disagree, and the resume that follows composes in the ordinary way
          (ADR-0170 §4).
        - a pass with no ``turn`` — a resume driven from a **recovered** park
          (ADR-0052 §3) — where context and memories were never persisted and there
          is nothing to compose from.

        The third shape, a composition that *failed*, is the stage's own report and
        arrives as a :class:`~ai_assistant.orchestration.composing.ComposedReply`
        with ``degraded`` set.

        **The undriven steps are computed here and handed over** (ADR-0170 §5): the
        stage is told which of the plan's steps were not driven rather than handed
        the plan alone and left to infer it. Until the plan-driving stage lands
        (#242) that is every step but the one this pass drove — of the plan the turn
        finally produced, which on a revising turn is the revision and never the plan
        it replaced (ADR-0228 §5: a superseded plan drives nothing, so none of its
        steps is undriven in this sense; it was never a candidate).

        **ADR-0228 §10's fact defaults to ``False``**, which is what a resume driven
        from a recovered park carries: nothing about that pass planned at all, so it
        stopped at no guard. Every ordinary pass is told the turn's own value.

        Returns:
            What the stage composed, or ``None`` where no answer was owed.
        """
        if turn is None or (step is not None and step.confirmation is not None):
            return None
        undriven = (
            () if step is None else tuple(one for one in turn.plan.steps if one.id != step.step_id)
        )
        return await self._composing.compose(
            turn=turn,
            step=step,
            undriven=undriven,
            deliveries=deliveries,
            hop_reached=hop_reached,
            stopped_while_asking=stopped_while_asking,
        )

    async def _compose_streaming(  # noqa: PLR0913 — the turn, the step, the conversation, the chunk queue, the delivery facts, the hop's reach and ADR-0228 §10's stop fact; each is a distinct input, as on :meth:`_compose`
        self,
        turn: TurnResult | None,
        step: StepOutcome | None,
        conversation_id: str,
        chunks: asyncio.Queue[ReplyChunk],
        deliveries: Mapping[str, SpokenDelivery],
        hop_reached: Sequence[str] = (),
        stopped_while_asking: bool = False,
    ) -> ComposedReply | None:
        """Stream this pass's answer onto ``chunks``, and report what it composed.

        The streaming twin of :meth:`_compose`, and it declines on **exactly** the
        same two shapes for exactly the same reasons — a park, and a pass with no
        turn — so a streaming call and a whole one owe an answer on precisely the
        same passes and a client cannot tell the two apart by which shapes fall
        silent. Zero chunks then, and the terminal outcome alone (ADR-0173 §4).

        **Every chunk is measured before it is published** (ADR-0173 §11's restating
        of ADR-0085 §8c): the limit is enforced on each value before the frame
        carrying it is written, in place of "on results before return", which a
        method returning an iterator has no single point to satisfy.

        **The stage's iterator is closed rather than merely exhausted.** The ceiling
        makes stopping part-way ordinary rather than exotic — the stage breaks out
        of its own read the moment the next chunk would breach — and
        :func:`contextlib.aclosing` is what releases the provider exchange
        underneath it (ADR-0060, ``StreamingCompleter``'s own clause).

        Returns:
            What the stage composed, or ``None`` where no answer was owed.

        Raises:
            RuntimeError: If the stage ended without reporting, which is a defect in
                it rather than a composition failure — and ADR-0170 §8's closed
                degradation set is why it is raised rather than reported as one.
        """
        if turn is None or (step is not None and step.confirmation is not None):
            return None
        undriven = (
            () if step is None else tuple(one for one in turn.plan.steps if one.id != step.step_id)
        )
        composed: ComposedReply | None = None
        stream = self._composing.compose_streaming(
            turn=turn,
            step=step,
            undriven=undriven,
            room=self._reply_room(turn=turn, step=step, conversation_id=conversation_id),
            deliveries=deliveries,
            hop_reached=hop_reached,
            stopped_while_asking=stopped_while_asking,
        )
        async with closing_stream(stream) as composing:
            async for produced in composing:
                if isinstance(produced, ReplyChunk):
                    check_payload(
                        produced,
                        max_bytes=self._max_payload_bytes,
                        subject="a chunk of the reply to converse_streaming()",
                    )
                    chunks.put_nowait(produced)
                else:
                    composed = produced
        if composed is None:  # pragma: no cover — the stage always reports last
            msg = "the composing stage ended without reporting what it composed"
            raise RuntimeError(msg)
        return composed

    def _reply_room(
        self, *, turn: TurnResult, step: StepOutcome | None, conversation_id: str
    ) -> int:
        """How many escaped bytes the terminal outcome has left for its reply (§3).

        **The reserve is computable, which is what makes ADR-0173 §3's clause an
        obligation rather than a wish.** A ``TurnOutcome``'s non-reply content is
        fixed before composition begins — its ``turn``, ``step``, ``plan`` and
        ``memories`` are all settled by the time this stage is reached (ADR-0170 §2)
        — and the two members capture supplies are an ``Identifier`` this method is
        handed and a ``bool``. So the room is measured here rather than guessed at
        as a fraction of the frame size.

        **Measured by encoding the outcome that will be built, less the probe reply
        it stands in for.** What is left is everything but the reply's own
        characters, so a reply whose escaped body fits in the difference produces a
        payload inside the limit — exactly, because ADR-0087 §2's encoding escapes a
        string character by character and is therefore additive over concatenation.

        **Both booleans are probed at their longer spelling**, ``false`` being five
        bytes against ``true``'s four. Capture has not run yet and the answer has not
        finished, so neither is known; taking the longer one can only under-state the
        room, which stops a stream a byte or two early and can never publish text the
        terminal frame would then refuse.

        Args:
            turn: The turn the outcome will carry.
            step: The step it will carry, or ``None``.
            conversation_id: The conversation it will name — the one
                ``ConversationLifecycle.capture`` reports back for this turn.

        Returns:
            The escaped byte budget for the reply. Zero or negative means no chunk
            fits at all, which the stage reports as the pre-commit degradation and
            which leaves an answerless outcome to be measured on its own way out
            (ADR-0173 §3's third case, ``OversizedValueError`` as on ``converse``).
        """
        probe = TurnOutcome(
            turn=turn,
            step=step,
            conversation_id=conversation_id,
            capture_degraded=False,
            reply=_ROOM_PROBE,
            reply_degraded=False,
        )
        fixed = len(canonical_payload(probe)) - encoded_text_bytes(_ROOM_PROBE)
        return self._max_payload_bytes - fixed - JSON_STRING_QUOTE_BYTES

    def _check_plan_is_for_goal(self, turn: TurnResult) -> None:
        """Refuse a plan that was not built for this turn's goal (ADR-0037 §2 in spirit).

        The pipeline reads its subjects from the store, not the caller's word, so a
        substituted subject is refused rather than checked for. Here the façade is
        the caller of the store, so it makes the one check no lower stage can: a
        conforming ``Planner`` returns a plan for the goal it was handed
        (``plan.goal_id == goal.id``), but a faulty or stale one could return an
        *already persisted* plan for a **previous** goal — which ``save_plan``
        would accept (its goal exists) and ``start_execution`` would then drive,
        executing actions planned for a different objective than the utterance.

        Raises:
            PlanningError: If the plan's ``goal_id`` is not this turn's goal.
        """
        if turn.plan.goal_id != turn.goal.id:
            msg = (
                f"the planner returned a plan for goal {turn.plan.goal_id!r}, not this turn's "
                f"goal {turn.goal.id!r}; driving it would execute actions planned for a "
                "different objective"
            )
            raise PlanningError(msg)

    async def _resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        remember_recipients_until: UtcInstant | None = None,
    ) -> TurnOutcome:
        """Reload the parked execution and continue its step.

        **The critical section is the resolution and nothing after it.**
        :meth:`_resolve_park` runs under ``_recovery_lock`` so a resolution is
        mutually exclusive with a recovery enumeration; composing the answer and
        capturing the exchange run outside it, over a resolved step no other caller
        can still reach. Holding the lock across the composing model call would put
        an arbitrarily slow provider — one exhausting ADR-0011 §2's retry budget, say
        — between a second, unrelated ``resume`` and its own park, and between
        ``pending_confirmations`` and a listing that needs no model at all. Capture
        runs outside it for the same reason and on ``converse``'s own precedent,
        which captures under no lock whatever.

        **A restatement ends inside the critical section and returns from here**
        (ADR-0198 §§1-3). Where the token names a settled record rather than a park,
        :meth:`_resolve_park` answers ``None`` in place of the parked entry and the
        method returns the restated step alone: nothing is composed, because the
        answer was composed once for the request that performed the act, and nothing
        is captured, because a restatement is not an exchange and a second episode
        under one answer is a binding ADR-0074 §3 cannot describe.

        **A routed park is answered first, and the whole of its resolution is under the
        same lock** (ADR-0197 §7, §9). :meth:`_answer_routed_park` answers ``None`` where
        the token names no routed park at all, which is the ordinary case for a token
        naming a parked step, so the two kinds of park share one method and one token space
        without either knowing about the other. Composing and capturing run outside it, on
        the step path's own reasoning: an arbitrarily slow provider must not stand between
        a second, unrelated ``resume`` and its own park.

        A routed park that resolves differs from a step's in exactly three respects and in
        no others: its outcome carries ``step`` ``None`` and ``routed``
        non-``None``, its refusal is returned as ``RouteOutcome.REFUSED`` rather than raised
        as a ``PermissionDeniedError``, and its ``turn`` is ``None`` for ADR-0197 §8's
        reason rather than ADR-0052 §3's.
        """
        if (
            remember_recipients_until is not None
            and approved
            and token.handle in self._routed_parks
        ):
            # **A routed park carries no egress confirmation to ride** (ADR-0235 §2).
            # It records no `PermissionDecision` at all — ADR-0197 §7 rules that a
            # routed refusal is returned rather than ruled on — so there is nothing
            # for `RecipientGrant.established_from` to transcribe an account and a
            # destination set from. Refused **before** the park is claimed, which is
            # what leaves the operation askable again: `_answer_routed_park` claims
            # atomically and a claimed routed park is never re-minted.
            msg = (
                "this token names a routed operation rather than a confirmation about an "
                "outbound call, so answering it establishes no standing recipient grant; "
                "nothing was claimed and the operation may be asked for again (ADR-0235 §2)"
            )
            raise UngrantableActError(msg)
        answered = await self._answer_routed_park(token, approved=approved)
        if answered is not None:
            park, routed = answered
            return await self._compose_and_capture_routed(park, routed)
        parked, step, establishing = await self._resolve_park(
            token,
            approved=approved,
            timeout=timeout,
            remember_recipients_until=remember_recipients_until,
        )
        if parked is None:
            # A **restatement** (ADR-0198 §§1-3), and it ends here rather than
            # continuing down this method: it composes nothing — the answer was
            # composed once, for the request that performed the act, and a second
            # model call would hold this caller behind a provider to produce prose
            # differing from what the first caller read for reasons no user could
            # account for — and it captures nothing, because it is not an exchange
            # and a second episode under one answer is a binding ADR-0074 §3 cannot
            # describe. ``turn`` ``None`` beside ``reply`` ``None`` and
            # ``reply_degraded`` ``False`` is ADR-0170 §4's second shape exactly.
            return TurnOutcome(turn=None, step=step)
        # **No delivery facts on this path, and none is fetched to make some**
        # (ADR-0205 §5). The facts ride the replay tail
        # ``ConversationLifecycle.history`` reads, and a resume reads none: it is
        # handed the parked turn's own ``TurnResult``, recovered rather than
        # reassembled, and §5 adds no second store call to any path. So this stage is
        # told nothing about delivery, which is not the same as being told the tail
        # was heard — the renderer writes a line only where it has a fact, and asserts
        # nothing where it has none.
        # **And no hop reach either, for the same reason** (ADR-0227 §3). A resume
        # runs no planner, emits no request and services no read, so there is nothing
        # this turn's citation hop reached; the parked ``TurnResult`` is recovered
        # rather than reassembled, and §3's carrier is empty on every turn that did
        # not fire.
        # **The act is performed after the answer was recorded and the call executed**
        # (ADR-0235 §6), and everything it can do is reported on the carrier rather
        # than raised: by the time `record` is asked the egress has gone out, so a
        # raise would report a failure for a call nobody can un-send while discarding
        # the outcome the surface needs in order to say what that call did.
        recipient_grant = await self._establish_recipients(
            establishing, approved=approved, remember_recipients_until=remember_recipients_until
        )
        composed = await self._compose(parked.turn, step, deliveries={})
        return await self._capture_resumption(
            parked, step, composed, recipient_grant=recipient_grant
        )

    async def _establish_recipients(
        self,
        establishing: EstablishingAnswer | None,
        *,
        approved: bool,
        remember_recipients_until: UtcInstant | None,
    ) -> RecipientGrantOutcome | None:
        """Say what became of a standing request, or that none was collected.

        Three states and no fourth (ADR-0235 §4, §6). No act collected — every
        ``resume`` supplying no ``remember_recipients_until`` — carries ``None``, and
        a surface then says nothing about standing grants at all. An act collected
        beside a declining answer carries ``DECLINED``: the ``DENY`` is recorded
        exactly as it is today and the store is never reached. An act collected
        beside an approving answer carries whatever the store did.

        ``establishing`` is ``None`` on one further path the runner reaches without
        recording an answer — a resumed call whose egress binding could no longer be
        derived (``EGRESS_UNBINDABLE``, ADR-0152 §7). Nothing was ruled on, nothing
        was sent and nothing was recorded there, so there is no outcome of an act to
        report and the carrier stays absent; the disposition the outcome already
        carries is what says what happened.
        """
        if remember_recipients_until is None:
            return None
        if establishing is None:
            return None if approved else self._recipient_grants.declined()
        return await self._recipient_grants.establish_from_answer(
            establishing, expires_at=remember_recipients_until
        )

    async def _resolve_park(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        remember_recipients_until: UtcInstant | None = None,
    ) -> tuple[_Parked | None, StepOutcome, EstablishingAnswer | None]:
        """Record the answer and drive it, or restate an answer already recorded.

        Runs under ``_recovery_lock`` so a resolution is mutually exclusive with a
        recovery enumeration: resolving records the decision through the runner and
        evicts the binding's ``_parked`` entry, both of which recovery reads, so the
        two must not interleave (:meth:`_pending_confirmations`, round 3 review). The
        lock is held across the runner call — the resolve and any execution it drives
        — so recovery cannot observe a binding mid-resolution. Resolutions are
        human-paced, so serializing them behind this one lock is free in practice.

        **The eviction and the settled record are one critical section** (ADR-0198
        §1). The park is replaced by its settled record before this lock is released,
        never after: a window in which the handle names neither would hand a
        concurrent ``resume`` the very ``UnknownContinuationError`` the decision
        exists to stop, and it would open on exactly the race #1621 describes — a
        recovery listing overtaking a resume, the loser told its action was declined
        for an action that ran.

        **A resolution that does not complete installs nothing** (§3). The record is
        written only where the answer was recorded, the runner returned and the park
        was evicted, all three below; a resolution that raised leaves the park where
        it was, and what becomes of it afterwards is what became of it before this
        decision — a direct retry re-enters resolution, and a recovery enumeration
        running in between may reconcile the binding away under ADR-0052 §2.

        **A restatement establishes nothing and consults the argument no more than
        it consults ``approved``** (ADR-0198 §§1-3, ADR-0235 §4). It drives no
        runner, so the two refusals the act owes never arise and no answer is
        recorded for a grant to ride; the third member below is ``None`` there, and
        the outcome carries ``recipient_grant`` ``None``.

        Returns:
            The parked entry this token named, what became of its step, and — on a
            ``resume`` that collected an establishing act and reached a recorded
            answer — the pair that answer's grant is transcribed from (ADR-0235 §2).
            The first is ``None`` beside the restated step where the token named a
            **settled** record, which is what tells :meth:`_resume` to stop: a
            restatement drives no runner, composes nothing and captures nothing.
        """
        async with self._recovery_lock:
            parked = self._parked.get(token.handle)
            if parked is None:
                return None, await self._restate(token), None
            state = await self._plans.get_execution(parked.execution_id)
            if state is None:
                msg = f"the store no longer holds execution {parked.execution_id!r} for this token"
                raise PlanningError(msg)
            disposition = await self._runner.resume(
                state,
                parked.step_id,
                confirmation_id=parked.confirmation_id,
                approved=approved,
                timeout=timeout,
                remember_recipients_until=remember_recipients_until,
            )
            # A resolving disposition is EXECUTED or DENIED, never AWAITING_CONFIRMATION,
            # so no new handle is needed here.
            step = self._step_outcome(parked.turn, disposition, step_id=parked.step_id, handle=None)
            # Answered once, and now **retained** rather than forgotten (ADR-0198 §1).
            # ADR-0044 §2b makes a second resolution impossible anyway; what changes is
            # what the engine says about one. Evicting used to turn a replay into an
            # "unknown token", whose ratified remedy — enumerate and re-mint — is the
            # one remedy a replay cannot use, since ADR-0052 §1 step 2 never lists a
            # settled binding. So the park becomes a settled record in its place.
            self._parked.pop(token.handle, None)
            self._retain(
                token.handle,
                _Settled(
                    execution_id=parked.execution_id,
                    step_id=parked.step_id,
                    tool_id=disposition.tool_id,
                    disposition=disposition.disposition,
                ),
            )
            return parked, step, disposition.establishing

    def _retain(self, handle: str, settled: _Settled) -> None:
        """Record one answered binding under its handle, within §4's bound.

        **The ceiling is ``max_outstanding_confirmations`` and no figure is
        invented** (ADR-0198 §4). The number of answers a client can be uncertain
        about at once is bounded by the number of tokens it can hold at once, and
        that is what this setting already bounds — so the two numbers are one, and a
        deployment that raises the ceiling raises this window in the same breath and
        for the same reason. No new setting scales, extends or disables it.

        **A count, not a lifetime, and no clock is read.** ADR-0197 §7 bounds a
        *live* routed park with a clock because such a park holds a ceiling slot and
        a route identity — scarce resources a park nobody answers would hold forever.
        A settled record holds neither; its only cost is a few fields of memory, a
        count bounds memory exactly, and nothing here makes a token's answerability
        depend on how long a user stared at a page.

        Discarding is **least recently settled**, which this table's insertion order
        already is: a handle settles at most once, and a restatement reads without
        re-inserting, so the oldest key is the oldest settlement. What the bound costs
        is stated rather than hidden — a restatement sought after that many other
        parks have settled meets ``UnknownContinuationError`` again, which is the
        behaviour every replay had before this decision, so the bound narrows the
        improvement and regresses nothing.

        Runs inside :meth:`_resolve_park`'s critical section, with no ``await`` of its
        own, so the eviction and this write cannot be observed apart.
        """
        while len(self._settled) >= self._max_outstanding:
            self._settled.pop(next(iter(self._settled)))
        self._settled[handle] = settled

    async def _restate(self, token: ContinuationToken) -> StepOutcome:
        """Say what a settled binding was decided, or refuse a token naming nothing.

        Called by :meth:`_resolve_park` with ``_recovery_lock`` **held**, and it must
        be: the check that the handle names no park and the read of the settled table
        are one decision, and a concurrent resolution completing between them is
        precisely the race ADR-0198 §1 closes.

        **The call's ``approved`` is not consulted at all** (§1). A park is answered
        once (ADR-0044 §2b), so a second answer is never honourable whatever it says,
        and the recorded answer stands unchanged. The engine could instead retain the
        answer given and refuse a contradicting one with a second typed error; that
        buys a distinct message and costs the surface the fact it came for, since a
        caller handed an error learns that the binding was answered and never learns
        *how*, and the token is opaque so it cannot ask any other way. A caller handed
        the outcome learns both, and the disagreement is visible to it without a
        second error class.

        **The refusal names both remedies because the engine cannot tell which token
        it holds** (#1649). A handle naming nothing here is one of two things, and by
        this point they are indistinguishable: a step park unknown, aged out or from a
        previous process life, whose remedy is ``pending_confirmations``; or a
        **routed** park already claimed or expired, which ``pending_confirmations``
        never lists and never re-mints (ADR-0197 §7) because "the claim is what evicts
        it". Naming only the first was wrong for half the callers it was given to — a
        double-clicked confirm button and the loser of two concurrent ``resume`` calls
        both land here — so the message now names the routed case too, and the way out
        of it, which is to ask for the operation again rather than to resume this
        token. Telling the two apart instead would mean retaining what §7's claim
        destroys, which is a decision and not a message.

        **What it must not say is that nothing happened.** §7's own sentence — "nothing
        has happened yet, and the operation is asked for again rather than resumed
        again" — is true of a park that was *never answered*, and this branch cannot
        establish that: §9 orders the claim before the row and the row before the
        effect, so a claimed routed token is equally a park that expired unanswered, one
        whose row failed to write, and one whose ``forget`` destroyed the belief a
        moment ago. The expired path can say it and does, because it raises from inside
        the claim with the entry in front of it; here the honest statement is that the
        engine no longer knows, and asking again is what turns not knowing into an
        answer the user reads.

        **``state`` is re-read here and never cached at settlement** (§2). It is
        defined as the durable execution state after the last transition committed,
        and a value snapshotted at settlement stops being that the moment anything
        else advances the execution — ADR-0139 §2's rule, at a second seam. Where the
        store no longer holds the execution, this raises ``PlanningError``, the same
        failure a resolution raises for the same condition, and asserts nothing about
        the outcome: an outcome it cannot read is not one it may state.

        **Nothing is performed, consulted, recorded or captured** (§3). No
        ``StepRunner``, no ``ActionPolicy``, no ``PermissionDecision``, no tool, no
        composed reply and no episode — so a settled binding yields one resolution,
        one ruling, one execution attempt and at most one captured resumption,
        however many times its token is presented. This is ADR-0044 §2b's refusal
        reaching the caller as an answer instead of as an error: the trail's
        single-resolution index would refuse a second resolution anyway, and the
        engine now reports the fact that index is protecting.

        Args:
            token: The continuation presented, whose handle names no park.

        Returns:
            The settled binding's step, carrying the immutable facts the record holds
            and the execution state read now.

        Raises:
            UnknownContinuationError: If the handle names no settled record either —
                unknown, from a previous process life, reconciled away under ADR-0052
                §2, discarded under §4's bound, or a **routed** park already claimed or
                expired (ADR-0197 §7). **Never a denial** (ADR-0084 §7).
            PlanningError: If the plan store no longer holds the settled binding's
                execution.
        """
        settled = self._settled.get(token.handle)
        if settled is None:
            msg = (
                "this token names no step awaiting confirmation in this engine, and no answer "
                "this engine still holds; it may be from an earlier run of the process, or its "
                "answer may have aged out. If it named a routed operation, this engine can no "
                "longer say whether that operation ran: a routed park is evicted the moment it "
                "is claimed, is never listed and is never re-minted, so ask for the operation "
                "again rather than resuming this token, and the answer will say what it finds. "
                "If it named a parked step, pending_confirmations() re-mints a token for any "
                "park that is still answerable"
            )
            raise UnknownContinuationError(msg)
        state = await self._plans.get_execution(settled.execution_id)
        if state is None:
            msg = f"the store no longer holds execution {settled.execution_id!r} for this token"
            raise PlanningError(msg)
        # ``confirmation`` is ``None``, which the type's own validator already requires
        # of a disposition that is not AWAITING_CONFIRMATION — and a settled binding's
        # never is: ADR-0044 §2b makes the resolution unrepeatable.
        return StepOutcome(
            disposition=settled.disposition,
            state=state,
            step_id=settled.step_id,
            tool_id=settled.tool_id,
            confirmation=None,
        )

    async def _capture_resumption(
        self,
        parked: _Parked,
        step: StepOutcome,
        composed: ComposedReply | None,
        *,
        recipient_grant: RecipientGrantOutcome | None = None,
    ) -> TurnOutcome:
        """Record the resolution in the conversation that parked, or say it was not.

        The association is **durable and recovered rather than passed** (ADR-0074
        §3): the parking turn wrote its ``(execution_id, step_id)`` binding into the
        index, and this resolves it back. Nothing resolving is the ratified case,
        not a fault — a park predating capture, or one whose conversation the user
        deleted — and the answer is that the resumption is not captured and no
        conversation is invented for it.

        A resumption is not an activity mark: ``mark_active`` belongs to a turn that
        *begins* against a named conversation (§2), and a resume is handed a token
        rather than an id. The parked turn's own episode is still live, so a reclaim
        cannot drop the conversation underneath it.
        """
        binding = ParkedBinding(execution_id=parked.execution_id, step_id=parked.step_id)
        try:
            origin = await self._conversations.conversation_of_binding(binding)
        except ConversationStoreError:
            _log.warning("conversation_binding_unresolved", exc_info=True)
            origin = None
        if origin is None:
            return TurnOutcome(
                turn=parked.turn,
                step=step,
                capture_degraded=True,
                reply=None if composed is None else composed.text,
                reply_degraded=composed is not None and composed.degraded,
                recipient_grant=recipient_grant,
            )
        return await self._capture(
            origin.conversation_id,
            turn=parked.turn,
            step=step,
            resumed=True,
            composed=composed,
            # **The act's outcome is carried, never re-derived** (ADR-0235 §6). It is
            # a fact about the act this pass performed and nothing about the capture
            # touches it: an episode that failed to write leaves the standing outcome
            # exactly as true as it was, which is why it rides both return paths here.
            recipient_grant=recipient_grant,
            # **No user words**, and this is ADR-0225 §1's own clause rather than an
            # absence of data: the parked turn is right here, and its utterance was
            # archived at its own address by the pass that parked. Repeating it here
            # would render one sentence as though the user had said it twice. The
            # asymmetry with `modality` and `supplied_withheld` just below is
            # deliberate — those are *retained* from the parked turn and applied
            # unchanged, because they describe the rendering this episode carries;
            # this field describes what the user said on *this* pass, and they said
            # nothing.
            asked=None,
            # The **parking turn's** value, not this pass's (ADR-0204 §2's fourth
            # clause). This pass retrieves nothing and evaluates nothing; the episode
            # it captures renders the parked turn's goal and plan, so what it is
            # stamped with is that turn's own evaluation, applied unchanged.
            supplied_withheld=parked.supplied_withheld,
            # And the parking turn's modality, on ADR-0221 §5's second case, which is
            # that same clause applied to a second field: the value is "retained with
            # the parked turn and applied unchanged. No implementation re-evaluates,
            # recomputes or defaults it at the second capture". A recovered park
            # retained `TEXT`, which is §5's third case and true of an episode that
            # renders no user material at all.
            modality=parked.modality,
            # And the parking turn's origin mark, on ADR-0223 §3's second case, which
            # is ADR-0204 §2's fourth clause applied to a third field for that
            # clause's own reason. Recomputing it here would evaluate the empty supply
            # of a pass that retrieves nothing and answer `False` about a rendering
            # the parked turn's supply produced — the laundering ADR-0181 §4 forbids,
            # arrived at through a park instead of a re-plan. A recovered park
            # retained `False`, which is §3's third case and true of an episode that
            # renders no turn's goal statement and no turn's plan rationale.
            derived_from_external=parked.derived_from_external,
        )

    async def _capture(  # noqa: PLR0913 — the capture point's five inputs plus the parked binding, the routed account, the utterance a routed pass has no turn to carry, the user's own words the transcript archive keeps, the turn's disclosure evaluation, its origin mark and its spoken capture; every one is a distinct fact about the pass
        self,
        conversation_id: str,
        *,
        turn: TurnResult | None,
        step: StepOutcome | None,
        resumed: bool,
        composed: ComposedReply | None,
        asked: str | None,
        supplied_withheld: bool,
        modality: Modality,
        derived_from_external: bool,
        parked: ParkedBinding | None = None,
        routed: RoutedOperation | None = None,
        utterance: str | None = None,
        spoken: _SpokenCapture | None = None,
        recipient_grant: RecipientGrantOutcome | None = None,
    ) -> TurnOutcome:
        """Record the exchange and fold what became of it into the outcome (§3, §9).

        The capture point is where a ``TurnOutcome`` is produced, which is both
        ``converse`` and ``resume`` (ADR-0042 §3's "one result out"). So a turn that
        parks for confirmation is captured **when it parks** — the alternative,
        holding the episode open until the park resolves, would make the record of
        an exchange depend on a confirmation the user may never answer, so an
        abandoned park would erase the question they actually asked.

        ``composed`` is what the composing stage produced for this pass, or ``None``
        where no answer was owed (:meth:`_compose`). **It reaches the captured
        episode's ``outcome``, whole** (ADR-0221 §1), which is what ADR-0170 §9
        deferred to ``track:memory`` (#1314) and what ADR-0221 decides. No prefix, no
        summary, no elision: an assertion's meaning depends on its ending, and a store
        that half-keeps one holds a record worse than no record.

        ``outcome`` is ``None`` on exactly the five paths that produced no reply, and
        this method computes none of them — it writes what ``composed`` carries.
        ``composed`` is itself ``None`` on three (a step parked for confirmation, a
        routed park, and a resume driven from a recovered park) and carries a ``text``
        of ``None`` on two more (a classified composition failure, the blank
        completion included, and a stream that published nothing before it stopped).
        **A stream that stopped after publishing stores what it published**, on the
        ceiling stop and on a mid-stream ``ModelError`` alike: that text is the whole
        of what the assistant said rather than a prefix of something longer, because
        no continuation of it was ever composed. Whether the pass completed is
        ``reply_degraded``'s to report and is reported there; §1 adds no field saying
        a stored reply was cut short.

        **What became of the pass goes into ``disposition``, as a member** (ADR-0221
        §2) — :func:`_outcome_of` on a driven or undriven step, :func:`_routed_outcome_of`
        on a routed pass — where until ADR-0221 the phrase for it went into ``outcome``.
        The three render sites produce that phrase from ``disposition``, so no prompt
        moves and the reply reaches no model (§3).

        **A routed pass is captured too, and its content is threaded rather than read off
        a turn it does not have** (ADR-0197 §10). ``utterance`` is that thread: a lane that
        wired routing without it would produce a captured exchange with the user's own
        sentence missing from it, a silent hole in the conversation record visible only to
        the next person to resume that conversation. What the episode carries is the
        utterance and a phrase for the route's outcome, and **no part of the routed
        account** — not the listing, not the display subject, not the scalar argument, and
        not the candidates. That is §6's second sentence made mechanical: a conversation's
        recent turns are retrieved into the next turn's prompt (ADR-0074 §5, ADR-0158 §5),
        so a capture that folded a routed listing into the episode would deliver the routed
        result to a model one turn later, satisfying every same-pass clause of §6 while
        breaking §6.

        **``supplied_withheld`` is a property of the turn whose rendering the
        episode carries, and it is passed at every call site** (ADR-0204 §2, whose
        evaluation ADR-0217 §3 leaves unchanged; what it now narrows is the episode's
        ``placement``). This
        method neither computes nor defaults it: the turn passes its own evaluation, a
        resumption passes the parked turn's, and a routed pass passes ``False`` —
        which is true of what its episode holds rather than a fallback, because
        ``_routed_exchange_of`` renders the utterance and a phrase for the route's
        outcome with no goal statement and no plan rationale of any turn in it.

        **``asked`` is the user's own words, passed at every call site, and this
        method neither computes nor derives it** (ADR-0225 §1) — a fourth field with
        the shape ``supplied_withheld``, ``modality`` and ``derived_from_external``
        already have. It is what the *transcript archive* keeps as the user's half of
        the exchange, and it is threaded rather than read off ``content`` for the
        reason §1 gives: ``content`` is ``_exchange_of``'s rendering, built for the
        observer and for retrieval, and the user's sentence is recoverable from it —
        if at all — only by parsing a prefix this system is free to change.

        Its three cases are ADR-0221 §5's three capture cases and no other partition
        is introduced. :meth:`_run_turn` passes ``turn.goal.statement`` on both its
        branches, because the pass carried a turn; :meth:`_finish_route` passes the
        ``utterance`` it already threads, because a routed pass has user material and
        no turn to read it off; and :meth:`_capture_resumption` and
        :meth:`_compose_and_capture_routed` each pass ``None``. The resumption's
        ``None`` is §1's own clause rather than an absence of data — the parked turn
        *is* in front of that method — because the utterance that parked was archived
        at its own address by the pass that parked, and repeating it would render one
        sentence as though the user had said it twice.

        **``spoken`` decides whether this capture writes a delivery at all** (ADR-0205
        §4). It is present exactly on a turn of ``converse_spoken``, which writes
        ``UNKNOWN`` unconditionally — the park, the ``reply`` of ``None`` and the
        degraded synthesis included, because at capture the hub has produced an answer
        and knows nothing about what reached anyone. ``converse``,
        ``converse_streaming`` and ``resume`` hand none and their rows carry none, and
        an absent value is never read as delivered and never read as heard (§3). The
        episode id the index allocated is written back onto it here, which is the one
        place that knows it.

        **``modality`` is passed at every call site and this method neither computes
        nor defaults it** (ADR-0221 §5) — the same shape as ``supplied_withheld``, for
        the same reason and at the same sites. It belongs to *the user material the
        episode renders*, not to the pass performing the capture, so it cannot be read
        off the ``spoken`` above: :meth:`_capture_resumption` hands none and yet its
        episode renders a turn that may have been spoken. §5's three cases are
        answered by the callers — :meth:`_run_turn` and :meth:`_finish_route` from
        their own pass's ``_SpokenCapture``, :meth:`_capture_resumption` from the
        value the park retained, and :meth:`_compose_and_capture_routed` with
        ``TEXT`` — and a required parameter is what makes a site that has not thought
        about it fail to compile rather than silently record ``TEXT``.

        **``derived_from_external`` is passed at every call site too, and this method
        neither computes nor defaults it either** (ADR-0223 §1) — a third field with
        the shape ``supplied_withheld`` and ``modality`` already have, and for a
        reason of its own: the value is the disjunction of
        ``rests_on_recorded_external_content`` over *the supply the turn ran over*,
        which only the pass that made the selection holds. §3's partition is
        **ADR-0204 §2's and not ADR-0221 §5's**, and the two differ on one site:
        :meth:`_finish_route` passes this pass's ``modality`` and ``False`` here,
        because a routed pass does have user material and does not have a supply. The
        other sites are the same three — :meth:`_run_turn` from the single computation
        it hoists above its branch, :meth:`_capture_resumption` from the value the
        park retained, and :meth:`_compose_and_capture_routed` with ``False``, which
        is true of an episode rendering no turn rather than a fallback.
        """
        report = await self._conversations.capture(
            conversation_id,
            content=(
                _exchange_of(turn, step, resumed=resumed)
                if routed is None
                else _routed_exchange_of(utterance, resumed=resumed)
            ),
            asked=asked,
            outcome=None if composed is None else composed.text,
            disposition=(
                _outcome_of(step) if routed is None else _routed_outcome_of(routed.outcome)
            ),
            parked=parked,
            supplied_withheld=supplied_withheld,
            modality=modality,
            derived_from_external=derived_from_external,
            delivery=None if spoken is None else spoken.delivery,
        )
        if spoken is not None:
            spoken.episode_id = report.episode_id
        return TurnOutcome(
            turn=turn,
            step=step,
            conversation_id=report.conversation_id,
            capture_degraded=report.degraded,
            reply=None if composed is None else composed.text,
            reply_degraded=composed is not None and composed.degraded,
            routed=routed,
            recipient_grant=recipient_grant,
        )

    async def _learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Delegate to the loop and translate its write outcomes (ADR-0042 §1)."""
        outcomes = await self._loop.learn(event)
        return learn_outcome(outcomes)

    async def _beliefs(
        self,
        *,
        bands: tuple[BeliefBand, ...] | None,
        kinds: tuple[MemoryKind, ...] | None,
        limit: int,
        offset: int,
    ) -> tuple[BeliefSummary, ...]:
        """Relay the enumeration to the store and summarise each record (ADR-0073 §7).

        The filters arrive already materialised by :meth:`beliefs`; the page's order
        and membership are the store's, and this adds no re-ordering, no re-filtering
        and no count of its own.
        """
        records = await self._memory.list_beliefs(
            bands=bands, kinds=kinds, limit=limit, offset=offset
        )
        return tuple([await self._summarise(record) for record in records])

    async def _belief(self, record_id: str) -> Belief | None:
        """Read one live record and project it, or report that there is none."""
        record = await self._memory.get(record_id)
        return None if record is None else await self._project(record)

    async def _resolved_citations(self, record: MemoryRecord) -> list[Evidence]:
        """Resolve the record's citations at the moment of presentation (ADR-0077 §6).

        **Lazily, here, and without rewriting anything.** The evidence tuple keeps
        the ids as written and the whole tuple is resolved through
        :meth:`~ai_assistant.core.protocols.MemoryStore.get_many`, so a citation the
        user destroyed — or one that expired under a retention horizon, which is the
        *commoner* case and has no event to hook — renders as a tombstone rather than
        a dangling id. Nothing is written: the record graph is frozen (ADR-0068), and
        losing evidence is not the producer changing its mind.

        **One batch read per record, not one ``get`` per citation** (ADR-0086 §6, §8
        item 6). `get_many` never disagrees with `get` — an id it omits is exactly an
        id `get` would answer ``None`` for, on all three read-time outcomes — so every
        tombstone this renders is the one the loop rendered. What changes is that a
        record's citations are now judged against **one** instant and one state of the
        store rather than against *n* of each, so a belief's rendered count can no
        longer disagree with its own tombstones because a citation expired partway
        through its own presentation.

        The answer is assembled by walking ``provenance.evidence``, never the mapping:
        the tuple carries the order and any repeated id, and a mapping carries neither
        (§6, "a mapping, not a sequence"). A record citing nothing asks for nothing,
        which §6 gives an answer and no round trip.

        Resolution happens at this façade rather than in `interfaces/`, which golden
        rule 3 keeps thin and which ADR-0072 §7 already refused to give a
        live-at-now computation.
        """
        cited = record.provenance.evidence
        found = await self._memory.get_many(cited)
        resolved: list[Evidence] = []
        for one in cited:
            episode = found.get(one)
            resolved.append(Evidence(content=None if episode is None else episode.content))
        return resolved

    async def _project(self, record: MemoryRecord) -> Belief:
        """Project one record into the **single-belief** view, citations and all."""
        return belief_from_record(record, tuple(await self._resolved_citations(record)))

    async def _summarise(self, record: MemoryRecord) -> BeliefSummary:
        """Project one record into the **listing**'s summary (ADR-0085 §4a).

        The listing "resolves *existence* and renders the count, the lost count, and
        the adjusted confidence" (ADR-0077 §6), so existence is still resolved per
        citation — the adjusted confidence is a function of how many resolved — but
        the contents go nowhere: a
        :class:`~ai_assistant.core.types.BeliefSummary` has no field one could
        occupy. That is what removes the ``beliefs * citations * content`` term from
        ADR-0085 §8f's frame arithmetic, structurally rather than by argument.

        **The listing still resolves, and now it resolves in one read per belief.**
        ADR-0085 §4a removed the payload and none of the reads — the count, the lost
        count and the adjusted confidence are all functions of how many citations
        resolved — so this shares :meth:`_resolved_citations` with the single-belief
        view and inherits its batch (ADR-0086 §6, §8 item 6). A page is one
        ``get_many`` per listed belief rather than one ``get`` per citation of each.
        """
        citations = await self._resolved_citations(record)
        return belief_summary_from_record(
            record,
            cited=len(citations),
            resolved=sum(1 for item in citations if not item.lost),
        )

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
        stands.** A ``converse`` that ran a tool, persisted its execution and
        captured the exchange, and only then produced a
        :class:`~ai_assistant.core.types.TurnOutcome` too large to carry, raises here
        with all of that already durable. That is not an ordering this lane chose and
        it is not one it can fix: no measurement of a *result* can precede producing
        it, and a wire client meets the identical situation one frame further out —
        the hub runs the turn and then cannot send what came back.

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

    def _step_outcome(  # noqa: PLR0913 — the turn, the raw disposition, the step it names, the pre-minted handle, and the three values a park retains for its resolution's capture; every one is a distinct fact about the pass
        self,
        turn: TurnResult | None,
        disposition: StepDisposition,
        *,
        step_id: str,
        handle: str | None,
        supplied_withheld: bool = False,
        modality: Modality = Modality.TEXT,
        derived_from_external: bool = False,
    ) -> StepOutcome:
        """Wrap a raw stage disposition, enriching a parked step (ADR-0042 §4).

        ``handle`` is the continuation handle minted *before* the runner could park
        (:meth:`_converse`); it is consumed only on the parked branch, and is
        ``None`` where no park is possible (a resumption, whose ``turn`` may itself
        be ``None`` on the recovered path — but a resolving disposition is never
        ``AWAITING_CONFIRMATION``, so the parked branch below is never taken there).

        ``supplied_withheld`` is this turn's own ADR-0204 §2 evaluation, on
        its way to the parked entry that the resolution's capture will read it back
        off. It reaches nothing else: the ``StepOutcome`` this method returns gains no
        member, and a pass that cannot park — a resumption, whose park already exists
        — passes none, exactly as it passes no handle.

        ``modality`` travels the same way and for the same reason (ADR-0221 §5's
        second case): it is this turn's own value, bound for the parked entry so the
        resolution stamps the material *this* turn supplied rather than recomputing
        one from a pass that has no user material of its own.

        ``derived_from_external`` is the third, on ADR-0223 §3's second case: this
        turn's own disjunction over the supply it ran over — the very value its own
        ``SelectionOrigin`` carried to the egress seam on this pass (§2) — bound for
        the parked entry so the resolution stamps that turn's answer rather than
        recomputing one over a supply that has moved on.
        """
        confirmation: Confirmation | None = None
        if disposition.disposition is Disposition.AWAITING_CONFIRMATION:
            if handle is None:  # pragma: no cover — _converse pre-mints before any park
                # Only a resumption passes None, and a resolving disposition is never
                # AWAITING_CONFIRMATION, so reaching here would be an internal fault.
                msg = "a parked step reached rendering without a pre-minted continuation handle"
                raise PlanningError(msg)
            if turn is None:  # pragma: no cover — the parked branch is only reached from _converse
                # A pre-minted handle is only present on the converse path, which
                # always carries a real turn; a recovered resume never parks anew.
                msg = "a parked step reached rendering without its originating turn"
                raise PlanningError(msg)
            confirmation = self._confirmation(
                turn,
                disposition,
                handle,
                supplied_withheld=supplied_withheld,
                modality=modality,
                derived_from_external=derived_from_external,
            )
        return StepOutcome(
            disposition=disposition.disposition,
            state=disposition.state,
            step_id=step_id,
            tool_id=disposition.tool_id,
            confirmation=confirmation,
        )

    def _confirmation(  # noqa: PLR0913 — the turn, the raw disposition, the pre-minted handle, and the three values the parked entry retains for its resolution's capture; every one is a distinct fact about the pass
        self,
        turn: TurnResult,
        disposition: StepDisposition,
        handle: str,
        *,
        supplied_withheld: bool = False,
        modality: Modality = Modality.TEXT,
        derived_from_external: bool = False,
    ) -> Confirmation:
        """Assemble the confirmation content around a pre-minted token (ADR-0042 §4).

        The tool declaration and the ruling ``reason`` come from the **recorded**
        ``CONFIRM`` the runner already read back and carried on its disposition
        (:attr:`~ai_assistant.orchestration.runner.StepDisposition.decision`) — the
        decision the user is being shown, which the adapter may not read itself
        (ADR-0042 §6). And ``handle`` was minted before the runner parked
        (:meth:`_converse`). So **no fallible work remains between parking the step
        and offering its token**: everything that could raise — reading the
        decision, calling the id factory — happened before ``run`` committed
        AWAITING_APPROVAL, so a parked step is never stranded without a continuation
        (#287). The parameters are the driven step's own, carried as data for the
        adapter to escape per target (ADR-0042 §4).
        """
        recorded = disposition.decision
        if recorded is None:  # pragma: no cover — StepRunner always sets it on this branch
            # A runner-contract violation, not caller input: a parked CONFIRM must
            # carry its decision so the step is resumable without a fallible re-read.
            msg = "a parked confirmation carries no recorded decision, so it cannot be rendered"
            raise PlanningError(msg)
        self._parked[handle] = _Parked(
            turn=turn,
            execution_id=disposition.state.id,
            step_id=turn.plan.steps[0].id,
            confirmation_id=recorded.id,
            # The parking turn's own evaluation, retained beside the turn it belongs
            # to so the resolution's capture stamps that turn's value rather than
            # recomputing one from a pass that retrieves nothing (ADR-0204 §2) — and
            # its own modality beside it, retained for ADR-0221 §5's second case,
            # which is that clause applied to a second field, and its own origin mark
            # beside both, retained for ADR-0223 §3's second case, which is that same
            # clause applied to a third.
            supplied_withheld=supplied_withheld,
            modality=modality,
            derived_from_external=derived_from_external,
        )
        return Confirmation(
            tool_id=recorded.tool.id,
            tool_description=recorded.tool.description,
            parameters=turn.plan.steps[0].parameters,
            reason=recorded.ruling.reason,
            token=ContinuationToken(handle=handle),
            egress=_confirmation_egress(recorded),
        )

    def _recovered_confirmation(
        self,
        execution_id: str,
        step_id: str,
        parameters: FrozenJsonMapping,
        confirmed: PermissionDecision,
    ) -> Confirmation:
        """Assemble a :class:`Confirmation` for a durably-parked step (ADR-0052 §1).

        The counterpart to :meth:`_confirmation` on the recovery path: the tool
        content and ruling ``reason`` come from the ``CONFIRM`` recovered from the
        trail, and the parameters from the plan step (the trail holds only a
        digest). The token names a ``_parked`` entry with ``turn=None`` and
        ``confirmation_id=None`` (:meth:`_handle_for_binding`), so a subsequent
        :meth:`resume` routes through the runner's restart recovery.
        """
        handle = self._handle_for_binding(execution_id, step_id)
        return Confirmation(
            tool_id=confirmed.tool.id,
            tool_description=confirmed.tool.description,
            parameters=parameters,
            reason=confirmed.ruling.reason,
            token=ContinuationToken(handle=handle),
            egress=_confirmation_egress(confirmed),
        )

    def _handle_for_binding(self, execution_id: str, step_id: str) -> str:
        """A continuation handle for a recovered binding, reused if already held.

        Idempotency and boundedness (ADR-0052 §2): if a ``_parked`` entry already
        names this ``(execution_id, step_id)`` binding — from an earlier recovery
        call — its handle is returned rather than a second minted, so repeated
        :meth:`pending_confirmations` calls yield stable tokens and the table stays
        bounded by the number of distinct durably-parked bindings. Otherwise a fresh
        unique handle is minted and the recovered entry registered. Runs to
        completion with no ``await`` from the uniqueness check to the write, so the
        mint-and-register is atomic against concurrency, as :meth:`_mint_handle` is.
        """
        for existing, parked in self._parked.items():
            if parked.execution_id == execution_id and parked.step_id == step_id:
                return existing
        handle = self._mint_handle()
        # _mint_handle reserves the handle against in-flight turns; a recovered park
        # goes straight into the table it counts against, so the reservation is released.
        self._reserved.discard(handle)
        self._parked[handle] = _Parked(
            turn=None, execution_id=execution_id, step_id=step_id, confirmation_id=None
        )
        return handle


__all__ = [
    "Engine",
    "belief_from_record",
    "belief_summary_from_record",
    "conversation_summary",
    "learn_decision",
    "learn_outcome",
    "presented_confidence",
    "queued_question",
]
