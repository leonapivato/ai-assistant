"""The answer path: claim, apply, resolve — and the surface that shows a question.

ADR-0078 §8 and §9. A deferred memory decision is a durable question, and this is
where it reaches the user and where their answer is committed. Two halves:

* **The reads.** :meth:`QuestionStage.questions` enumerates the answerable
  questions and :meth:`QuestionStage.interrupted_questions` the ones whose answer
  was begun and whose outcome was never recorded. The two stay **separate all the
  way to the surface, never merged into one list** (§8): an interrupted question is
  not answerable, and offering it beside the ones that are would present a claim
  that cannot be taken. Each is projected into a :class:`Question`, which is where
  :func:`~ai_assistant.core.types.band_of` is applied — **once**, here — so no
  adapter classifies anything (ADR-0073 §7).
* **The write.** :meth:`QuestionStage.answer` runs ADR-0078 §9's sequence, **claim →
  ingest → resolve**, spanning two stores that share no transaction. Claiming
  *first* is what makes an answer apply at most once: without it two concurrent
  answers both read a ``PENDING`` deferral, both ingest, and **both write**, with
  only one winning the terminal compare-and-set while the loser's memory mutation
  stands — a duplicate correction produced by ordinary concurrent use, with no crash
  anywhere.

**The claim is one-way, and that is what keeps the guarantee true after a crash.**
There is no ``release``, no lease, no timeout and deliberately **no verb here that
claims to retry an apply** (§2, §8): anything able to re-open a *stranded* claim
could re-open a **live** one, letting a second apply run beside the first. So a
process that dies inside a claim leaves the question ``APPLYING`` forever, the
surface says *an answer was begun and its outcome is not recorded*, and the user's
recovery is §9's two steps — dispose of it with :meth:`QuestionStage.forget_question`,
then read the belief and correct it again if it is missing.

**This stage is the only producer of a**
:class:`~ai_assistant.core.types.UserConfirmation`, **and it produces one only from
a deferral it has claimed** (§3's third composition-root obligation). Unlike the
other two that obligation is not merely a wiring rule: a second producer of
confirmations is a second thing that can authorise retiring a user's assertion,
which is the one authority in this system that has never been delegable. Nothing in
the writer's checks looks for a claim, so a helper that assembled a confirmation
from a pending deferral's id, key and conflict ids — all of which reads expose —
could retire a ``USER_ASSERTED`` record while every answer-path test still passed.
It is a structural property, so ``tests/orchestration/test_confirmation_authority.py``
asserts it structurally.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import DeferralStoreError, MemoryStoreError
from ai_assistant.core.types import (
    DeferralAdmissionOutcome,
    DeferralState,
    MemoryDecisionKind,
    MemoryKind,
    UserConfirmation,
    band_of,
)
from ai_assistant.orchestration.writes import admit_question

if TYPE_CHECKING:
    from collections.abc import Callable

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import DeferralStore, MemoryStore, MemoryWriter
    from ai_assistant.core.types import (
        BeliefBand,
        DeferralClaim,
        DeferredProposal,
        MemoryIngestResult,
        MemoryUpdateProposal,
    )

#: Default page size for both enumerations, restated here rather than left to the
#: store's own default so the façade's signature says what a caller gets by saying
#: nothing — and relayed explicitly on every call, so a store whose default drifted
#: could not silently change what this surface returns (ADR-0073 §2, §8).
DEFAULT_QUESTION_PAGE = 50


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class QuestionState(StrEnum):
    """Where a question stands, as a surface says it (ADR-0078 §8).

    The ``orchestration``-level echo of
    :class:`~ai_assistant.core.types.DeferralState`, so an adapter can render a
    question without importing ``core`` — the same boundary every other result DTO
    on this façade holds (ADR-0042 §1). One member per ``DeferralState``
    (:func:`question_state`), named for what the user can *do* rather than for the
    row's internal label.
    """

    OPEN = "open"
    """Answerable: nobody has begun an answer (``PENDING``)."""

    INTERRUPTED = "interrupted"
    """An answer was begun and its outcome is not recorded (``APPLYING``).

    Not "failed" and not "retryable": the system does **not** know whether the
    memory write landed, which is the actual epistemic situation (ADR-0078 §9).
    """

    DECLINED = "declined"
    """The user said no, and the record is retained so they are not re-asked."""

    APPLIED = "applied"
    """The answer was applied and a record is live (``ACCEPTED``)."""

    STALE = "stale"
    """The answer arrived and the belief it was about no longer applied."""

    REDEFERRED = "redeferred"
    """The answer was used and raised a further question the record names."""


def question_state(state: DeferralState) -> QuestionState:
    """Map a ``core`` deferral state to its surface echo (ADR-0042 §1).

    Total by construction, in the shape
    :func:`~ai_assistant.orchestration.engine.learn_decision` already uses: a new
    ``DeferralState`` fails type-checking here until it is given an echo, rather
    than silently losing its rendering.
    """
    match state:
        case DeferralState.PENDING:
            return QuestionState.OPEN
        case DeferralState.APPLYING:
            return QuestionState.INTERRUPTED
        case DeferralState.REJECTED:
            return QuestionState.DECLINED
        case DeferralState.ACCEPTED:
            return QuestionState.APPLIED
        case DeferralState.STALE:
            return QuestionState.STALE
        case DeferralState.REDEFERRED:
            return QuestionState.REDEFERRED
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(state)


@dataclass(frozen=True, slots=True)
class Retirement:
    """One record a question's answer would retire (ADR-0078 §8).

    **Not decoration: this is the exact scope the answer authorises** (§5). The
    content is resolved through the ratified ``MemoryStore.get``, which hides a
    closed window (ADR-0045 §6) — so a conflict retired since the question was asked
    does not resolve, and renders as *no longer held* rather than being omitted. The
    user should be told that the thing they would be overruling is already gone.

    Attributes:
        record_id: The conflict's id, opaque data an adapter may echo.
        content: What that record says, or ``None`` when it is no longer held.
    """

    record_id: str
    content: str | None


@dataclass(frozen=True, slots=True)
class SuccessorLink:
    """A question raised by an answer, and the state it is in (ADR-0078 §7, §9).

    The state is carried because **naming it without its state would be the failure
    §9 names**: a ``PENDING`` successor is a question the user can go and answer, a
    ``DECLINED`` one means they already declined this and must forget it to be asked
    again, and an ``INTERRUPTED`` one is another interrupted answer. Calling any of
    those "the follow-on question" would tell a user their answer raised something
    askable when it raised nothing they can act on.
    """

    id: str
    state: QuestionState


@dataclass(frozen=True, slots=True)
class Question:
    """A deferred memory decision, as the user is shown it (ADR-0078 §8).

    A frozen ``orchestration`` dataclass beside :class:`Belief`,
    :class:`Confirmation` and :class:`TurnOutcome`, for their reason (ADR-0042 §1:
    it crosses no *subsystem* boundary, only `interfaces`) and for ADR-0073 §7's
    deciding reason — ``band_of`` is applied here, in the engine, so no adapter
    classifies anything.

    Attributes:
        id: The question's id, which :meth:`QuestionStage.answer` and
            :meth:`QuestionStage.forget_question` take.
        state: Where it stands, and therefore what the user can do about it.
        content: What accepting would have the assistant believe.
        kind: Which typed memory it would establish.
        band: The band the record **would** enter if accepted — a conditional, never
            a belief held. A pending question is not a belief of any band (§1):
            ``band_of`` applied to its proposal says only where it would land.
        rationale: Why the proposal was made, in its producer's words.
        reason: **Why the user is being asked** — the ``ASK_USER`` ruling's own
            non-optional ``reason``.
        retires: What accepting would retire, resolved to content (:class:`Retirement`).
        asked_at: When the question was admitted.
        expires_at: When it stops being answerable, or ``None`` under the user's
            deliberate "ask me forever".
        successor: The question this one's answer already raised, when it has one —
            the state a cancellation caught after a re-deferral admitted a successor
            leaves behind (§9).
    """

    id: str
    state: QuestionState
    content: str
    kind: MemoryKind
    band: BeliefBand
    rationale: str
    reason: str
    retires: tuple[Retirement, ...]
    asked_at: datetime
    expires_at: datetime | None
    successor: SuccessorLink | None = None


class AnswerKind(StrEnum):
    """What answering a question produced (ADR-0078 §8).

    Four outcomes the ADR names — *applied*, *rejected*, *stale* and *re-deferred* —
    plus the one an answer to a question that is not open produces. Rendering a
    re-deferral as a failure would be a lie in a small place, so it is its own
    member and carries the successor.
    """

    APPLIED = "applied"
    """The correction landed; ``record_id`` names what is now live."""

    REJECTED = "rejected"
    """Nothing was written. Either the user declined, or the policy ruled
    ``REJECT`` on the re-submitted proposal — a conforming policy that is not the
    default one may, and the mapping to a terminal state is **total** so such an
    answer resolves rather than stranding (ADR-0078 §2)."""

    STALE = "stale"
    """The proposal's own validity window had closed by the answer instant, so
    accepting would have written a belief born dead (ADR-0078 §6). Distinct from a
    lapsed deadline: telling a user who answered promptly they were too slow would
    be the wrong sentence."""

    REDEFERRED = "redeferred"
    """The answer was **used** and raised a further question, because re-ingesting
    surfaced an assertion the user was never shown (ADR-0078 §5a). A completed
    answer, not a failed one."""

    NOT_OPEN = "not_open"
    """That question is not open — absent, lapsed, already being answered, or
    already answered. Nothing was written."""


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    """What one answer did (ADR-0078 §8, §9).

    Attributes:
        kind: Which of the five outcomes happened.
        question_id: The question that was answered, echoed back.
        record_id: What an applied answer left live; ``None`` otherwise.
        successor: The question a re-deferred answer raised — newly admitted, or the
            already-open one it collapsed onto — with the state that decides what to
            say about it. ``None`` when no successor could be queued.
        successor_refused: Whether a re-deferral could queue **no** follow-on
            question at all, because the queue was full and this admission had no
            exemption to spend (which happens only where the parent was destroyed
            mid-apply, since an exempt admission never consults the cap). Reporting
            it as an ordinary re-deferral would claim a question was asked when none
            was, which is the one sentence ADR-0078 cannot write.
        disposed: Whether the question was **destroyed while its answer was being
            applied**, so the bookkeeping found nothing. A true statement the caller
            reports; what it reports *about the answer* comes from the ingest, which
            it still holds, and never from the failed bookkeeping (ADR-0078 §9).
    """

    kind: AnswerKind
    question_id: str
    record_id: str | None = None
    successor: SuccessorLink | None = None
    successor_refused: bool = False
    disposed: bool = False


class QuestionStage:
    """Reads the deferred-question queue, and commits the user's answers."""

    def __init__(
        self,
        *,
        writer: MemoryWriter,
        deferrals: DeferralStore,
        memory: MemoryStore,
        now: Clock = _utcnow,
        id_factory: Callable[[], str] = _uuid,
    ) -> None:
        """Wire the answer path from the contracts its sequence spans.

        Three composition-root obligations ride on this constructor, and ADR-0078 §3
        states them because no type expresses any of them:

        1. **``deferrals`` is the very instance the write stage enqueues into.** A
           second instance queues questions nobody can answer.
        2. **``writer`` writes to ``memory``** — ADR-0028 §4's existing same-store
           rule, and the answer path is a second place it must hold: applying a
           confirmed retirement against a different store would retire nothing while
           reporting success. ``memory`` is also read directly, to resolve a
           question's frozen conflict ids to the content the user is shown, so the
           two must be the same store or the surface would show conflicts the apply
           cannot reach.
        3. **This stage is the only producer of a ``UserConfirmation``**, from a
           deferral it has claimed. Held by a structural test, not by wiring.

        Args:
            writer: The ratified write path an accepted answer is re-submitted
                through. Conflict detection, the policy, the atomic applier and the
                full-set retirement rule all run unchanged — resolving by
                re-ingesting is what makes this path inherit ADR-0079 §1's
                completeness obligation and ADR-0080 §1's clamp by construction
                rather than by restatement (ADR-0078 §5).
            deferrals: The durable queue.
            memory: Long-term memory, read to resolve what an answer would retire.
            now: Clock stamping a confirmation and judging the proposal's own
                validity window at the answer instant (ADR-0078 §6). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
                reading is a ``DeferralStoreError`` from the stage that read it —
                `orchestration` has no error of its own, so ADR-0026 §4 gives the
                failure to the store this stage is about.
            id_factory: Mints a successor question's id on the re-deferral path;
                injectable so a test can force a collision.
        """
        self._writer = writer
        self._deferrals = deferrals
        self._memory = memory
        self._clock = checked_clock(now, owner="QuestionStage")
        self._id_factory = id_factory

    async def questions(
        self, *, limit: int = DEFAULT_QUESTION_PAGE, offset: int = 0
    ) -> tuple[Question, ...]:
        """Enumerate the **answerable** questions, oldest first (ADR-0078 §2, §7, §8).

        The reach for a question no ``learn`` was in flight to render — which is
        every question the observer raises. Membership and order are the store's
        ratified contract, not this stage's: ``PENDING`` and before ``expires_at``,
        judged against one clock reading, ``deferred_at`` ascending with ``id``
        breaking ties. **Oldest first**, because the head of the queue is the
        question whose admission is blocking a newer one, so a full cap is legible
        from the first page.

        Args:
            limit: Page size, bounded by default for ADR-0073 §8's reason — it keeps
                an unbounded read of a Tier 1 store from being what a caller gets by
                saying nothing.
            offset: How many ordered rows to skip.

        Returns:
            The page, projected. Empty when nothing is waiting.

        Raises:
            ValueError: If ``limit`` or ``offset`` falls outside ``[0, 2**63)``, as
                the store refuses rather than clamps. Not an ``AssistantError``, so
                an adapter letting a user supply either must refuse an out-of-range
                value at its own parse boundary.
            DeferralStoreError: If the queue cannot be read.
            MemoryStoreError: If a conflict's content cannot be read.
        """
        return await self._page(await self._deferrals.pending(limit=limit, offset=offset))

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_QUESTION_PAGE, offset: int = 0
    ) -> tuple[Question, ...]:
        """Enumerate the questions whose answer was begun and never recorded (§9).

        A **second enumeration** rather than a flag on :meth:`questions`, all the way
        to the surface (ADR-0078 §8): two different questions behind one argument is
        one argument doing two jobs, and an interrupted question is not answerable,
        so offering it beside the ones that are would present a claim that cannot be
        taken.

        It exists because after a restart nothing holds an id to look one up by —
        without it the stranded question is unreachable, which is the vanishing
        ADR-0078 is about, one state along. Disposing of such a question is the
        user's **first** recovery step (:meth:`forget_question`), because while the
        row lives it holds its ``question_key`` and a re-proposal of the same
        correction would collide with it and be handed back an id nothing can claim.

        Args:
            limit: Page size, bounded by default as :meth:`questions` is.
            offset: How many ordered rows to skip.

        Returns:
            The page, projected, in :meth:`questions`' order. The two reads are
            disjoint by the store's contract.

        Raises:
            ValueError: As :meth:`questions` refuses a malformed page argument.
            DeferralStoreError: If the queue cannot be read.
            MemoryStoreError: If a conflict's content cannot be read.
        """
        return await self._page(await self._deferrals.interrupted(limit=limit, offset=offset))

    async def forget_question(self, question_id: str) -> bool:
        """Destroy one question and everything it holds (ADR-0078 §8, §9; ADR-0007).

        Relays ``DeferralStore.delete`` and nothing more. **Unconditional**, like
        every other deletion on this façade: no state refuses it, ``APPLYING``
        included, because ADR-0073 §9 declines a classification-conditional delete
        and an internal-state-conditional one is the same mistake with a different
        label — and a refusal would be *permanent* for a stranded claim, so a user
        could never destroy an interrupted question at all.

        It is also step 1 of the only recovery a stranded answer has. Deleting
        destroys the ``question_key`` with the row, which is what unblocks a
        re-``learn`` of the same correction. Step 2 is ``beliefs`` then ``learn``,
        the correction path ADR-0073 §6 says is the only one — and deliberately
        **not** a retry: the system does not know whether the write landed, and a
        verb implying it does would be the one dishonest line on this surface.

        Args:
            question_id: The question the user named, taken as opaque.

        Returns:
            ``True`` if a row was destroyed, ``False`` if the id named nothing.

        Raises:
            DeferralStoreError: If the queue cannot be written.
        """
        return await self._deferrals.delete(question_id)

    async def answer(self, question_id: str, *, accept: bool) -> AnswerOutcome:
        """Answer one question: ``claim`` → ``ingest`` → ``resolve`` (ADR-0078 §9).

        **Answering is binary.** There is no third "neither — here's the real
        answer": an amendment is a new proposal, and ``learn`` already is one
        (ADR-0073 §6), so a free-text answer would be a second correction path
        wearing a confirmation's clothes.

        **A rejection needs no claim**, because it writes nothing: it is a single
        compare-and-set from ``PENDING`` straight to ``REJECTED``, and a concurrent
        second rejection simply reports the question as not open. The record is then
        *retained*, which is what makes ADR-0078 §7's dedup honest — without it a
        chatty producer re-proposes tomorrow and the user is asked something they
        already declined. Changing their mind is two steps: forget the question,
        then ``learn`` again.

        **An accept claims first.** That is the single-resolution invariant moved one
        step earlier than ADR-0044 §2 puts it, so that it covers the *apply* rather
        than only the bookkeeping.

        **An ``ingest`` that raises leaves the question ``APPLYING``, and that is a
        decision rather than an oversight.** It is an ordinary path, not only a
        crash: a deferred derived proposal can cite evidence that resolved when the
        question was queued and has since been deleted, so the writer raises before
        writing anything; a store failure raises at a moment this stage cannot
        classify. In both the exception **propagates unchanged** — no error transport
        is invented here (ADR-0028 §5) — and the claim is neither resolved nor
        released nor deleted. Resolving it terminally to tidy up is the tempting move
        and the wrong one: for a store failure this stage does not know whether the
        write landed, so ``ACCEPTED`` and ``REJECTED`` are both potentially false and
        stamping either is the lie §9 exists to prevent. The answer lands where
        everything indeterminate lands — :meth:`interrupted_questions`.

        **Cancellation gets one rule for the whole sequence.** A cancelled ``answer``
        propagates its ``CancelledError`` (ADR-0060) and this stage **applies nothing
        further and cleans nothing up**, wherever it lands. ADR-0060 makes a
        cancelled call's effect indeterminate *to its caller*, so no corrective
        action is available: every one of them needs exactly the inference the caller
        may not make. The durable state is right without it, because each step's own
        compare-and-set is atomic — whatever committed is committed, and the row is
        then terminal, still ``PENDING``, or stranded ``APPLYING``, all states this
        design already renders honestly. What an implementation must **not** do is
        "repair" the row, because it cannot tell which it has and both are already
        correct.

        Args:
            question_id: The question to answer, taken as opaque.
            accept: The user's answer. ``True`` re-submits the proposal under the
                authority the claim mints; ``False`` declines it.

        Returns:
            What the answer did, including a re-deferral's successor question.

        Raises:
            MemoryStoreError: As the writer raises. The claim is left ``APPLYING``.
            UnresolvedEvidenceError: As the writer raises when the cited evidence has
                been deleted between the question and the answer. Likewise stranding.
            DeferralStoreError: If the queue cannot be read or written, or a
                successor question could not be minted.
        """
        if not accept:
            return await self._reject(question_id)
        claim = await self._deferrals.claim(question_id)
        if claim is None:
            # Absent, lapsed, or no longer PENDING — "that question is not open",
            # and nothing is written (ADR-0078 §9 step 1).
            return AnswerOutcome(kind=AnswerKind.NOT_OPEN, question_id=question_id)
        return await self._apply(claim)

    async def _reject(self, question_id: str) -> AnswerOutcome:
        """Decline a question with the one unclaimed transition (ADR-0078 §9)."""
        recorded = await self._deferrals.resolve(
            question_id, claim_id=None, state=DeferralState.REJECTED
        )
        if not recorded:
            return AnswerOutcome(kind=AnswerKind.NOT_OPEN, question_id=question_id)
        return AnswerOutcome(kind=AnswerKind.REJECTED, question_id=question_id)

    async def _apply(self, claim: DeferralClaim) -> AnswerOutcome:
        """Re-submit the claimed proposal, then record what the ingest produced."""
        deferral = claim.deferral
        now = self._now_utc()
        # ADR-0078 §6's staleness check: the proposal's own **envelope** window, read
        # at the answer instant. A closed one means accepting would write a belief
        # every later read hides, so nothing is ingested. The check is here and not
        # at the write boundary, which ADR-0080 §5 answered "no" rather than
        # deferred: a *question* going stale between asking and answering is a
        # product fact about the user's answer, not a storage rule. Reconciling
        # ``SemanticMemory.valid_until`` with the envelope stays ADR-0045 §10's item.
        if not deferral.proposal.proposed.validity.live_at(now):
            recorded = await self._deferrals.resolve(
                deferral.id, claim_id=claim.claim_id, state=DeferralState.STALE
            )
            return AnswerOutcome(
                kind=AnswerKind.STALE, question_id=deferral.id, disposed=not recorded
            )
        result = await self._writer.ingest(self._confirmed(claim, at=now))
        return await self._record(claim, result)

    def _confirmed(self, claim: DeferralClaim, *, at: datetime) -> MemoryUpdateProposal:
        """The claimed proposal, under the authority this claim mints (ADR-0078 §5).

        The proposal is rebuilt from the claimed ``DeferredProposal`` with exactly
        one addition, which is what makes the whole binding hold **by construction**
        on the honest path: both the content the writer digests and the conflicts it
        carries are the ones the question was asked about, so the recomputed
        ``question_key`` matches and ``retires`` is bounded by what the surface
        showed.

        ``retires`` is set to **exactly the conflict ids the question froze**.
        Legitimately empty where every conflict the user was shown has since gone —
        which is why ``UserConfirmation`` is a value rather than a bare tuple, so
        that case cannot read as "no confirmation" under a truthiness check and
        re-defer an answered question forever.

        **The only place a ``UserConfirmation`` is constructed**, and it takes the
        claim rather than the deferral, so holding the authority requires holding the
        claim (ADR-0078 §3's third obligation).
        """
        proposal = claim.deferral.proposal
        return proposal.model_copy(
            update={
                "confirmation": UserConfirmation(
                    deferral_id=claim.deferral.id,
                    question_key=proposal.question_key,
                    confirmed_at=at,
                    retires=proposal.conflicts,
                )
            }
        )

    async def _record(self, claim: DeferralClaim, result: MemoryIngestResult) -> AnswerOutcome:
        """Move the claim to the terminal state the ingest produced (ADR-0078 §2).

        The mapping is **total**, in the shape ``learn_decision`` already uses for
        the same class of exhaustiveness. ``REJECT`` is the arm an earlier revision
        of ADR-0078 omitted, and it is reachable: ``MemoryWriter`` takes an injected
        policy, and a conforming policy that is not ``DefaultMemoryPolicy`` may rule
        ``REJECT`` on a confirmed proposal, so without it such an answer would have
        no legal transition and strand forever.
        """
        deferral = claim.deferral
        match result.decision.kind:
            case MemoryDecisionKind.ASK_USER:
                return await self._redefer(claim, result)
            case MemoryDecisionKind.REJECT:
                recorded = await self._deferrals.resolve(
                    deferral.id, claim_id=claim.claim_id, state=DeferralState.REJECTED
                )
                return AnswerOutcome(
                    kind=AnswerKind.REJECTED, question_id=deferral.id, disposed=not recorded
                )
            case (
                MemoryDecisionKind.ACCEPT
                | MemoryDecisionKind.STORE_TEMPORARY
                | MemoryDecisionKind.REINFORCE
                | MemoryDecisionKind.SUPERSEDE
            ):
                return await self._accepted(claim, result)
            case _:  # pragma: no cover — exhaustive over the enum
                assert_never(result.decision.kind)

    async def _accepted(self, claim: DeferralClaim, result: MemoryIngestResult) -> AnswerOutcome:
        """Record an applied answer, naming the record the write left live."""
        deferral = claim.deferral
        record_id = result.record_id
        if record_id is None:
            # A write-producing ruling that named nothing written is a `MemoryWriter`
            # contract violation (ADR-0022 §4, ADR-0028 §8: an `ACCEPT` has stored
            # the record by the time `ingest` returns). Refused rather than passed
            # on, because `resolve(ACCEPTED)` requires a record id and a terminal
            # state that named nothing would be a state that lies.
            msg = (
                f"the writer ruled {result.decision.kind} on the answer to deferral "
                f"{deferral.id!r} but named no record written; nothing is recorded and the "
                f"question is left interrupted (ADR-0028 §8)"
            )
            raise MemoryStoreError(msg)
        recorded = await self._deferrals.resolve(
            deferral.id,
            claim_id=claim.claim_id,
            state=DeferralState.ACCEPTED,
            record_id=record_id,
        )
        return AnswerOutcome(
            kind=AnswerKind.APPLIED,
            question_id=deferral.id,
            record_id=record_id,
            disposed=not recorded,
        )

    async def _redefer(self, claim: DeferralClaim, result: MemoryIngestResult) -> AnswerOutcome:
        """Queue the successor, then resolve the original ``REDEFERRED`` (ADR-0078 §9).

        **A re-deferral is a completed answer, not a failed one.** The re-ingest
        surfaced a ``USER_ASSERTED`` conflict outside the answer's authority, so
        nothing was written and a *fresh* question is owed over the new set.

        **The successor is enqueued first and the original resolved second**, and
        that order matters for the same reason it does everywhere else in this
        sequence: a crash after resolving but before enqueuing would leave a question
        marked handled with no successor — the silent drop wearing a terminal state.
        Crashing the other way leaves the original ``APPLYING`` and the successor
        already asked: visible, and recoverable by §9's two steps.

        The successor is admitted **regardless of the queue cap**, because the token
        the claim minted is the capability that buys the exemption — so a full queue
        cannot strand a claimed answer. And because the store validates that token
        against a parent that is genuinely ``APPLYING`` and names no successor yet,
        the exemption is reachable from nowhere but here.

        Nothing on this path raises for a disposal or a refusal: **both are things
        the user brought about, and both are told.** If the parent was destroyed
        mid-apply the successor's admission finds no parent, takes the *ordinary*
        path — no cap bypass, nothing linked — and this stage branches on the
        admission it gets back rather than assuming a successor exists.
        """
        deferral = claim.deferral
        # ADR-0078 §9's exact call. The snapshot is the same proposal with its
        # `conflicts` set to *this* ingest's resolved set — the new set the successor
        # asks about, and the reason its `question_key` differs from its parent's so
        # dedup does not suppress it. The confirmation is dropped: a queued question
        # holds no authority, and the one it was answered under has been spent.
        snapshot = deferral.proposal.model_copy(
            update={"conflicts": result.conflicts, "confirmation": None}
        )
        admission = await admit_question(
            self._deferrals,
            id_factory=self._id_factory,
            proposal=snapshot,
            decision=result.decision,
            predecessor_id=deferral.id,
            successor_to_claim=claim.claim_id,
        )
        if admission.outcome is DeferralAdmissionOutcome.REFUSED:
            # Only reachable where the parent was destroyed mid-apply: an admission
            # holding a live parent's token never consults the cap. So there is no
            # row left to resolve, and `resolve` is not attempted — a `REDEFERRED`
            # transition needs a successor id and there is none to name.
            return AnswerOutcome(
                kind=AnswerKind.REDEFERRED,
                question_id=deferral.id,
                successor_refused=True,
                disposed=True,
            )
        successor = admission.deferral
        if successor is None:
            # `DeferralAdmission`'s validator pins the three shapes, so this is a
            # non-conforming store rather than a case — reported rather than
            # dereferenced, which is what the validator exists to make impossible to
            # write by accident.
            msg = (
                f"the queue reported a {admission.outcome} admission for the successor to "
                f"deferral {deferral.id!r} but carried no question; nothing is recorded"
            )
            raise DeferralStoreError(msg)
        recorded = await self._deferrals.resolve(
            deferral.id,
            claim_id=claim.claim_id,
            state=DeferralState.REDEFERRED,
            successor_id=successor.id,
        )
        return AnswerOutcome(
            kind=AnswerKind.REDEFERRED,
            question_id=deferral.id,
            successor=SuccessorLink(id=successor.id, state=question_state(successor.state)),
            disposed=not recorded,
        )

    async def _page(self, rows: list[DeferredProposal]) -> tuple[Question, ...]:
        """Project one page of stored rows into the surface's own DTO."""
        return tuple([await self._project(row) for row in rows])

    async def _project(self, deferral: DeferredProposal) -> Question:
        """Build the :class:`Question` a surface renders (ADR-0078 §8)."""
        proposal = deferral.proposal
        record = proposal.proposed
        return Question(
            id=deferral.id,
            state=question_state(deferral.state),
            content=record.content,
            kind=MemoryKind(record.kind),
            # Applied **once**, here (ADR-0073 §7). It says which band the record
            # *would* enter if accepted, never what the system holds: a pending
            # question is not a belief of any band (ADR-0078 §1).
            band=band_of(record.provenance.source),
            rationale=proposal.rationale,
            reason=deferral.decision.reason,
            retires=tuple([await self._retirement(one) for one in proposal.conflicts]),
            asked_at=deferral.deferred_at,
            expires_at=deferral.expires_at,
            successor=await self._successor(deferral.successor_id),
        )

    async def _retirement(self, record_id: str) -> Retirement:
        """Resolve one frozen conflict id to what it says, or to *no longer held*."""
        held = await self._memory.get(record_id)
        return Retirement(record_id=record_id, content=None if held is None else held.content)

    async def _successor(self, successor_id: str | None) -> SuccessorLink | None:
        """Resolve a stamped successor to its id **and its state** (ADR-0078 §9).

        ``None`` when the row names none, and ``None`` when the successor has since
        been destroyed — a link to a question nothing can walk would be worse than
        no link.
        """
        if successor_id is None:
            return None
        row = await self._deferrals.get(successor_id)
        if row is None:
            return None
        return SuccessorLink(id=successor_id, state=question_state(row.state))

    def _now_utc(self) -> datetime:
        """The guarded clock's reading, as the store this stage is about (ADR-0026 §4).

        ``core/errors.py`` defines no error for `orchestration`, so the failure goes
        to the stage — and this stage's own is the deferral queue, exactly as
        ``ConversationLifecycle`` raises ``ConversationStoreError`` for its clock.

        Raises:
            DeferralStoreError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise DeferralStoreError(str(exc)) from exc
