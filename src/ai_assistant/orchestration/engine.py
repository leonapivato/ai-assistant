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
deliberately explicit: nothing triggers it but a caller, which today is the CLI
and later is leg 5's scheduler, unchanged.

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
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar, assert_never

import structlog

from ai_assistant.core.errors import ConversationStoreError, PlanningError
from ai_assistant.core.types import (
    DeferralAdmissionOutcome,
    MemoryDecisionKind,
    MemoryKind,
    ParkedBinding,
    StepStatus,
    band_of,
)
from ai_assistant.orchestration.questions import (
    DEFAULT_QUESTION_PAGE,
    AnswerOutcome,
    Question,
    QuestionState,
    question_state,
)
from ai_assistant.orchestration.runner import Disposition

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.protocols import AuditTrail, MemoryStore, PlanStore
    from ai_assistant.core.types import (
        BeliefBand,
        Conversation,
        DeferralAdmission,
        ExecutionState,
        FeedbackEvent,
        FrozenJsonMapping,
        MemoryRecord,
        PermissionDecision,
    )
    from ai_assistant.orchestration.conversations import (
        ConversationDigest,
        ConversationLifecycle,
    )
    from ai_assistant.orchestration.loop import LearningLoop, TurnResult
    from ai_assistant.orchestration.observation import ObservationReport, ObservationStage
    from ai_assistant.orchestration.questions import QuestionStage
    from ai_assistant.orchestration.runner import StepDisposition, StepRunner
    from ai_assistant.orchestration.writes import WriteOutcome

_log = structlog.get_logger(__name__)

_T = TypeVar("_T")

#: Default ceiling on unanswered parked confirmations held in memory (see
#: :class:`Engine`). Generous enough that a real interactive session never reaches
#: it, low enough that an abandoning client cannot exhaust memory.
_DEFAULT_MAX_OUTSTANDING = 1024

#: Default page size for :meth:`Engine.beliefs`. Restated here rather than left to
#: ``MemoryStore.list_beliefs``'s own default so the façade's signature says what a
#: caller gets by saying nothing (ADR-0073 §2's bounded default, 50, matching
#: ``AuditTrail.recent``). It is relayed explicitly on every call, so a store whose
#: default drifted could not silently change what this surface returns.
_DEFAULT_BELIEF_PAGE = 50

#: Default page size for :meth:`Engine.recent_conversations`, restated here for the
#: reason :data:`_DEFAULT_BELIEF_PAGE` is: the façade's signature should say what a
#: caller gets by saying nothing, and it is relayed explicitly on every call so a
#: store whose default drifted could not silently change this surface (ADR-0074
#: §9.3's named default, 50, matching ``AuditTrail.recent``).
_DEFAULT_CONVERSATION_PAGE = 50


def _uuid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class ContinuationToken:
    """An opaque handle to a parked step (ADR-0042 §4).

    The adapter stores this and relays it back on :meth:`Engine.resume`. It
    **must not** interpret, construct, or re-derive its contents: an adapter that
    branched on the token to decide allow/deny would be authoring a permission
    outcome in `interfaces/`, exactly what ADR-0042 §4 forbids. The ``handle`` is
    deliberately meaningless outside the :class:`Engine` instance that minted it —
    it names an entry in that instance's private table, nothing more.

    **Lifetime is process-scoped.** The table lives in the engine object, so a
    handle does not survive a restart. Making the continuation durable across a
    restart is a separate concern ADR-0042's Revisit-if clause ties to #242; until
    then a token is valid only within the process (and the ``Engine``) that
    produced it.
    """

    handle: str


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What a person needs to judge a parked action (ADR-0042 §4).

    The engine assembles this because the adapter may not read the audit trail or
    a ``PermissionDecision`` to recover it (ADR-0042 §6). The values are carried
    **as data, not pre-formatted**: "safe" is target-specific — a parameter value
    holding an ANSI escape or Rich markup is valid data a terminal would interpret
    as a control sequence, but an HTTP front end encodes differently — so escaping
    is each adapter's own job on render (ADR-0042 §4).

    Attributes:
        tool_id: The selected tool's id, human-readable and shown to the user.
        tool_description: What the tool does, from the declaration ruled on.
        parameters: The arguments it would run with, as structured data.
        reason: The recorded ``CONFIRM`` ruling's own ``reason`` — the policy's
            explanation of *why* confirmation is required (an off-device
            disclosure, an unknown cost). Not optional: ``PermissionRuling.reason``
            is "text shown to the user at the moment they decide", so a prompt
            omitting it would drop what the user most needs (ADR-0042 §4).
        token: The opaque continuation to relay back on :meth:`Engine.resume`.
    """

    tool_id: str
    tool_description: str
    parameters: FrozenJsonMapping
    reason: str
    token: ContinuationToken


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """What became of the one step a turn drove (ADR-0042 §3, §4).

    Richer than the raw stage :class:`~ai_assistant.orchestration.runner.StepDisposition`,
    which carries only ``state``, ``decision_id`` and ``tool_id`` — a bare tool id
    is not enough for a human to judge "send email to X" (ADR-0042 §4). This is
    the concrete reason the façade returns its own result type rather than a raw
    stage DTO (ADR-0042 §1).

    Attributes:
        disposition: Which of the five outcomes the step reached.
        state: The durable execution state after the last transition committed.
        tool_id: The tool selected, or ``None`` where none was.
        confirmation: Present **iff** ``disposition`` is
            :attr:`~ai_assistant.orchestration.runner.Disposition.AWAITING_CONFIRMATION`
            — the content and token the adapter renders and relays.
    """

    disposition: Disposition
    state: ExecutionState
    tool_id: str | None = None
    confirmation: Confirmation | None = None


@dataclass(frozen=True, slots=True)
class TurnOutcome:
    """One unit of what a call produced (ADR-0042 §3).

    A frozen dataclass in `orchestration`, like
    :class:`~ai_assistant.orchestration.loop.TurnResult` and
    :class:`~ai_assistant.orchestration.runner.StepDisposition`, for their reason:
    it crosses no *subsystem* boundary, only `interfaces`, which already depends
    on this package. It graduates to ``core`` on the day a subsystem needs to
    receive one (ADR-0042 §1).

    Attributes:
        turn: The turn's goal, context, retrieved memories, plan, and — obliged to
            be surfaced, not swallowed — whether retrieval degraded
            (:attr:`~ai_assistant.orchestration.loop.TurnResult.memory_degraded`).
            ``None`` on a resume driven from a **recovered** park (ADR-0052 §3):
            a confirmation reconstructed from durable state after a restart has no
            live turn — context and retrieved memories are ephemeral and were never
            persisted — so a fabricated ``TurnResult`` would misrepresent what the
            turn saw. The ``step`` — the resolution — is what a resume is for and is
            always present.
        step: The disposition of the step the engine drove, or ``None`` when the
            plan had no step to drive. On a resumption this is the resolved step.
        conversation_id: The conversation this turn ran under (ADR-0074 §2), which
            a client keeps and presents to continue. ``None`` only on a resumption
            whose parked binding no longer resolves to a turn — a park predating
            capture, or one whose conversation the user deleted — which §3 ratifies
            as "not captured at all, and no conversation invented".
        capture_degraded: Whether the exchange went **unrecorded** (ADR-0074 §9
            item 6). The answer is still the answer: capture failure degrades a
            turn rather than failing it, because failing would throw away an answer
            the user already has because the record of it could not be written. But
            it is reported beside
            :attr:`~ai_assistant.orchestration.loop.TurnResult.memory_degraded` and
            not swallowed, because a user whose turns are silently not being
            recorded will not find out until they try to continue.
    """

    turn: TurnResult | None
    step: StepOutcome | None = None
    conversation_id: str | None = None
    capture_degraded: bool = False


class LearnDecision(StrEnum):
    """How memory folded one piece of feedback — the orchestration-level echo of a ruling.

    The façade translates each raw :class:`~ai_assistant.core.types.MemoryIngestResult`
    the loop returns into an :class:`IngestSummary` carrying one of these, so an
    adapter can render what became of the feedback **without importing** ``core``'s
    :class:`~ai_assistant.core.types.MemoryDecisionKind` — the same reason the
    façade returns its own result DTOs rather than raw stage types (ADR-0042 §1).
    One member per ``MemoryDecisionKind`` (:meth:`LearnOutcome.from_results`), named
    for the effect on memory rather than the relation the policy names.
    """

    STORED = "stored"
    """A new memory was written (``ACCEPT``)."""

    REJECTED = "rejected"
    """The proposal was refused; nothing was written (``REJECT``)."""

    REINFORCED = "reinforced"
    """An existing memory was strengthened by folding the proposal into it
    (``REINFORCE``)."""

    SUPERSEDED = "superseded"
    """A prior belief was retired and the correction written in its place
    (``SUPERSEDE``)."""

    DEFERRED = "deferred"
    """The policy wants a human answer before acting; nothing was written yet
    (``ASK_USER``)."""

    STORED_TEMPORARILY = "stored_temporarily"
    """A memory was written with a retention window (``STORE_TEMPORARY``)."""


class QueueOutcome(StrEnum):
    """What became of the question a deferred ruling raised (ADR-0078 §7, §10 item 9).

    The ``orchestration``-level echo of
    :class:`~ai_assistant.core.types.DeferralAdmissionOutcome`, plus the one arm
    ADR-0078 deliberately does **not** close. A closed set with a name because the
    surface must say a *different sentence* for each — and because a single "not
    stored, go answer it" line covering all four would tell a user to answer a
    question that was never queued, which is the same dishonesty ``cli.py``'s old
    comment was written to avoid, arriving from the other direction.
    """

    QUEUED = "queued"
    """The question was parked, and ``question_id`` names it."""

    ALREADY_ASKED = "already_asked"
    """An existing question the key still speaks for stands in the way, and
    ``question_id`` and ``question_state`` say **which and in what state** — a
    declined one to forget, an interrupted answer to dispose of, or one still
    waiting (ADR-0078 §7)."""

    QUEUE_FULL = "queue_full"
    """The answerable queue was at its cap, so nothing was queued and there is no
    question to read. The refusal is **reported, not swallowed**: the cap refuses
    the *new* question rather than evicting an old one, which is safe only because
    the producer still holds what it proposed and can re-propose."""

    NOT_QUEUABLE = "not_queuable"
    """Secret-tier data, which is never queued at all (ADR-0078 §1). ADR-0004 §3
    puts Tier 0 content in the OS keyring and forbids it a committed file, and a
    durable queue is a file — so today's deferral is precisely what keeps such
    content out of storage. This is the one ``ASK_USER`` ADR-0078 leaves
    unanswerable, and it keeps the existing non-answerable line and the existing
    reason."""


@dataclass(frozen=True, slots=True)
class QueuedQuestion:
    """Where a deferred proposal's question went (ADR-0078 §7, §8 reach 1).

    Carried on :class:`IngestSummary` so ``learn`` can point the user at the
    question in the moment they submitted the correction — the reach that closes
    issue #423's own scenario. An ``orchestration`` widening, not a contract change
    (ADR-0042 §1).

    Attributes:
        outcome: Which of the four things happened.
        question_id: The question parked, or the existing one standing in the way.
            ``None`` for ``QUEUE_FULL`` and ``NOT_QUEUABLE``, where there is no
            question to name.
        question_state: The state of the question ``question_id`` names, for the
            same reason :class:`~ai_assistant.orchestration.questions.SuccessorLink`
            carries one: "you declined this" and "an answer to this may be
            committing right now" are different sentences, and naming a question
            without its state would render one as the other.
    """

    outcome: QueueOutcome
    question_id: str | None = None
    question_state: QuestionState | None = None

    @classmethod
    def from_admission(cls, admission: DeferralAdmission) -> QueuedQuestion:
        """Translate a ``core`` admission into the surface's own echo.

        The one place a :class:`~ai_assistant.core.types.DeferralAdmission` is read
        on the learn path, exactly as :meth:`LearnOutcome.from_results` is the one
        place a ``MemoryIngestResult`` is (ADR-0042 §1). It branches on the
        ``outcome`` and **never on an id comparison**, which is the shape ADR-0078 §2
        rejects: comparing the returned id to the one the coordinator minted fails
        the moment a caller retries with the same id, and the surface would announce
        a newly parked question over a suppressed one.
        """
        match admission.outcome:
            case DeferralAdmissionOutcome.ADMITTED:
                outcome = QueueOutcome.QUEUED
            case DeferralAdmissionOutcome.SUPPRESSED:
                outcome = QueueOutcome.ALREADY_ASKED
            case DeferralAdmissionOutcome.REFUSED:
                # No deferral to read at all — reaching for one here is the
                # dereference the three-shape validator exists to prevent.
                return cls(outcome=QueueOutcome.QUEUE_FULL)
            case _:  # pragma: no cover — exhaustive over the enum
                assert_never(admission.outcome)
        deferral = admission.deferral
        if deferral is None:  # pragma: no cover — the validator pins the shapes
            return cls(outcome=outcome)
        return cls(
            outcome=outcome,
            question_id=deferral.id,
            question_state=question_state(deferral.state),
        )


@dataclass(frozen=True, slots=True)
class IngestSummary:
    """What became of one proposal folded from a piece of feedback (ADR-0042 §1).

    The orchestration-level echo of a single
    :class:`~ai_assistant.core.types.MemoryIngestResult`, carrying only what an
    adapter needs to render a one-line confirmation and none of the raw ``core``
    type it was translated from.

    Attributes:
        decision: How memory folded the proposal.
        record_id: The id of the record left live by the write, or ``None`` when
            nothing was stored (a rejection, or a deferral). Carried as opaque data
            an adapter may echo, never interpret.
        reason: The policy's own human-readable justification for the ruling,
            surfaced for transparency — as a confirmation carries its ruling's
            ``reason`` (ADR-0042 §4).
        queued: Where the question a ``DEFERRED`` ruling raised went, and ``None``
            on every other ruling. Present on **every** deferral, including the
            secret-tier one nothing queues, because the distinguishing fact has to
            reach the adapter for it to say anything honest (ADR-0078 §10 item 9).
    """

    decision: LearnDecision
    record_id: str | None
    reason: str
    queued: QueuedQuestion | None = None

    @property
    def stored(self) -> bool:
        """Whether the write left a record live in memory."""
        return self.record_id is not None


@dataclass(frozen=True, slots=True)
class LearnOutcome:
    """What one piece of feedback did to memory (ADR-0042 §1, §3).

    The façade's result for :meth:`Engine.learn`, mirroring :class:`TurnOutcome`: a
    frozen ``orchestration`` dataclass that crosses no *subsystem* boundary, only
    `interfaces`, which already depends on this package. It **translates** the
    ``tuple[MemoryIngestResult, ...]`` the
    :class:`~ai_assistant.orchestration.loop.LearningLoop` returns into a summary an
    adapter renders without touching a raw ``core`` type (:meth:`from_results`),
    the same boundary the other result DTOs hold.

    Attributes:
        results: One :class:`IngestSummary` per proposal the feedback produced, in
            the order they were applied — empty when the feedback proposed no update
            at all.
    """

    results: tuple[IngestSummary, ...]

    @property
    def stored(self) -> int:
        """How many proposals left a record live in memory."""
        return sum(1 for summary in self.results if summary.stored)

    @classmethod
    def from_results(cls, outcomes: tuple[WriteOutcome, ...]) -> LearnOutcome:
        """Translate the write stage's outcomes into an orchestration summary.

        The one place a ``core``
        :class:`~ai_assistant.core.types.MemoryIngestResult` or
        :class:`~ai_assistant.core.types.DeferralAdmission` is read on the learn
        path; everything an adapter sees downstream is ``orchestration``-level
        (ADR-0042 §1).
        """
        return cls(
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
    return QueuedQuestion.from_admission(outcome.admission)


def learn_decision(kind: MemoryDecisionKind) -> LearnDecision:
    """Map a ``core`` memory ruling to its orchestration-level echo (ADR-0042 §1).

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


@dataclass(frozen=True, slots=True)
class Evidence:
    """One citation behind a belief, as a person reads it (ADR-0077 §6).

    **Resolved lazily, at this façade, and never by rewriting the record.** The
    evidence tuple keeps the ids as written; a presenting read resolves each through
    ``MemoryStore.get`` and renders what it finds. Eager rewriting at deletion time
    is refused for a decisive reason rather than an economic one: most evidence loss
    is *expiry*, which retention enforces at read time with no per-record event to
    hook, so an eager mechanism would handle the conversation deletion and silently
    leave every expired citation dangling.

    **It carries no id, deliberately.** ADR-0073 §4's floor is that "a citation the
    surface cannot render as evidence is never rendered *as* evidence — not as a
    reassuring id, not silently dropped", and an adapter that never receives the id
    cannot render one as though it were the warrant.

    Attributes:
        content: The cited record's own canonical text, or ``None`` where the
            citation no longer resolves — a **tombstone**. The tombstone says an
            evidence item stood here and is gone, and deliberately does not say what
            it was, nor whether it was *deleted* or merely *expired*: the read cannot
            tell those apart, and the user's question — "is there still something
            behind this?" — is answered by absence either way.
    """

    content: str | None = None

    @property
    def lost(self) -> bool:
        """Whether this citation no longer resolves."""
        return self.content is None


@dataclass(frozen=True, slots=True)
class Belief:
    """One live belief, as a person reads it (ADR-0073 §4, §7).

    A frozen ``orchestration`` dataclass beside :class:`TurnOutcome` and
    :class:`IngestSummary` and for their reason: it crosses no *subsystem*
    boundary, only `interfaces`, which already depends on this package (ADR-0042
    §1). It is deliberately **not** a raw
    :class:`~ai_assistant.core.types.MemoryRecord`, and the deciding reason is not
    tidiness — :func:`~ai_assistant.core.types.band_of` is applied *here*, once, in
    the engine (:meth:`from_record`), because an adapter doing it would put
    ADR-0072 §1's projection into `interfaces/`. It also flattens the four-member
    discriminated union an adapter would otherwise branch over, and drops ``score``,
    which is meaningless on a path where nothing was ranked (ADR-0073 §2).

    **What it carries is exactly ADR-0073 §4's list, and the omissions are ruled
    rather than incidental.** The kind-specific fields (a preference's ``strength``,
    an episode's ``participants``) are not carried: ``content`` is the store's own
    canonical text rendering of every kind. ``SemanticMemory.valid_until`` is not
    carried either, and is named here because it shares a name with
    :attr:`valid_until` below while meaning something else — a content-declared
    fact expiry, not the operational live-belief window.

    **The evidence citations are carried as resolved values and never as ids**,
    which is ADR-0073 §4's floor made structural: a derived belief must not be
    presented as carrying a warrant the surface cannot show, and "a citation the
    surface cannot render as evidence is never rendered *as* evidence — not as a
    reassuring id, not silently dropped." An adapter that never receives the ids
    cannot render one as though it were the evidence. ADR-0073 §4 deferred resolving
    them **with a gate** — a precondition of the first producer of derived beliefs
    shipping (#431) — and ADR-0077 §6 discharges it: :attr:`evidence` is that field,
    and a citation that no longer resolves arrives as an explicit tombstone.

    Attributes:
        id: The record's id, opaque, and what :meth:`Engine.forget` names.
        band: The standing the belief is held with (ADR-0072 §2), projected from
            its provenance source. Never omitted, and never left to be implied by
            position (ADR-0073 §4).
        kind: Which of the four typed memories this is — what the ``kinds`` filter
            selects on, and the difference between reading a preference and a fact.
        content: The canonical text rendering of the belief.
        confidence: How strongly it is held, in ``[0, 1]`` — **the presented
            value**, already adjusted for lost support (:func:`presented_confidence`,
            ADR-0077 §6). The stored number is not carried, and that is the point:
            every surface that states a confidence must state the adjusted one, and
            a DTO offering both would let two surfaces quote different numbers for
            one belief. The record itself is untouched, and ``export`` still carries
            it as stored.
        evidence: One entry per citation, in the order the record wrote them —
            resolved to readable content, or a tombstone where it no longer
            resolves. Empty for an assertion, whose warrant is the user's own word
            (ADR-0038 §1a) and needs no citation.
        last_updated: The transaction stamp — when *the assistant* last revised this
            belief (ADR-0045 §3) — which is also the enumeration's sort key. It is
            **our** clock and not a source's: an attested belief synced on Tuesday
            from a calendar that said so on Monday carries Tuesday here, so a
            renderer must not offer this as when a source said so (ADR-0073 §4).
        valid_until: The end of the belief's validity window, where one is set;
            ``None`` where the window is open. Every listed belief is live by
            construction, so an open window carries no information and a set end
            does ("believed until…").
    """

    id: str
    band: BeliefBand
    kind: MemoryKind
    content: str
    confidence: float
    last_updated: datetime
    evidence: tuple[Evidence, ...] = ()
    valid_until: datetime | None = None

    @property
    def evidence_count(self) -> int:
        """How many citations stand behind it, resolved or not."""
        return len(self.evidence)

    @property
    def lost_evidence(self) -> int:
        """How many of its citations no longer resolve."""
        return sum(1 for item in self.evidence if item.lost)

    @property
    def unsupported(self) -> bool:
        """Whether every citation behind it has gone (ADR-0077 §6).

        A belief in this state is **held, marked and answerable — not auto-retired**:
        retiring it would be the cascade under a softer name, and it may be perfectly
        true. It sits at its effective floor, ``forget`` still destroys it, and the
        user asserting it themselves still supersedes it into the asserted band.

        ``False`` for a belief that cites nothing at all: an assertion is not
        unsupported, it is supported by the user's own word.
        """
        return bool(self.evidence) and all(item.lost for item in self.evidence)

    @classmethod
    def from_record(cls, record: MemoryRecord, evidence: tuple[Evidence, ...] = ()) -> Belief:
        """Project one stored record into the belief a person reads (ADR-0073 §7).

        The one place a ``core``
        :class:`~ai_assistant.core.types.MemoryRecord` is read on the inspection
        path, and the one place :func:`~ai_assistant.core.types.band_of` is applied
        — everything an adapter sees downstream is ``orchestration``-level, exactly
        as :meth:`LearnOutcome.from_results` holds that boundary on the learn path.

        ``evidence`` is resolved by the caller, because resolving it is a *store
        read* and this is a pure projection. It must carry one entry per citation on
        the record, in order: the presented confidence is computed from how many of
        them resolved, so a caller that dropped the lost ones would report a belief
        as fully supported at the exact moment it stopped being.
        """
        provenance = record.provenance
        resolved = sum(1 for item in evidence if not item.lost)
        return cls(
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
        )


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    """One conversation, as a person choosing which to continue reads it (ADR-0074 §2).

    A frozen ``orchestration`` dataclass beside :class:`Belief` and for its reason:
    it crosses no *subsystem* boundary, only `interfaces`, which already depends on
    this package (ADR-0042 §1). It is deliberately not a raw
    :class:`~ai_assistant.core.types.Conversation` — ``deleted_at`` has no meaning
    on this surface, because a stamped conversation never reaches it.

    Attributes:
        id: The opaque id ``assistant ask --conversation`` takes. Server-minted,
            encoding nothing; a client holds this and nothing else.
        started_at: When the conversation record was created.
        last_active_at: When someone was last here — set at creation and refreshed
            whenever a turn begins. **This is the listing's sort key**, and never
            ``last_turn_at``: ordering by "has a turn landed" would sink a
            conversation the user opened a minute ago below one they abandoned last
            week.
        last_turn_at: When a turn was last *recorded*, or ``None`` if none has
            been. A different fact from activity, and the one that tells an empty
            conversation from one whose first turn landed instantly.
    """

    id: str
    started_at: datetime
    last_active_at: datetime
    last_turn_at: datetime | None = None

    @classmethod
    def from_record(cls, conversation: Conversation) -> ConversationSummary:
        """Project one stored conversation into the summary a person reads."""
        return cls(
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

    def __init__(  # noqa: PLR0913 — one parameter per injected collaborator plus three knobs
        self,
        *,
        loop: LearningLoop,
        runner: StepRunner,
        plans: PlanStore,
        trail: AuditTrail,
        memory: MemoryStore,
        conversations: ConversationLifecycle,
        observation: ObservationStage,
        questions: QuestionStage,
        closers: Sequence[Callable[[], Awaitable[None]]] = (),
        id_factory: Callable[[], str] = _uuid,
        max_outstanding_confirmations: int = _DEFAULT_MAX_OUTSTANDING,
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
            closers: The resources the façade owns, as async close callables, in
                the order :meth:`aclose` must run them. The composition root hands
                these over so the façade is the defined owner that releases every
                connection on shutdown (ADR-0042 §2). Empty when the façade owns
                nothing (its collaborators are all in-memory).
            id_factory: Supplies opaque continuation-token handles; injectable so
                a test can assert a stable handle.
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
        self._conversations = conversations
        self._observation = observation
        self._questions = questions
        self._closers = tuple(closers)
        self._id_factory = id_factory
        self._max_outstanding = max_outstanding_confirmations
        self._drain_timeout = drain_timeout
        self._parked: dict[str, _Parked] = {}
        self._reserved: set[str] = set()
        self._recovery_lock = asyncio.Lock()
        self._inflight: set[asyncio.Task[Any]] = set()
        self._closing = False
        self._shutdown: asyncio.Task[None] | None = None

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

        Idempotent, and safe to call more than once: both sweeps are re-runnable by
        construction, and every drop is re-checked under the store's own
        per-conversation exclusion.

        Raises:
            RuntimeError: If the engine is shutting down.
            ConversationStoreError: If the conversation index cannot be read or
                written. A sweep that swallowed a store fault to keep running would
                report success over work it never did, so it aborts loudly — an id
                that is merely *gone* is a no-op and does not abort it.
            MemoryStoreError: If an episode a deletion must destroy could not be.
        """
        self._reject_if_closing()
        return await self._tracked(self._start())

    async def _start(self) -> None:
        """Finish pending deletions, then reclaim what retention has emptied."""
        await self._conversations.sweep_deletions()
        await self._conversations.reclaim()

    async def converse(
        self,
        utterance: str,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, threaded to the seam which owns the deadline (ADR-0029 §4)
        conversation_id: str | None = None,
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
        return await self._tracked(
            self._converse(utterance, timeout=timeout, conversation_id=conversation_id)
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
        return await self._tracked(self._resume(token, approved=approved, timeout=timeout))

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
        return await self._tracked(self._learn(event))

    async def observe(self, conversation_id: str | None = None) -> ObservationReport:
        """Distil beliefs from a conversation's recent turns (ADR-0077 §8).

        The accumulation leg, and an **explicit operation**: it is not wired into
        the turn, nothing polls it, and no background task runs it. Four reasons,
        in the order they bind (ADR-0077 §8): nothing is waiting on an observation
        while a turn is, and a one-shot process has no "after the answer" to hide
        the round trip in; the roadmap sequences leg 4's soundness work against
        volume, and a per-turn trigger *is* volume on the day it merges; the first
        producer that sends accumulated history to a model should not run without
        the user knowing; and leg 5's scheduler becomes a second caller of this
        same operation, so cadence becomes configuration rather than a contract
        change.

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
        return await self._tracked(self._observation.observe(conversation_id))

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = _DEFAULT_BELIEF_PAGE,
        offset: int = 0,
    ) -> tuple[Belief, ...]:
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
        snapshot_bands = None if bands is None else tuple(bands)
        snapshot_kinds = None if kinds is None else tuple(kinds)
        return await self._tracked(
            self._beliefs(bands=snapshot_bands, kinds=snapshot_kinds, limit=limit, offset=offset)
        )

    async def belief(self, record_id: str) -> Belief | None:
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
        return await self._tracked(self._belief(record_id))

    async def forget(self, record_id: str) -> bool:
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
        return await self._tracked(self._memory.delete(record_id))

    async def questions(
        self, *, limit: int = DEFAULT_QUESTION_PAGE, offset: int = 0
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
        return await self._tracked(self._questions.questions(limit=limit, offset=offset))

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_QUESTION_PAGE, offset: int = 0
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
        return await self._tracked(
            self._questions.interrupted_questions(limit=limit, offset=offset)
        )

    async def answer(self, question_id: str, *, accept: bool) -> AnswerOutcome:
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
        return await self._tracked(self._questions.answer(question_id, accept=accept))

    async def forget_question(self, question_id: str) -> bool:
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
        return await self._tracked(self._questions.forget_question(question_id))

    async def recent_conversations(
        self, *, limit: int = _DEFAULT_CONVERSATION_PAGE, offset: int = 0
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
        return await self._tracked(self._recent_conversations(limit=limit, offset=offset))

    async def _recent_conversations(
        self, *, limit: int, offset: int
    ) -> tuple[ConversationSummary, ...]:
        """Relay the listing to the stage and project each record."""
        listed = await self._conversations.recent(limit=limit, offset=offset)
        return tuple(ConversationSummary.from_record(one) for one in listed)

    async def conversation(self, conversation_id: str) -> ConversationDigest | None:
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
        return await self._tracked(self._conversations.digest(conversation_id))

    async def forget_conversation(self, conversation_id: str) -> bool:
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
        return await self._tracked(self._conversations.delete(conversation_id))

    async def pending_confirmations(self) -> list[Confirmation]:
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
        return await self._tracked(self._pending_confirmations())

    async def _pending_confirmations(self) -> list[Confirmation]:
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
            return recovered

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
          re-raise only then, uniformly across all five stores. So a cancelled
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
        _log.info("shutdown_drain_budget_exceeded", cancelling=len(pending))
        for task in pending:
            task.cancel()
        # Unbounded, and `return_exceptions=True` so a cancelled task's
        # `CancelledError` is a *result* here rather than something that aborts the
        # gather and skips its siblings. Every one must complete before a closer runs.
        await asyncio.gather(*pending, return_exceptions=True)

    async def _tracked(self, coro: Awaitable[_T]) -> _T:
        """Run ``coro`` as a tracked, shielded task, so shutdown can drain it.

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
        """
        task: asyncio.Task[_T] = asyncio.ensure_future(coro)
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        return await asyncio.shield(task)

    def _reject_if_closing(self) -> None:
        """Refuse new work once shutdown has begun (ADR-0042 §2 stops accepting).

        Raises:
            RuntimeError: If :meth:`aclose` has been entered.
        """
        if self._closing:
            msg = "the engine is shutting down and is not accepting new work"
            raise RuntimeError(msg)

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
            step = self._step_outcome(turn, disposition, handle=handle)
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
                    "from an earlier run of the process, or already resolved"
                )
                raise PlanningError(msg)
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
            step = self._step_outcome(parked.turn, disposition, handle=None)
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
        return LearnOutcome.from_results(outcomes)

    async def _beliefs(
        self,
        *,
        bands: tuple[BeliefBand, ...] | None,
        kinds: tuple[MemoryKind, ...] | None,
        limit: int,
        offset: int,
    ) -> tuple[Belief, ...]:
        """Relay the enumeration to the store and project each record (ADR-0073 §7).

        The filters arrive already materialised by :meth:`beliefs`; the page's order
        and membership are the store's, and this adds no re-ordering, no re-filtering
        and no count of its own.
        """
        records = await self._memory.list_beliefs(
            bands=bands, kinds=kinds, limit=limit, offset=offset
        )
        return tuple([await self._project(record) for record in records])

    async def _belief(self, record_id: str) -> Belief | None:
        """Read one live record and project it, or report that there is none."""
        record = await self._memory.get(record_id)
        return None if record is None else await self._project(record)

    async def _project(self, record: MemoryRecord) -> Belief:
        """Resolve the record's citations, then project it (ADR-0077 §6).

        **Lazily, here, and without rewriting anything.** The evidence tuple keeps
        the ids as written and each is resolved through
        :meth:`~ai_assistant.core.protocols.MemoryStore.get` at the moment of
        presentation, so a citation the user destroyed — or one that expired under a
        retention horizon, which is the *commoner* case and has no event to hook —
        renders as a tombstone rather than a dangling id. Nothing is written: the
        record graph is frozen (ADR-0068), and losing evidence is not the producer
        changing its mind.

        Resolution happens at this façade rather than in `interfaces/`, which golden
        rule 3 keeps thin and which ADR-0072 §7 already refused to give a
        live-at-now computation.

        The cost is a ``get`` per citation per presented belief, bounded by the page
        (ADR-0073 §2's default of 50) and by evidence tuples that are small by
        construction. Accepted for now, and it is where ADR-0074 §5's declined
        ``get_many`` gets its second consumer — revisited at the hub.
        """
        resolved: list[Evidence] = []
        for cited in record.provenance.evidence:
            found = await self._memory.get(cited)
            resolved.append(Evidence(content=None if found is None else found.content))
        return Belief.from_record(record, tuple(resolved))

    def _step_outcome(
        self, turn: TurnResult | None, disposition: StepDisposition, *, handle: str | None
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
            token=ContinuationToken(handle),
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
            token=ContinuationToken(handle),
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
    "Belief",
    "Confirmation",
    "ContinuationToken",
    "ConversationSummary",
    "Engine",
    "Evidence",
    "IngestSummary",
    "LearnDecision",
    "LearnOutcome",
    "QueueOutcome",
    "QueuedQuestion",
    "StepOutcome",
    "TurnOutcome",
    "presented_confidence",
]
