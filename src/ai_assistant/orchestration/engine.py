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
:meth:`Engine.ingest` and :attr:`Engine.drain_phase`. New *concrete* surface on
this class rather than ``core`` contract surface — the scheduler holds this object
from inside the hub, not the ``AssistantEngine`` Protocol a client sees, whose
fifteen methods ADR-0085 §1 fixes and none of these is among.

:meth:`Engine.ingest` is that surface's second scheduled operation and leg 6's
(ADR-0093 §6): it reads the injected :class:`~ai_assistant.core.protocols.Reader`
once and puts every belief the reading proposes through the same write path
``learn`` and ``observe`` use, because ADR-0093 §1 declines the capture exemption
to a reader and a third party's report is the last thing that should reach the
store unmediated. It is **optional collaborator, required behaviour**: a reader
ships disabled by default (§7), so an engine wired without one is the ordinary
deployment — and asking it to ingest is then a wiring fault it refuses rather than
an empty success it reports.

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
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, TypeVar, assert_never

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConfigurationError,
    ConversationStoreError,
    NotificationBudgetError,
    PlanningError,
    TraceStoreError,
    UnknownContinuationError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    Belief,
    BeliefSummary,
    Confirmation,
    ContinuationToken,
    ConversationSummary,
    DeferralAdmissionOutcome,
    Disposition,
    Evidence,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryDecisionKind,
    MemoryKind,
    NotificationDispositionKind,
    ParkedBinding,
    QueuedQuestion,
    QueueOutcome,
    StepOutcome,
    StepStatus,
    TraceOutcome,
    TurnOutcome,
    band_of,
)
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_payload,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
)
from ai_assistant.orchestration.questions import question_state
from ai_assistant.orchestration.traces import Observation, OperationTraces

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        AuditTrail,
        DeferralStore,
        MemoryStore,
        NotificationPolicy,
        NotificationStore,
        PlanStore,
        TraceRetention,
        TraceSink,
    )
    from ai_assistant.core.types import (
        AnswerOutcome,
        BeliefBand,
        Conversation,
        ConversationDigest,
        DeferralAdmission,
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
        NotificationDelivery,
        NotificationDisposition,
        NotificationPreferences,
        ObservationReport,
        PermissionDecision,
        Question,
        SourceGrant,
        TurnResult,
    )
    from ai_assistant.orchestration.consolidation import (
        ConsolidationReport,
        ConsolidationStage,
    )
    from ai_assistant.orchestration.conversations import ConversationLifecycle
    from ai_assistant.orchestration.delivery import DeliveryOutbox
    from ai_assistant.orchestration.grants import GrantOperations
    from ai_assistant.orchestration.ingestion import IngestionReport, IngestionStage
    from ai_assistant.orchestration.loop import LearningLoop
    from ai_assistant.orchestration.observation import ObservationStage
    from ai_assistant.orchestration.questions import QuestionStage
    from ai_assistant.orchestration.runner import StepDisposition, StepRunner
    from ai_assistant.orchestration.writes import WriteOutcome

_log = structlog.get_logger(__name__)

_T = TypeVar("_T")

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
    )


def conversation_summary(conversation: Conversation) -> ConversationSummary:
    """Project one stored conversation into the summary a person reads (ADR-0074 §2)."""
    return ConversationSummary(
        id=conversation.id,
        started_at=conversation.started_at,
        last_active_at=conversation.last_active_at,
        last_turn_at=conversation.last_turn_at,
    )


def _outcome_of(step: StepOutcome | None) -> str:
    """How the exchange turned out, as the captured episode's ``outcome`` (ADR-0074 §4).

    Total over :class:`~ai_assistant.orchestration.runner.Disposition` and
    mechanically so — the wildcard does nothing but ``assert_never`` — so a
    disposition added without a phrase here fails the gate rather than recording an
    exchange whose outcome reads as empty. This is deterministic recording, not a
    judgement: it says what the engine did, and infers nothing about the user.
    """
    if step is None:
        return "no action was needed"
    match step.disposition:
        case Disposition.EXECUTED:
            return "the selected tool ran"
        case Disposition.DENIED:
            return "the action was refused by the permission policy"
        case Disposition.AWAITING_CONFIRMATION:
            return "the action was parked for the user to confirm"
        case Disposition.NO_CAPABLE_TOOL:
            return "no tool advertised the capability the step needed"
        case Disposition.AMBIGUOUS_CAPABILITY:
            return "several tools advertised the capability, so none was chosen"
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


@dataclass(frozen=True, slots=True)
class _Parked:
    """The private state one continuation token names (never seen by an adapter).

    ``turn`` is ``None`` and ``confirmation_id`` is ``None`` for an entry
    reconstructed from durable state by :meth:`Engine.pending_confirmations`
    (ADR-0052): a recovered park has no live turn, and a ``None`` confirmation id
    routes :meth:`Engine.resume` through the runner's restart recovery path
    (recover the ``CONFIRM`` by its ``(execution_id, step_id)`` binding, ADR-0044
    §3) rather than caching a decision id a concurrent resolution could stale.
    """

    turn: TurnResult | None
    execution_id: str
    step_id: str
    confirmation_id: str | None


class Engine:
    """The concrete façade an interface adapter drives (ADR-0042 §1).

    Composes the engine's stage objects behind two calls and one shutdown path.
    It is handed the stage objects and the ``PlanStore`` — the same instance its
    ``runner`` was wired with — by the composition root, the one layer licensed to
    construct concretes (ADR-0042 §2).
    """

    def __init__(  # noqa: PLR0913 — one parameter per injected collaborator plus its knobs
        self,
        *,
        loop: LearningLoop,
        runner: StepRunner,
        plans: PlanStore,
        trail: AuditTrail,
        memory: MemoryStore,
        deferrals: DeferralStore,
        traces: TraceRetention,
        trace_sink: TraceSink,
        trace_retention: timedelta | None,
        conversations: ConversationLifecycle,
        observation: ObservationStage,
        questions: QuestionStage,
        grant_operations: GrantOperations,
        ingestion: IngestionStage | None = None,
        consolidation: ConsolidationStage | None = None,
        notifications: NotificationStore | None = None,
        notification_policy: NotificationPolicy | None = None,
        notification_outbox: DeliveryOutbox | None = None,
        max_notification_budget: timedelta = _DEFAULT_MAX_NOTIFICATION_BUDGET,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
        id_factory: Callable[[], str] = _uuid,
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

                **Required, where ``ingestion`` below is optional, and the
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
            ingestion: The read-only ingestion stage (ADR-0093 §6), or ``None``
                where this deployment configured no source. It writes through the
                *same* write stage the learn leg and ``observation`` use — the
                composition-root obligation ADR-0078 §3 puts on every producer, so
                an ingested belief the policy defers parks a question the user can
                actually answer, and one it stores is retrievable and forgettable
                through the surfaces the user already has (ADR-0028 §4).

                **Optional, where its three siblings above are required, and the
                asymmetry is ADR-0093 §7 rather than laxity.** Every reader ships
                **disabled by default**, "and the reason is that nothing may read a
                user's personal files because a default said so" — so an engine
                with no reader is not a half-built engine, it is the default
                deployment, and requiring the stage would make every caller
                manufacture a reader for a source the operator never configured.
                What is *not* optional is what :meth:`ingest` does about it: it
                refuses rather than reporting an empty success, because a job that
                reports health while ingesting nothing is the failure mode this
                corpus keeps naming (ADR-0022 §4a).
            consolidation: The chunked consolidation stage (ADR-0106, ADR-0111), or
                ``None`` where this deployment wires none. It writes through the
                *same* write stage every other producer here uses — ADR-0106 §6
                obliges it by name, because a job calling ``MemoryWriter.ingest``
                directly would rule ``ASK_USER`` on a thousand consolidations and
                persist not one question — and it walks the **same ``MemoryStore``
                instance** ``memory`` names, or it would propose beliefs citing
                records the write path cannot resolve.

                **Optional for ``ingestion``'s reason**, one job over: the
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
                state, on ``ingest``'s shape: "no store is wired" and "no
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
            TypeError: If ``max_outstanding_confirmations`` is not an integer. A
                ``bool`` is excluded (it is an ``int`` subclass and a flag is not a
                count), and a ``float`` like ``1.5`` is refused rather than compared
                — the same guard shape ``LearningLoop`` uses for its own count.
            ValueError: If it is not positive.
        """
        if isinstance(max_outstanding_confirmations, bool) or not isinstance(
            max_outstanding_confirmations, int
        ):
            msg = (
                "max_outstanding_confirmations must be an integer, got "
                f"{max_outstanding_confirmations!r}"
            )
            raise TypeError(msg)
        if max_outstanding_confirmations < 1:
            msg = (
                "max_outstanding_confirmations must be positive, got "
                f"{max_outstanding_confirmations}"
            )
            raise ValueError(msg)
        self._loop = loop
        self._runner = runner
        self._plans = plans
        self._trail = trail
        self._memory = memory
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
        self._observation = observation
        self._questions = questions
        self._grants = grant_operations
        self._ingestion = ingestion
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
        self._closers = tuple(closers)
        self._id_factory = id_factory
        self._max_outstanding = max_outstanding_confirmations
        self._max_payload_bytes = max_payload_bytes
        self._drain_timeout = drain_timeout
        self._parked: dict[str, _Parked] = {}
        self._reserved: set[str] = set()
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
        """Finish the sweeps a previous run left behind (ADR-0074 §7, §8; ADR-0076).

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
        """Finish pending deletions, reclaim, then reconcile the delivery outbox."""
        await self._conversations.sweep_deletions()
        await self._conversations.reclaim()
        if self._notification_outbox is not None:
            await self._recover_leases_once()
            await self._notification_outbox.reconcile()

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

    async def ingest(self) -> IngestionReport:
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
        if self._ingestion is None:
            msg = (
                "no ingestion stage is wired, so there is nothing to ingest; it "
                "needs a configured source (ASSISTANT_CALENDAR_READER_PATH, "
                "ADR-0093 §7a). Configuration says where a source is; a grant says "
                "whether it may be read, and neither stands in for the other"
            )
            raise ConfigurationError(msg)
        return await self._tracked(self._ingestion.ingest(), "ingest", _ingested)

    async def consolidate(self) -> ConsolidationReport:
        """Distil stored records into durable beliefs, one bounded run (ADR-0106).

        The **maintenance surface**'s third scheduled operation. ADR-0083 §8 already
        settled that this is "new *concrete* surface on a class in
        ``orchestration``, not ``core`` contract surface", and ADR-0085 §1 fixes the
        promoted ``AssistantEngine`` Protocol at fifteen *request* methods with
        lifecycle deliberately off it — "a Protocol constrains what an
        implementation must have, not what it may not". :meth:`purge_expired` and
        :meth:`ingest` are the standing proof, and ADR-0114 §9 records this as a
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
                stage, for :meth:`ingest`'s reason: an empty report would be
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
            conversation it ran under and whether recording it degraded. ``step`` is
            ``None`` when the plan had no step.

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

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam (ADR-0029 §4)
    ) -> TurnOutcome:
        """Answer a parked confirmation and continue its step (ADR-0042 §3, §4).

        The adapter relays the opaque ``token`` and the human's yes/no; it does
        **not** author the outcome. ``ActionPolicy.resolve`` — inside
        `permissions`, reached through the engine — is what turns ``approved`` into
        an ``ALLOW`` or ``DENY``, and only ``approved=False → DENY`` is guaranteed:
        ``approved=True`` may still be refused by the policy (ADR-0042 §4). The
        adapter conveys consent; the policy rules; the engine records and executes.

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

        Returns:
            The resumed turn: the parked turn's own result, and the step's
            resolved disposition (``EXECUTED`` or ``DENIED``).

        Raises:
            RuntimeError: If the engine is shutting down.
            PlanningError: If ``token`` names no parked step this engine holds — a
                token from a previous process, or one already resolved and evicted
                (its lifetime is process-scoped; ADR-0042 §4, the Revisit-if clause
                ties durable resume to #242).
            PermissionDeniedError: If the recorded decision is not a ``CONFIRM``
                about this parked step (``StepRunner`` refuses it).
            AuditError, ToolBindingError: As the stages raise.
        """
        self._reject_if_closing()
        check_arguments(
            "resume",
            max_bytes=self._max_payload_bytes,
            token=token,
            approved=approved,
            timeout=timeout,
        )
        return await self._tracked(
            self._resume(token, approved=approved, timeout=timeout), "resume", checked=True
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
        answer" to hide the round trip in; the roadmap sequences leg 4's soundness
        work against volume, and a per-turn trigger *is* volume on the day it
        merges; the first producer that sends accumulated history to a model should
        not run without the user knowing; and the hub's scheduler becomes a second
        caller of this same operation, so cadence becomes configuration rather than
        a contract change.

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
        connections (ADR-0042 §2).

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
        return await self._tracked(self._observation.observe(selected), "observe", checked=True)

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
        return await self._tracked(self._memory.delete(named), "forget", checked=True)

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
        actionability — which frees a slot under the cap at once and stops its
        key suppressing duplicates.

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
        """
        if self._notification_outbox is None:
            return
        if ruling.kind is not NotificationDispositionKind.INTERRUPT:
            return
        await self._notification_outbox.offer(candidate)

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
            ConfigurationError: If none is wired, in :meth:`ingest`'s shape — a
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
        """
        async with self._recovery_lock:
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
        self, *, acknowledging: Identifier | None = None, budget: timedelta
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

        Args:
            acknowledging: The ``delivery_id`` being confirmed, or ``None``.
            budget: How long the hub may hold this request before answering with
                nothing.

        Returns:
            The delivery to show, or ``None`` where the budget elapsed with
            nothing available.

        Raises:
            RuntimeError: If the engine is shutting down.
            ValueError: If ``acknowledging`` is blank.
            NotificationBudgetError: If ``budget`` is negative or above the
                configured ceiling.
            ConfigurationError: If no delivery outbox is wired.
            NotificationOutboxError: If the outbox cannot be read or written, or
                an acknowledgement's dismissal could not commit.
        """
        self._reject_if_closing()
        named = None if acknowledging is None else identifier(acknowledging, name="acknowledging")
        self._check_budget(budget)
        check_arguments(
            "next_notification",
            max_bytes=self._max_payload_bytes,
            acknowledging=named,
            budget=budget,
        )
        outbox = self._delivery_surface()
        return await self._tracked(
            self._poll(outbox, named, budget), "next_notification", checked=True
        )

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
        self, outbox: DeliveryOutbox, acknowledging: Identifier | None, budget: timedelta
    ) -> NotificationDelivery | None:
        """Apply the acknowledgement, then wait out the budget for an entry.

        The deadline is computed **once**, from this engine's guarded clock, so a
        poll's length is fixed at its start rather than recomputed against a clock
        that may move under it.

        **And before the acknowledgement is applied, because computing it can still
        refuse.** ADR-0131 §4 is unconditional that a refused request "retires
        nothing, leases nothing and mints nothing", and an acknowledgement is a
        retirement that cannot be taken back: the entry is gone, and the device is
        told by the same call that its poll failed. Round 11's fix for the
        unrepresentable deadline put that refusal *after* the acknowledgement and so
        reintroduced the very ordering the range check next door exists to keep —
        adversarial review found it on the twelfth round. Computing it first also
        makes "fixed at its start" literally true, the acknowledgement now falling
        inside the budget rather than ahead of it.

        Raises:
            NotificationBudgetError: If the deadline is not representable, which is
                the budget being unusable rather than merely large.
        """
        try:
            deadline = self._now() + budget
        except OverflowError as exc:
            # **A budget the clock cannot add is a budget refusal, not a crash.**
            # `hub_max_notification_budget` is bounded below and not above (§5a
            # states the figure and its range, and a ceiling it does not state is
            # not this lane's to invent), so an operator may configure one near
            # `timedelta.max`; a client then asking for exactly the ceiling reaches
            # this addition and `datetime` raises a raw `OverflowError`. The wire
            # dispatcher maps this project's error types and nothing else, so the
            # raw one would drop a *valid* request's connection instead of answering
            # it. This is the same fact the range check next door reports —  the
            # budget cannot be honoured — so it is reported the same way.
            # Adversarial review found it on the eleventh round.
            msg = (
                f"budget {budget} cannot be honoured: added to the hub's clock it leaves "
                f"the range a datetime can represent, so no deadline exists for this poll "
                f"(ADR-0131 §4)"
            )
            raise NotificationBudgetError(msg) from exc
        if acknowledging is not None:
            await outbox.acknowledge(acknowledging)
        while True:
            delivery = await outbox.claim()
            if delivery is not None:
                return delivery
            remaining = deadline - self._now()
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

    async def _tracked(
        self,
        coro: Awaitable[_T],
        seam: str,
        observe: Callable[[_T], Observation] | None = None,
        *,
        checked: bool = False,
    ) -> _T:
        """Run ``coro`` as a tracked, shielded, **traced** task, so shutdown can drain it.

        The task is what :meth:`aclose` awaits, and the shield is what keeps the
        underlying work alive when the *caller* cancels: a cancelled
        ``converse()``/``resume()``/``pending_confirmations()`` abandons this await,
        but the task keeps running and stays tracked until it finishes, which is
        what lets the drain wait for work a cancelled call orphaned (ADR-0042 §2).
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

        Returns:
            Whatever ``coro`` returned.
        """
        work = self._checked_result(coro, seam) if checked else coro
        task: asyncio.Task[_T] = asyncio.ensure_future(
            self._operation_traces.observing(seam, work, observe)
        )
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

        **Recovered entries do not count.** The ceiling bounds the memory a client
        can pin by requesting confirmable actions and abandoning their tokens — the
        *converse* path, whose entries carry the turn (``turn is not None``). An
        entry recovered from durable state (``turn is None``,
        :meth:`pending_confirmations`) is bounded by durable state and reconciled on
        each recovery, so counting it would let durably-parked work apply false
        backpressure to new turns (a resolution by another engine could otherwise
        leave a stale entry that blocks forever). So capacity counts only
        turn-carrying parks.

        Called *before* the runner can park and before the turn is persisted, so a
        refusal leaves neither durable execution state nor a durable goal/plan.

        Raises:
            RuntimeError: If ``max_outstanding_confirmations`` confirmations are
                already outstanding or reserved.
        """
        outstanding = sum(1 for parked in self._parked.values() if parked.turn is not None)
        if outstanding + len(self._reserved) >= self._max_outstanding:
            msg = (
                f"{self._max_outstanding} confirmations are already awaiting an answer; resolve "
                "some before starting another action"
            )
            raise RuntimeError(msg)
        return self._mint_handle()

    def _mint_handle(self) -> str:
        """Reserve and return a handle no other outstanding continuation is using.

        The injected factory supplies the opacity; the engine supplies the
        *uniqueness*, against both the parked table and the set of handles reserved
        by turns still in flight. A factory that repeats a handle is disambiguated
        with a suffix rather than trusted or refused, so two parked steps never
        share a handle and neither is stranded.

        **Reservation is atomic against concurrency.** This method runs to
        completion with no ``await`` between checking uniqueness and recording the
        reservation, so two concurrent turns cannot both mint the same handle even
        with a repeating factory: the first fully reserves before the second reads.
        The reservation is released by :meth:`_converse` once the turn is known to
        park (moved into the parked table) or not. Called *before* the runner can
        park, so a raising factory fails with no durable state yet committed.
        """
        handle = self._id_factory()
        suffix = 0
        while handle in self._parked or handle in self._reserved:
            suffix += 1
            handle = f"{self._id_factory()}#{suffix}"
        self._reserved.add(handle)
        return handle

    async def _converse(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — threaded through to the seam (ADR-0029 §4)
        conversation_id: str | None,
    ) -> TurnOutcome:
        """Resolve the conversation, plan the turn, drive its step, record it."""
        # Before the turn's work (ADR-0074 §2), so the id exists whatever the turn
        # does and a continuation marks the conversation active before a reclaim
        # could judge it idle.
        conversation = await self._conversations.begin(conversation_id)
        history = await self._conversations.history(conversation.id)
        turn = await self._loop.respond(
            utterance, history=history.records, history_degraded=history.degraded
        )
        self._check_plan_is_for_goal(turn)
        if not turn.plan.steps:
            # A no-action decision is still a decision, and drives nothing that
            # could park — so it needs no capacity slot, and its goal and plan are
            # persisted as an auditable record (ADR-0014 §2).
            await self._plans.save_goal(turn.goal)
            await self._plans.save_plan(turn.plan)
            return await self._capture(conversation.id, turn=turn, step=None, resumed=False)
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
            await self._plans.save_plan(turn.plan)
            state = await self._plans.start_execution(turn.plan.id)
            disposition = await self._runner.run(state, first.id, timeout=timeout)
            step = self._step_outcome(turn, disposition, step_id=first.id, handle=handle)
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
        return await self._capture(
            conversation.id, turn=turn, step=step, resumed=False, parked=parked
        )

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
    ) -> TurnOutcome:
        """Reload the parked execution and continue its step.

        Runs under ``_recovery_lock`` so a resolution is mutually exclusive with a
        recovery enumeration: resolving records the decision through the runner and
        evicts the binding's ``_parked`` entry, both of which recovery reads, so the
        two must not interleave (:meth:`_pending_confirmations`, round 3 review). The
        lock is held across the runner call — the resolve and any execution it drives
        — so recovery cannot observe a binding mid-resolution. Resolutions are
        human-paced, so serializing them behind this one lock is free in practice.
        """
        async with self._recovery_lock:
            parked = self._parked.get(token.handle)
            if parked is None:
                msg = (
                    "this token names no step awaiting confirmation in this engine; it may be "
                    "from an earlier run of the process, or already resolved. Call "
                    "pending_confirmations() to re-mint a token for any park that is still "
                    "answerable"
                )
                raise UnknownContinuationError(msg)
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
            )
            # A resolving disposition is EXECUTED or DENIED, never AWAITING_CONFIRMATION,
            # so no new handle is needed here.
            step = self._step_outcome(parked.turn, disposition, step_id=parked.step_id, handle=None)
            # Resolved once: a second answer would be refused by the trail's
            # single-resolution index anyway; evicting keeps the table bounded and
            # turns a replay into a clean "unknown token" (ADR-0042 §4).
            self._parked.pop(token.handle, None)
            return await self._capture_resumption(parked, step)

    async def _capture_resumption(self, parked: _Parked, step: StepOutcome) -> TurnOutcome:
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
            return TurnOutcome(turn=parked.turn, step=step, capture_degraded=True)
        return await self._capture(
            origin.conversation_id, turn=parked.turn, step=step, resumed=True
        )

    async def _capture(
        self,
        conversation_id: str,
        *,
        turn: TurnResult | None,
        step: StepOutcome | None,
        resumed: bool,
        parked: ParkedBinding | None = None,
    ) -> TurnOutcome:
        """Record the exchange and fold what became of it into the outcome (§3, §9).

        The capture point is where a ``TurnOutcome`` is produced, which is both
        ``converse`` and ``resume`` (ADR-0042 §3's "one result out"). So a turn that
        parks for confirmation is captured **when it parks** — the alternative,
        holding the episode open until the park resolves, would make the record of
        an exchange depend on a confirmation the user may never answer, so an
        abandoned park would erase the question they actually asked.
        """
        report = await self._conversations.capture(
            conversation_id,
            content=_exchange_of(turn, step, resumed=resumed),
            outcome=_outcome_of(step),
            parked=parked,
        )
        return TurnOutcome(
            turn=turn,
            step=step,
            conversation_id=report.conversation_id,
            capture_degraded=report.degraded,
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

    def _step_outcome(
        self,
        turn: TurnResult | None,
        disposition: StepDisposition,
        *,
        step_id: str,
        handle: str | None,
    ) -> StepOutcome:
        """Wrap a raw stage disposition, enriching a parked step (ADR-0042 §4).

        ``handle`` is the continuation handle minted *before* the runner could park
        (:meth:`_converse`); it is consumed only on the parked branch, and is
        ``None`` where no park is possible (a resumption, whose ``turn`` may itself
        be ``None`` on the recovered path — but a resolving disposition is never
        ``AWAITING_CONFIRMATION``, so the parked branch below is never taken there).
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
            confirmation = self._confirmation(turn, disposition, handle)
        return StepOutcome(
            disposition=disposition.disposition,
            state=disposition.state,
            step_id=step_id,
            tool_id=disposition.tool_id,
            confirmation=confirmation,
        )

    def _confirmation(
        self, turn: TurnResult, disposition: StepDisposition, handle: str
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
        )
        return Confirmation(
            tool_id=recorded.tool.id,
            tool_description=recorded.tool.description,
            parameters=turn.plan.steps[0].parameters,
            reason=recorded.ruling.reason,
            token=ContinuationToken(handle=handle),
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
