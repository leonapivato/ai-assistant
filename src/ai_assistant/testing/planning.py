"""Canonical test doubles for the planning contracts (ADR-0014).

The shared fakes for :class:`~ai_assistant.core.protocols.Planner` and
:class:`~ai_assistant.core.protocols.PlanStore`, so a subsystem that depends on
planning (orchestration, tools, ...) can test against real, contract-correct
implementations *without importing the planning subsystem's internals*
(CLAUDE.md golden rule 1).

They deliberately re-implement the transition graph rather than importing
``ai_assistant.planning``: importing it would defeat the purpose, since a
consumer's tests would then pull in the very subsystem the fake stands in for.
The shared conformance suite is what keeps the two implementations honest — both
must pass it, so a divergence is a test failure rather than a latent surprise.

``FakePlanStore``'s reads *and* writes go through a
:class:`~ai_assistant.testing.cancellation.SuspendableResource` so it is a real
subject for the cancellation clause ``core.protocols`` states (ADR-0060), rather
than an implementation the obligation cannot reach. The reads are in because
``SqlitePlanStore`` answers every one of them from under its connection lock, so
each is its own place the resource could be handed over early (#397).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    MAX_GOAL_EVIDENCE,
    MAX_GOAL_INTERPRETATIONS,
    MAX_INTENDED_ACTIONS,
    TERMINAL_ATTEMPT_STATES,
    ActionPlan,
    AssociationVerdict,
    AttemptPhase,
    AttemptState,
    EvidenceHistory,
    EvidenceStanding,
    ExecutionState,
    Goal,
    GoalAssociation,
    GoalAttempt,
    GoalCandidates,
    GoalDeletion,
    GoalEvidence,
    GoalQuestion,
    GoalQuestionDisposition,
    GoalRevision,
    Identifier,
    IntendedActionMinting,
    PlanExport,
    PlannerOutput,
    SkipReason,
    StepExecution,
    StepStatus,
    evidence_order,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        AttemptTransition,
        CurrentContext,
        EvidenceDigest,
        GoalBrief,
        GoalCandidacy,
        GoalStatus,
        MemoryRecord,
        ProposedUnderstanding,
        ReadAskOutcome,
        ReadRequest,
        ShownFile,
        StepTransition,
        UtcInstant,
    )
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog


def _revalidated_goal(goal: Goal, *, what: str) -> Goal:
    """Re-run ``Goal``'s validators over a goal built by ``model_copy`` (ADR-0023 §2).

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives for the transition graph. §2's own words are
    why it exists at all: "``model_copy(update=...)`` skips validators … and **a write
    that reaches past it must re-validate**" — so a naive ``at`` reaching
    ``engage_goal`` is refused here as the real stores refuse it, rather than stored
    and handed back.

    Args:
        goal: The goal as ``model_copy`` built it.
        what: What the caller was doing, for the refusal message.

    Returns:
        The goal, validated.

    Raises:
        PlanningError: If the rebuilt goal is not one ``Goal`` admits.
    """
    try:
        return Goal.model_validate(goal.model_dump())
    except ValidationError as exc:
        msg = f"{what} would leave goal {goal.id} in a shape Goal refuses: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_plan(plan: ActionPlan) -> ActionPlan:
    """Rebuild ``plan`` as a validated, detached :class:`ActionPlan`, or refuse it.

    :func:`_revalidated_goal`'s reasoning over the record ADR-0253 gives a graph.
    ``model_copy(update=...)`` skips validators, so a caller can hand in a plan whose
    ``depends_on`` points **forward** — which ADR-0253 §1 makes unconstructible so that
    "a cycle has no other spelling". A fake that stored one would hand a driver a plan
    the type says cannot exist, and would disagree with the stores it stands in for.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives: a consumer's tests would then pull in the very
    subsystem the fake stands in for, and a double that decided conformance by calling
    the code under test would report every implementation conformant.

    Args:
        plan: The plan as the caller handed it in.

    Returns:
        The plan, validated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return ActionPlan.model_validate(plan.model_dump())
    except ValidationError as exc:
        subject = getattr(plan, "id", "<no id>")
        msg = f"plan {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


#: Mirror of the ADR-0014 §4 graph; see the module docstring on duplication.
def _revalidated_revision(revision: GoalRevision) -> GoalRevision:
    """Rebuild ``revision`` as a validated, detached :class:`GoalRevision`, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives for the transition graph. A snapshot is not
    enough: ``invalidates`` is annotated ``tuple[Identifier, ...]`` but
    ``model_copy(update=...)`` **skips validators** (ADR-0023 §2), so it can arrive as a
    one-shot iterator a second traversal finds empty, or as a **string** whose
    ``tuple()`` is its characters — ``tuple("ev1")`` is ``("e", "v", "1")``, three ids
    the caller never named. The fake must not certify a weaker contract than the real
    stores keep.

    Args:
        revision: The command as the caller handed it in.

    Returns:
        The command, revalidated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return GoalRevision.model_validate(revision.model_dump())
    except ValidationError as exc:
        subject = getattr(revision, "goal_id", "<no goal>")
        msg = f"the revision for goal {subject!r} is not a valid command: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_minting(minting: IntendedActionMinting) -> IntendedActionMinting:
    """Rebuild ``minting`` as a validated, detached command, or refuse it (ADR-0265 §5).

    :func:`_revalidated_revision`'s reason one command over: ``model_copy(update=...)``
    skips validators (ADR-0023 §2), so ``actions`` can arrive as a one-shot iterator, as
    a string whose ``tuple()`` is its characters, or carrying two members under one
    ``id`` — the last being the case §5's own validator exists to close and the one a
    store's refusal of an id the goal already holds cannot reach.

    Args:
        minting: The command as the caller handed it in.

    Returns:
        The command, revalidated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return IntendedActionMinting.model_validate(minting.model_dump())
    except ValidationError as exc:
        subject = getattr(minting, "goal_id", "<no goal>")
        msg = f"the minting for goal {subject!r} is not a valid command: {exc}"
        raise PlanningError(msg) from exc


def _revalidated_evidence(row: GoalEvidence) -> GoalEvidence:
    """Rebuild ``row`` as a validated, detached :class:`GoalEvidence`, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives for the transition graph. ADR-0023 §2's words
    are why it exists: "``model_copy(update=...)`` skips validators … and **a write that
    reaches past it must re-validate**" — and a caller holding a stored row can reach
    past them, so a row copied to ``SUPERSEDED`` with no ``superseded_by`` arrives here
    as a value ADR-0252 §1's fourth axis says is not constructible. The fake must not
    certify a weaker contract than the real stores keep.

    Args:
        row: The row as the caller handed it in.

    Returns:
        The row, revalidated and detached.

    Raises:
        PlanningError: If it does not satisfy its own model.
    """
    try:
        return GoalEvidence.model_validate(row.model_dump())
    except ValidationError as exc:
        subject = getattr(row, "id", "<no id>")
        msg = f"evidence row {subject!r} is not a valid record and will not be stored: {exc}"
        raise PlanningError(msg) from exc


#: Mirror of :data:`ai_assistant.planning.goals._ROW_IDS`; see the module docstring on
#: duplication.
_ROW_IDS: Final[TypeAdapter[tuple[Identifier, ...]]] = TypeAdapter(tuple[Identifier, ...])


def _revalidated_row_ids(named: Sequence[str], *, what: str) -> tuple[Identifier, ...]:
    """Snapshot a caller's set of evidence row ids as a validated tuple, or refuse it.

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives for the transition graph. A **parameter**
    annotated ``Sequence[str]`` carries no validator at all, and ``str`` satisfies it:
    ``tuple("ev1")`` is ``("e", "v", "1")``, three rows the caller never named, which a
    store would irreversibly supersede wherever they happen to stand while leaving
    ``ev1`` itself ``STANDING`` and answering success (ADR-0252 §12). The fake must not
    certify a weaker contract than the real stores keep.

    Args:
        named: The ids as the caller handed them in.
        what: What the ids are for, as the tail of "the ids to {what}" in the message.

    Returns:
        The ids, validated and detached, in the order given.

    Raises:
        PlanningError: If the argument is not a container of identifiers.
    """
    if isinstance(named, str | bytes):
        msg = (
            f"the ids to {what} were given as {named!r}, a single string rather than a "
            f"container of ids: its characters are not the ids you named (ADR-0252 §12)"
        )
        raise PlanningError(msg)
    try:
        return _ROW_IDS.validate_python(named)
    except ValidationError as exc:
        msg = f"the ids to {what} are not a container of identifiers: {exc}"
        raise PlanningError(msg) from exc


def _marked_evidence(row: GoalEvidence, mark: dict[str, object], *, what: str) -> GoalEvidence:
    """Apply one of ADR-0252's two marks to ``row`` and revalidate it (ADR-0023 §2).

    Re-implemented here rather than imported from ``ai_assistant.planning``, for the
    reason this module's docstring gives for the transition graph: importing it would
    pull in the very subsystem the fake stands in for. The shared ``PlanStoreContract``
    is what holds the two statements honest.

    §2's own words are why it exists at all: "``model_copy(update=...)`` skips
    validators … and **a write that reaches past it must re-validate**" — and what it
    re-validates is ADR-0252 §1's fourth axis, that a row's standing and the argument
    beside it agree, over a value no constructor built.

    Args:
        row: The ``STANDING`` row being marked.
        mark: The standing and its one argument.
        what: What the caller was doing, for the refusal message.

    Returns:
        The marked row.

    Raises:
        PlanningError: If the result is not a shape ``GoalEvidence`` admits.
    """
    try:
        return GoalEvidence.model_validate(row.model_copy(update=mark).model_dump())
    except ValidationError as exc:
        msg = f"{what} would leave evidence row {row.id} in a shape it refuses: {exc}"
        raise PlanningError(msg) from exc


_LEGAL_TRANSITIONS: dict[StepStatus, frozenset[StepStatus]] = {
    StepStatus.PENDING: frozenset(
        {StepStatus.RUNNING, StepStatus.AWAITING_APPROVAL, StepStatus.SKIPPED}
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({StepStatus.RUNNING, StepStatus.SKIPPED}),
    StepStatus.RUNNING: frozenset(
        {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.INDETERMINATE}
    ),
    StepStatus.FAILED: frozenset({StepStatus.RUNNING}),
    StepStatus.SUCCEEDED: frozenset(),
    StepStatus.SKIPPED: frozenset(),
    StepStatus.INDETERMINATE: frozenset(),
}

#: The three :class:`~ai_assistant.core.types.AttemptState` members ADR-0249 §5 derives
#: *paused* from, which ADR-0255 §3 makes as disqualifying of a claim as the two
#: terminal ones. Mirrored here rather than imported, as the transition graph above is.
_PAUSED_ATTEMPT_STATES: Final[frozenset[AttemptState]] = frozenset(
    {
        AttemptState.AWAITING_CLARIFICATION,
        AttemptState.AWAITING_AUTHORIZATION,
        AttemptState.BLOCKED,
    }
)

#: Which skip reasons are truthful from which status; mirrors ADR-0014 §4 as
#: widened by ADR-0041 — ``APPROVAL_DENIED`` is legal from ``PENDING`` too, for
#: a policy that refuses with nobody asked, guarded by the unconditional
#: ``approval_ref`` check below rather than by this table.
_LEGAL_SKIP_REASONS: dict[StepStatus, frozenset[SkipReason]] = {
    StepStatus.PENDING: frozenset(
        {
            SkipReason.APPROVAL_DENIED,
            SkipReason.UNMET_DEPENDENCY,
            SkipReason.NO_CAPABLE_TOOL,
            SkipReason.SUPERSEDED,
        }
    ),
    StepStatus.AWAITING_APPROVAL: frozenset({SkipReason.APPROVAL_DENIED, SkipReason.SUPERSEDED}),
}

_MAX_ATTEMPTS = 3

#: ADR-0249 §6's order, read off the declaration rather than restated: "within one
#: attempt, ``phase`` advances in that order and never moves backwards".
_PHASE_ORDER: Final[dict[AttemptPhase, int]] = {
    phase: index for index, phase in enumerate(AttemptPhase)
}


def _appended_id(held: tuple[str, ...], addition: str | None) -> tuple[str, ...]:
    """Append ``addition`` unless the tuple already holds it (ADR-0249 §12).

    Args:
        held: The identifiers already on the attempt, in order.
        addition: The identifier to append, or ``None``.

    Returns:
        The tuple with ``addition`` at its end, or unchanged where it was absent or
        already held.
    """
    if addition is None or addition in held:
        return held
    return (*held, addition)


#: ADR-0228 §3's bound, restated here for the one thing this module needs it for:
#: how many calls of :meth:`FakePlanner.plan` a scripted turn accounts for. It is not
#: a second statement of the rule — the loop enforces it and
#: :data:`~ai_assistant.orchestration.loop._PLANNER_CALL_BOUND` is where it binds —
#: but the figure a fake scripting *one turn* must stop at.
_CALLS_PER_TURN: Final = 2


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FakePlanner:
    """A ``Planner`` that returns a scripted plan and records how it was called.

    Structurally implements :class:`~ai_assistant.core.protocols.Planner`.

    **It can also ask for one more read** (ADR-0226 §4). ``read_request`` scripts
    what the synthesised plan carries, so a consumer's tests can drive a turn on
    which the trigger fired — and, left alone, the fake asks for nothing on every
    turn, which is what a planner that knows nothing of the envelope does and what
    every existing consumer of this fake keeps getting.

    **And a turn may call it twice** (ADR-0228 §3), which is where a fake that
    answered one id twice would stop conforming. ADR-0014 §2's "re-planning produces a
    *new* ``ActionPlan`` with a new ``id``" now binds *within* one turn: the loop
    stamps the second plan as superseding the first, and ``PlanStore.save_plan``
    refuses a ``supersedes`` naming the saving plan's own id (ADR-0228 §5) — so a
    consumer driving a revising turn against a fake that reused one would get a
    ``PlanningError`` from the store for the *fake's* defect. **Every call after the
    first therefore answers a distinct id**, on the synthesised path and the scripted
    path alike: a scripted plan is returned exactly as scripted on the first call and
    with a fresh ``id`` and no other change afterwards, which is the fake conforming
    to the contract rather than disagreeing with itself — ``id`` is precisely the
    field ADR-0014 §2 requires to move.

    **``revision`` scripts what a turn's *second* call returns**, which is the hook a
    consumer takes to drive the milestone's own shape — a first plan that cannot name
    a value and asks for it, and a second that carries it — without standing a model
    up. A fake scripted that way models **one turn and no more**, and says so rather
    than guessing: ADR-0228 §3 bounds a turn at two planner calls, so a third call is
    a *second turn*, whose first call ought to be the first plan again and which
    ``revision`` cannot express. It would instead answer that turn's opening call with
    the previous turn's revision — a plan for a goal that turn does not have, and an
    id already spent. The fake cannot detect the boundary itself (a turn boundary is a
    signal the loop passes no more than it passes an iteration index, and ADR-0228 §12
    rules that the planner "is not told which iteration it is on"), so it refuses the
    third call and names the fix: **a consumer driving two turns builds two fakes**,
    which is what this suite's existing two-turn cases already do.

    **It sets no ``supersedes``** (ADR-0228 §5). That field is the loop's on every
    plan a planner returns, so a fake authoring one would be scripting a value its
    consumer discards; a test that wants to prove the discard scripts a plan carrying
    one and asserts what was persisted.

    **It records the listing it was shown and reads nothing into it** (ADR-0230 §3).
    ``files`` joins :attr:`calls` as a fifth element, so a consumer's test can assert
    *what the planner was handed* — that the projection was positional, that the same
    sequence reached both of a turn's calls, and that no capability came with it —
    without standing a model up, which is the only place outside `orchestration` those
    are checkable. Nothing here renders it, indexes it or judges it: what a planner
    makes of a listing is an implementation's business (ADR-0211 §9 item 2), and a
    ``LOCAL_FILE`` ask is scripted through ``read_request`` exactly as the other kinds
    are — **not** derived from ``files``, for the reason the request as a whole
    is not derived from ``memories``. So a fake handed an empty listing and scripted to
    name ``F1`` emits ``F1``, which is the unresolved-label population ADR-0226 §9's
    audit exists to count and which a filtering fake would put out of a consumer's
    reach.

    **It records ADR-0251 §3's carrier and reads nothing into it either.**
    ``read_outcomes`` joins :attr:`calls` as a **sixth** element, so a consumer's test
    can assert what the planner was *told* — that a turn's first call was handed
    ``()``, that a later call was handed the very ask an earlier plan emitted byte for
    byte beside the member the classifier reached for it, and that a read the budget
    did not reach, one the supply's shape blocked and a failed or declined servicing
    each produce **no entry at all** — without standing a model up. Nothing here
    renders it, and nothing here changes what the fake returns on account of it: what a
    planner makes of the fact is an implementation's business, and ADR-0240 §7's own
    clause, which ADR-0251 §3 restates over the wider carrier, is that "an
    implementation that accepts it and ignores its value means exactly what it meant".

    **A ``STRUCTURED_READ`` ask needs nothing of this fake but the existing hook**
    (ADR-0240 §2). A consumer drives a structured turn by scripting
    ``read_request=ReadRequest(asks=(ReadAsk(kind=ReadKind.STRUCTURED_READ,
    structure=StructuredAsk(window=TimeWindow(start=...))),))``, and the emission is
    passed through unfiltered exactly as an ``M`` label or an ``F`` entry is: this fake
    checks no axis against ``memories``, so a scripted ask naming a label nothing in the
    supply carried is emitted and serviced, which is ADR-0240 §9's clause that "the
    condition governs the invitation and never the ask" left reachable from a
    consumer's tests.

    **A ``WEB_SEARCH`` ask needs nothing of this fake but the same hook** (ADR-0231
    §1). The kind carries no argument, so a consumer drives a searching turn by
    scripting ``read_request=ReadRequest(asks=(ReadAsk(kind=ReadKind.WEB_SEARCH),))``
    and nothing here changes: the fake authors no query, holds no composer and reads
    no utterance, which is ADR-0231 §3's seam sitting on the far side of this one.
    Whether such an ask is serviced is the loop's and is invisible here — ADR-0226 §5's
    posture, which ADR-0231 §17 restates for this kind — so a fake that answered
    differently on a deployment with no search account would be certifying a planner
    that had been told something no planner is told.
    """

    def __init__(
        self,
        plan: ActionPlan | None = None,
        *,
        now: Clock = _utcnow,
        read_request: ReadRequest | None = None,
        revision: ActionPlan | None = None,
        understanding: ProposedUnderstanding | None = None,
    ) -> None:
        """Create a planner.

        Args:
            plan: The plan to return. When ``None``, a single-step plan is
                synthesised for whichever goal it is asked about.
            now: Clock for synthesised plans; injectable for deterministic tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`
                (ADR-0026 §7): ``ActionPlan.created_at``'s only producer today is
                this fake, so a fake looser than the contract is the whole gap.
            read_request: What the synthesised plan asks to have read beside it
                (ADR-0226 §4), or ``None`` — the default, and the true answer for a
                planner that asked for no read. This is the hook a consumer's tests
                take to drive a turn on which the trigger fired, without standing a
                model up.
            revision: What a call after the first returns (ADR-0228 §3), or ``None``
                — the default, under which a synthesised plan differs only in its id
                and a scripted one only in its id, and a consumer sees what it saw
                before this milestone. A turn makes at most two calls, so within one
                turn this is the only other one there is. Its ``supersedes`` is
                scripted like any other field and the loop discards it (§5), which is
                what makes the discard assertable.
            understanding: What every call proposes the system now understands
                (ADR-0249 §7), or ``None`` — the default, and the true answer for a
                planner that knows nothing of that envelope. Returned unchanged on
                every call, because what a planner proposes is not a function of the
                iteration and a fake that varied it would hold an opinion the contract
                leaves to an implementation.

        Raises:
            ValueError: If both ``plan`` and ``read_request`` are given. A scripted
                plan carries its own ``read_request`` field, so honouring both would
                give one value two sources that can disagree — and a fake that can
                disagree with itself certifies nothing. A ``revision`` reusing the
                first plan's ``id`` is refused too, but at the **call** rather than
                here: with no scripted first plan that id comes from the goal, which
                this constructor has not seen.
        """
        if plan is not None and read_request is not None:
            msg = (
                "pass read_request only with a synthesised plan; a scripted plan carries "
                "its own read_request field"
            )
            raise ValueError(msg)
        self._plan = plan
        self._read_request = read_request
        self._revision = revision
        self._understanding = understanding
        #: The id of the plan this fake answered a turn's **first** call with, which
        #: a scripted revision may not reuse. Recorded rather than derived: the
        #: synthesised id is a function of the goal, so it is not knowable until the
        #: call is made.
        self._first_id: str | None = None
        self._clock = checked_clock(now, owner="FakePlanner")
        #: One entry per call: the goal, the context, the memories, the capability
        #: vocabulary the caller stated (ADR-0211 §9 item 3) and the file listing it
        #: was shown (ADR-0230 §3). The vocabulary is recorded so a test over the loop
        #: can assert *what the planner was told* without standing a model up — which
        #: is the only way ADR-0211 §3's same-object clause is checkable from outside
        #: `app` — and the listing is recorded for the same reason: ADR-0230 §14 item
        #: 20 asks that the value crossing the seam be "a sequence of ``ShownFile``,
        #: one per entry in the listing's own order", which is a fact about the
        #: **call** and about no return value.
        #:
        #: **One element per fact rather than a second attribute**, so the facts of one
        #: call cannot come apart: a parallel list is one `append` away from recording
        #: a listing against the wrong call, and every consumer already reads this by
        #: index. The sixth is ADR-0251 §3's ``read_outcomes``, recorded for the
        #: reason the fifth is: §3 states a property of the **call** — that a later
        #: one receives the very ask an earlier plan emitted, byte for byte, beside
        #: one member of a closed vocabulary and nothing the store returned — which is
        #: a fact about no return value.
        self.calls: list[
            tuple[
                GoalBrief,
                str,
                CurrentContext,
                tuple[MemoryRecord, ...],
                tuple[str, ...],
                tuple[ShownFile, ...],
                tuple[ReadAskOutcome, ...],
                tuple[EvidenceDigest, ...],
            ]
        ] = []

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error the real planner raises.

        ``PlanningError``, not the raw ``ValueError`` ``core`` raises, for the
        reason ADR-0026 §4 gives: a fake exists to certify a consumer against its
        contract, so one that leaked ``ValueError`` where `planning` raises
        ``PlanningError`` would certify error handling against behaviour the real
        implementation never produces.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def plan(  # noqa: PLR0913 — the brief plus one keyword per thing the pipeline assembled before planning, as the Protocol declares them; ADR-0230 §3, ADR-0251 §3 and ADR-0249 §7 each add to it
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        """Return the scripted plan, recording the arguments it was given.

        **It proposes no understanding unless one is scripted** (ADR-0249 §7).
        ``understanding`` defaults to ``None``, which is what a planner that knows
        nothing of the envelope returns and what every existing consumer of this fake
        keeps getting; ``understanding=`` is the hook a consumer takes to drive a
        revising turn without standing a model up. Nothing here derives one from the
        brief, the utterance or the supply: what a planner proposes is the judgement
        the envelope *is*, and a fake that judged it would be a fake with an opinion
        the contract leaves to an implementation.

        **It authors no phase, no revision number, no ``raised_by`` and no
        ``recorded_at``** (ADR-0249 §6): ``ProposedUnderstanding`` carries no field
        for any of them, so the writer clause is a property of the type here rather
        than a restraint this fake is trusted to keep.

        ``capabilities`` is recorded and **not acted on**: the plan is scripted, so
        making it depend on the vocabulary would put a judgement in a fake that the
        contract leaves to an implementation (ADR-0211 §9 item 2 forbids the
        conformance suite asserting which envelope any planner returns). It is
        taken as handed — not sorted, de-duplicated or otherwise canonicalised
        (ADR-0211 §1) — and only frozen into a tuple, so a caller mutating the
        sequence it passed cannot rewrite what this records.

        **A turn's second call is answered by ``revision`` where one was scripted**
        (ADR-0228 §3), and by the same value as the first everywhere else — so a fake
        constructed as every existing consumer constructs it behaves on a revising
        turn exactly as it behaves on any other. Nothing here reads the iteration off
        ``memories`` or changes what it emits on account of it: ADR-0228 §12 rules
        that the planner "is not told which iteration it is on", and a fake that
        judged the supply would be a fake with an opinion the contract leaves to an
        implementation. The call ordinal it does read is the fake's own script
        pointer, never an input to a decision.

        **The read request is scripted for the same reason and is not derived from
        ``memories``** (ADR-0226 §8). Whether this turn's supply sufficed is the
        judgement the trigger *is*, and a fake that judged it would be a fake with
        an opinion the contract leaves to an implementation — and one whose fire
        rate a consumer's test could not control. So the request is whatever the
        constructor was handed, on every call, and a fake constructed without one
        asks for no read on every turn: §4's default, which is exactly what a
        planner that knows nothing of the envelope does.

        **It emits the labels it was given, unfiltered.** Nothing here checks a
        label against ``memories`` or an ``entry`` against ``files``: ADR-0226 §3 and
        ADR-0230 §2 both give resolution to the loop, which discards what does not
        resolve and records the drop in §9's audit, so a fake that filtered its own
        emission would make that population unreachable from a consumer's tests —
        which is precisely where it needs to be reachable. A scripted ``LOCAL_FILE``
        ask is therefore emitted on a turn that was shown no listing at all, which is
        exactly the arm a consumer needs to drive an unresolved label.

        Args:
            goal: The brief of the objective to plan for (ADR-0249 §9).
            utterance: This turn's own request (ADR-0248 §1, ADR-0249 §7). Recorded
                and **not acted on**, for ``capabilities``' own reason.
            context: The situational context assembled for this request.
            memories: What the pipeline assembled for this turn.
            capabilities: The vocabulary the registry advertised for this turn.
                Required, exactly as the contract requires it; the empty
                vocabulary is legal and changes nothing here (ADR-0211 §6).
            files: The listing the loop showed this turn (ADR-0230 §3). Recorded and
                **not acted on**, for ``capabilities``' own reason: the empty listing
                is legal, means no file is nameable, and changes nothing about what
                this fake returns. Frozen into a tuple, so a caller mutating the
                sequence it passed cannot rewrite what this records.
            read_outcomes: One entry per ask this turn has already serviced, in
                servicing order (ADR-0251 §3). Recorded and **not acted on**, for
                ``files``' own reason: what a planner makes of the fact is an
                implementation's business, and a fake that broadened its own scripted
                ask on account of it would be a fake with an opinion the contract
                leaves to an implementation — and would put ADR-0228 §2's last clause,
                that no implementation widens a request, out of a consumer's reach.
                Empty is legal and is every first call. Frozen into a tuple, as the
                others are.
            evidence: What this call may act on about the reads already taken
                (ADR-0249 §10). Recorded and **not acted on**, for the same reason;
                empty is legal and is every call of ADR-0249's own lanes.
        """
        self.calls.append(
            (
                goal,
                utterance,
                context,
                tuple(memories),
                tuple(capabilities),
                tuple(files),
                tuple(read_outcomes),
                tuple(evidence),
            )
        )
        ordinal = len(self.calls)
        if self._revision is not None:
            if ordinal > _CALLS_PER_TURN:
                # ADR-0228 §3 bounds a turn at two planner calls, so this is a second
                # turn — and a script naming one turn's revision cannot say what a
                # later turn's *opening* plan is. Answering with the revision again
                # would hand that turn a plan for a goal it does not have, carrying an
                # id already spent, and the failure would surface at `save_plan` as
                # the store's fault. Refused loudly instead, naming the fix.
                msg = (
                    f"this FakePlanner scripts one turn's two calls (ADR-0228 §3) and was "
                    f"called {ordinal} times; a second turn's first call is not a revision, "
                    "so build one FakePlanner per turn"
                )
                raise RuntimeError(msg)
            if ordinal > 1:
                # A turn persists both plans and `save_plan` refuses a `supersedes`
                # naming the saving plan's own id (ADR-0228 §5), so a script whose two
                # plans share an id is a script no conforming planner could satisfy.
                # Checked **here** rather than at construction, because that is the
                # first moment it is checkable in every case: a synthesised first plan
                # takes its id from the goal, which the constructor has not seen.
                if self._revision.id == self._first_id:
                    msg = (
                        f"the scripted revision reuses the first plan's id "
                        f"{self._first_id!r}; a turn's two plans are two records with two "
                        "ids (ADR-0014 §2, ADR-0228 §5)"
                    )
                    raise RuntimeError(msg)
                return PlannerOutput(plan=self._revision, understanding=self._understanding)
        if self._plan is not None:
            # Exactly as scripted on the first call, and with a fresh id afterwards
            # (ADR-0014 §2, ADR-0228 §3, §5). Only `id` moves — every other field is
            # the caller's own — because a plan reusing one is what `save_plan`
            # refuses, and a fake that failed its consumer for its own defect would
            # certify nothing.
            if ordinal == 1:
                self._first_id = self._plan.id
                return PlannerOutput(plan=self._plan, understanding=self._understanding)
            return PlannerOutput(
                plan=self._plan.model_copy(update={"id": f"{self._plan.id}-{ordinal}"}),
                understanding=self._understanding,
            )
        synthesised = ActionPlan(
            # Distinct on every call after the first (ADR-0228 §3, ADR-0014 §2). The
            # first keeps the id this fake has always minted, so nothing that named
            # it moves; a revision takes a new one, because a turn persists both
            # plans and `save_plan` refuses a `supersedes` naming the saving plan's
            # own id (ADR-0228 §5) — a fake reusing the id would fail its consumer
            # for the fake's own defect.
            id=(f"{goal.goal_id}-plan" if ordinal == 1 else f"{goal.goal_id}-plan-{ordinal}"),
            goal_id=goal.goal_id,
            steps=(),
            created_at=self._now(),
            rationale="synthesised by FakePlanner",
            read_request=self._read_request,
        )
        if ordinal == 1:
            self._first_id = synthesised.id
        return PlannerOutput(plan=synthesised, understanding=self._understanding)


class FakeGoalAssociator:
    """A scripted ``GoalAssociator`` test double (ADR-0250 §4).

    Structurally implements
    :class:`~ai_assistant.core.protocols.GoalAssociator`, and it is the canonical fake
    the Protocol's triad lands with (``CONTRIBUTING.md`` -> "Adding a Protocol"): the
    Protocol, its shared conformance suite and this value are one unit of work, with
    the production implementation following in ADR-0250 §19's M2.

    **It decides nothing.** A consumer scripts the answer it wants and the fake hands
    it back, recording the candidacy it was given so a test can assert over what
    crossed the seam — which is what arm 22's behavioural half is written against.
    Deciding here would make the double a second associator with a second rule to
    drift from the real one.

    **The default answer is** ``UNDECIDED`` **with no labels**, and that is deliberate
    rather than convenient: ADR-0250 §4 makes the decline the shape an implementation
    returns when it cannot read its model's answer, and a fake that defaulted to
    ``CONTINUES`` would hand every unconfigured consumer a silent association to the
    focused goal.

    Attributes:
        answer: What :meth:`associate` returns.
    """

    def __init__(self, *, answer: GoalAssociation | None = None) -> None:
        """Create an associator that returns ``answer`` to every call.

        Args:
            answer: What to return, or ``None`` for ADR-0250 §4's decline.
        """
        self.answer = answer or GoalAssociation(verdict=AssociationVerdict.UNDECIDED)
        self._calls: list[GoalCandidacy] = []

    @property
    def calls(self) -> tuple[GoalCandidacy, ...]:
        """Every candidacy this associator was handed, in call order.

        Returns:
            The candidacies, oldest first. A tuple, so a caller that mutated the
            page has changed nothing about the record.
        """
        return tuple(self._calls)

    @property
    def call_count(self) -> int:
        """How many times :meth:`associate` has been called.

        The figure ADR-0250 §3's arms are stated over — "a first turn costs nothing
        new", "one candidate still costs a call", "a turn carrying a reply reference
        costs nothing new" — each of which is an assertion about whether this seam was
        reached at all.

        Returns:
            The call count.
        """
        return len(self._calls)

    async def associate(self, candidacy: GoalCandidacy, /) -> GoalAssociation:
        """Return the scripted answer, recording what it was asked (ADR-0250 §4).

        Args:
            candidacy: The turn's request and its labelled candidates.

        Returns:
            :attr:`answer`, unchanged.
        """
        self._calls.append(candidacy)
        return self.answer


class FakePlanStore:
    """A non-persistent ``PlanStore`` test double backed by dicts.

    Structurally implements :class:`~ai_assistant.core.protocols.PlanStore`,
    including the compare-and-swap write path and the data-rights operations.
    """

    def __init__(self, *, now: Clock = _utcnow) -> None:
        """Create an empty store with an injectable clock.

        Args:
            now: Clock for transition and export timestamps; injectable for
                deterministic tests. Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, exactly as
                ``InMemoryPlanStore`` is (ADR-0026 §7).
        """
        self._goals: dict[str, Goal] = {}
        self._attempts: dict[str, GoalAttempt] = {}
        self._questions: dict[str, GoalQuestion] = {}
        # ADR-0252 §12's rows, and §13's per-goal elision count beside them. The count
        # is **held** rather than recomputed from the row count, and goes with the goal.
        self._evidence: dict[str, GoalEvidence] = {}
        self._evidence_elided: dict[str, int] = {}
        self._plans: dict[str, ActionPlan] = {}
        self._executions: dict[str, ExecutionState] = {}
        self._clock = checked_clock(now, owner="FakePlanStore")
        self._sequence = 0
        # A per-instance random nonce, matching ``InMemoryPlanStore``: the
        # sequence alone is process-local, so a restart would re-mint a prior
        # id. The nonce makes the id unique across restarts too, satisfying the
        # ADR-0044 §1 non-reuse guarantee (#280). The fake must not certify a
        # weaker contract than the real store keeps.
        self._incarnation = uuid4().hex
        self._resource = SuspendableResource()

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        The hook ``PlanStoreContract``'s cancellation case takes (ADR-0060 §3).
        Test-only, and not part of the ``PlanStore`` contract: the Protocol
        deliberately grows no affordance for this, so the suite asks the *subject*
        it was handed rather than the seam every consumer depends on.

        Named for an *operation* rather than a write because the reads enter the
        resource too (#397); it holds whichever call arrives next, so a suite arms
        it after its preconditions have run.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def _now(self) -> datetime:
        """The guarded clock's reading, as the error the real store raises.

        Raises:
            PlanningError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range
                (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    async def save_goal(self, goal: Goal) -> str:
        """Persist a **new** goal (ADR-0249 §12), refusing an id already held.

        The opening write alone, and no longer an upsert: an upsert that replaced a
        whole goal would defeat ADR-0249 §1's append-only interpretation and §12's
        compare-and-swap in one call, so every later change goes through
        :meth:`record_interpretation`.

        **And a goal opened carrying an intended action is refused** (ADR-0265 §1, §2).
        "The goal's opening write mints none", and "the only route to a new
        ``IntendedAction`` is a ``ProposedAction`` recorded by the member §5 adds" — so
        a seeded tuple would take at the door what ``MAX_INTENDED_ACTIONS`` forbids and
        leave the bound enforced on nothing. Stated here rather than imported, for the
        reason this module's own docstring gives.

        Raises:
            PlanningError: If the store already holds a goal under this ``id``, or if
                the goal is opened carrying an intended action.
        """
        if goal.intended_actions:
            named = ", ".join(action.id for action in goal.intended_actions)
            msg = (
                f"goal {goal.id} is opened carrying intended action {named}: a goal's "
                f"opening write mints none, and the only route to an intended action "
                f"is record_intended_actions (ADR-0265 §1, §2)"
            )
            raise PlanningError(msg)
        async with self._resource.held():
            if goal.id in self._goals:
                msg = (
                    f"goal {goal.id} already exists: save_goal is the opening write "
                    "alone, and a later change to a goal is a record_interpretation "
                    "(ADR-0249 §12)"
                )
                raise PlanningError(msg)
            # ADR-0249 §2's bound is stated over **the write**, so the opening write
            # takes it too: a goal handed in with more revisions than the ceiling
            # admits is stored trimmed, with the count saying how many went.
            dropped = max(0, len(goal.interpretation) - MAX_GOAL_INTERPRETATIONS)
            stored = goal.model_copy(
                update={
                    "interpretation": goal.interpretation[dropped:],
                    "interpretation_elided": goal.interpretation_elided + dropped,
                }
            )
            self._goals[stored.id] = stored.model_copy(deep=True)
        return stored.id

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Append one interpretation revision, compare-and-swap (ADR-0249 §12).

        Re-implemented here rather than imported from ``ai_assistant.planning``, for
        the reason this module's docstring gives for the transition graph: importing
        it would pull in the very subsystem the fake stands in for. The shared
        ``PlanStoreContract`` is what holds the two statements honest.

        **``invalidates`` is applied in the same step as the append** (ADR-0252 §9,
        §12), with the refusals ahead of it so a call that cannot mark every row it
        named appends nothing. **The command is revalidated on the first executed
        line**, which is both ADR-0023 §2's obligation and this method's ADR-0065
        snapshot.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If the revision is not a valid command, if ``goal_id`` names
                no stored goal, if the revision does not follow the goal's current one,
                or if a row named by ``invalidates`` is not this goal's or is not
                ``STANDING``.
        """
        command = _revalidated_revision(revision)
        async with self._resource.held():
            stored = self._goals.get(command.goal_id)
            if stored is None:
                msg = f"cannot record an interpretation for unknown goal {command.goal_id}"
                raise PlanningError(msg)
            if stored.version != command.expected_version:
                msg = (
                    f"goal {command.goal_id} is at version {stored.version}, not "
                    f"{command.expected_version}: re-read it and recompute the revision"
                )
                raise StaleExecutionError(msg)
            current = stored.interpretation[-1]
            if command.interpretation.revision != current.revision + 1:
                msg = (
                    f"goal {command.goal_id} is at revision {current.revision}, so the "
                    f"next revision is {current.revision + 1} and not "
                    f"{command.interpretation.revision} (ADR-0249 §1)"
                )
                raise PlanningError(msg)
            self._refuse_unmarkable_locked(
                command.goal_id, command.invalidates, being_written=None, what="invalidate"
            )
            history = (*stored.interpretation, command.interpretation)
            # ADR-0249 §2: the write that would exceed the bound drops the **oldest**
            # element, never the current one, and the count is advanced rather than
            # the truncation left silent.
            dropped = max(0, len(history) - MAX_GOAL_INTERPRETATIONS)
            updated = stored.model_copy(
                update={
                    "interpretation": history[dropped:],
                    "interpretation_elided": stored.interpretation_elided + dropped,
                    "version": stored.version + 1,
                }
            )
            self._goals[updated.id] = updated
            for row_id in command.invalidates:
                self._evidence[row_id] = _marked_evidence(
                    self._evidence[row_id],
                    {
                        "standing": EvidenceStanding.INAPPLICABLE,
                        "inapplicable_at_revision": command.interpretation.revision,
                    },
                    what="the invalidation",
                )
            return updated.model_copy(deep=True)

    async def record_intended_actions(self, minting: IntendedActionMinting) -> Goal:
        """Append intended actions to a goal, compare-and-swap (ADR-0265 §5).

        Re-implemented here rather than imported from ``ai_assistant.planning``, for
        the reason this module's docstring gives: importing it would pull in the very
        subsystem the fake stands in for, and a fake that decided conformance by
        calling the code it stands in for would report every implementation conformant.
        The shared ``PlanStoreContract`` is what holds the two statements honest.

        **The three refusals run before the append**, so a minting that cannot record
        every action it carries records none of them — not the first, not a prefix, and
        not the ones that would have fit. **None of them takes the stale-write class**:
        each is an invariant breach at the current version, "and a caller that re-read
        and retried would re-raise for ever".

        **The command is revalidated on the first executed line**, which is both
        ADR-0023 §2's obligation and this method's ADR-0065 snapshot.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If the minting is not a valid command, if ``goal_id`` names
                no stored goal, if an ``id`` is one the goal already holds, if the
                append would carry the goal past ``MAX_INTENDED_ACTIONS``, or if a
                ``serves`` value names no element of the goal's current interpretation.
        """
        command = _revalidated_minting(minting)
        async with self._resource.held():
            stored = self._goal_for_write_locked(
                command.goal_id, command.expected_version, "mint against"
            )
            held = {action.id for action in stored.intended_actions}
            repeated = sorted({action.id for action in command.actions if action.id in held})
            if repeated:
                msg = (
                    f"goal {command.goal_id} already holds intended action "
                    f"{', '.join(repeated)}: an intended action is minted once and the "
                    f"tuple is append-only (ADR-0265 §1, §5)"
                )
                raise PlanningError(msg)
            if len(stored.intended_actions) + len(command.actions) > MAX_INTENDED_ACTIONS:
                msg = (
                    f"goal {command.goal_id} holds {len(stored.intended_actions)} "
                    f"intended actions and this minting carries {len(command.actions)}, "
                    f"which is past the bound of {MAX_INTENDED_ACTIONS}: the minting is "
                    f"refused whole and nothing is elided to make room (ADR-0265 §1, §5)"
                )
                raise PlanningError(msg)
            current = stored.interpretation[-1]
            known = {
                element.id
                for group in (current.constraints, current.criteria, current.conditions)
                for element in group
                if element.id is not None
            }
            dangling = sorted(
                {served for action in command.actions for served in action.serves} - known
            )
            if dangling:
                msg = (
                    f"the minting for goal {command.goal_id} serves "
                    f"{', '.join(dangling)}, which "
                    f"{'is' if len(dangling) == 1 else 'are'} not the id of an element "
                    f"of revision {current.revision}: at the append every entry names a "
                    f"current element (ADR-0265 §3, §5)"
                )
                raise PlanningError(msg)
            updated = _revalidated_goal(
                stored.model_copy(
                    update={
                        "intended_actions": (*stored.intended_actions, *command.actions),
                        "version": stored.version + 1,
                    }
                ),
                what="minting an intended action",
            )
            self._goals[updated.id] = updated
            return updated.model_copy(deep=True)

    def _goal_for_write_locked(self, goal_id: str, expected: int, what: str) -> Goal:
        """Read a goal for a compare-and-swap write; the caller holds the resource.

        Re-implemented here rather than imported from ``ai_assistant.planning``, for
        the reason this module's docstring gives: importing it would pull in the very
        subsystem the fake stands in for. ``PlanStoreContract`` is what holds the two
        statements honest.

        Args:
            goal_id: The goal to read.
            expected: The ``Goal.version`` the caller computed against.
            what: What the caller is about to do, for the refusal message.

        Returns:
            The stored goal.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        stored = self._goals.get(goal_id)
        if stored is None:
            msg = f"cannot {what} unknown goal {goal_id}"
            raise PlanningError(msg)
        if stored.version != expected:
            msg = (
                f"goal {goal_id} is at version {stored.version}, not {expected}: re-read "
                f"it and recompute the write"
            )
            raise StaleExecutionError(msg)
        return stored

    async def engage_goal(
        self, goal_id: str, /, *, at: UtcInstant, conversation_id: str, expected_version: int
    ) -> Goal:
        """Stamp the goal's engagement, compare-and-swap (ADR-0250 §1, §9).

        The one writer of ``last_engaged_at`` and ``last_engaged_in``; it writes
        nothing else, and ``conversation_id`` is never rewritten.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        async with self._resource.held():
            stored = self._goal_for_write_locked(goal_id, expected_version, "engage")
            updated = _revalidated_goal(
                stored.model_copy(
                    update={
                        "last_engaged_at": at,
                        "last_engaged_in": conversation_id,
                        "version": stored.version + 1,
                    }
                ),
                what="the engagement stamp",
            )
            self._goals[updated.id] = updated
            return updated.model_copy(deep=True)

    async def set_goal_status(
        self,
        goal_id: str,
        /,
        *,
        status: GoalStatus,
        at: UtcInstant,  # noqa: ARG002 — the contract's instant; no field of `Goal` records it, and this fake mints no second record to hold it (ADR-0250 §9)
        expected_version: int,
    ) -> Goal:
        """Move the goal's status, compare-and-swap (ADR-0250 §9).

        The goal's only status-mutation route, and it refuses no member of the
        vocabulary: which act writes which member is the caller's rule.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal.
        """
        async with self._resource.held():
            stored = self._goal_for_write_locked(goal_id, expected_version, "set the status of")
            updated = _revalidated_goal(
                stored.model_copy(update={"status": status, "version": stored.version + 1}),
                what="the status move",
            )
            self._goals[updated.id] = updated
            return updated.model_copy(deep=True)

    async def candidates_for(self, conversation_id: str, /, *, limit: int) -> GoalCandidates:
        """Return this conversation's candidate goals, capped (ADR-0250 §2, §9).

        Membership is §2's two-field test — opened in this conversation, or last
        engaged in it — and the order is §1's: ``last_engaged_at`` descending, the
        ``goal_id`` ascending as the tie-break, and a goal carrying no instant after
        every goal that carries one.

        Raises:
            PlanningError: If ``limit`` is not positive.
        """
        if limit < 1:
            msg = f"a candidate set is read with a positive limit and not {limit} (ADR-0250 §9)"
            raise PlanningError(msg)
        taken = min(limit, MAX_ASSOCIATION_CANDIDATES)
        async with self._resource.held():
            members = [
                goal.model_copy(deep=True)
                for goal in self._goals.values()
                if conversation_id in (goal.conversation_id, goal.last_engaged_in)
            ]
        # Two passes over a stable sort, comparing the instants themselves: a float of
        # a datetime makes two instants a microsecond apart compare equal from about
        # 2262, which would hand the id tie-break a pair §1 does not tie. The real
        # stores state the same rule in `planning/goals.capped`; `PlanStoreContract` is
        # what holds the two statements honest.
        carrying = [
            (one.last_engaged_at, one) for one in members if one.last_engaged_at is not None
        ]
        carrying.sort(key=lambda pair: pair[1].id)
        carrying.sort(key=lambda pair: pair[0], reverse=True)
        absent = sorted(
            (one for one in members if one.last_engaged_at is None), key=lambda one: one.id
        )
        ordered = [one for _, one in carrying] + absent
        return GoalCandidates(goals=tuple(ordered[:taken]), elided=max(0, len(ordered) - taken))

    async def record_question(self, question: GoalQuestion, /) -> bool:
        """Write an ``OPEN`` question, or refuse a second on one goal (§9).

        The read of the existing question and the write happen under one hold of the
        modelled resource, so two callers cannot both be admitted against one goal.

        Raises:
            PlanningError: If ``goal_id`` or ``attempt_id`` names no stored record, or
                the store already holds a question under this ``id``.
        """
        async with self._resource.held():
            if question.disposition is not GoalQuestionDisposition.OPEN:
                # A terminal record written here would answer `True` while `open_question`
                # answered `None` for the same goal — a question reported as opened that
                # occupies no slot and carries a `settled_at` nothing settled. Only
                # `settle_question` reaches a terminal disposition (ADR-0250 §9, §12).
                msg = (
                    f"question {question.id} arrives {question.disposition.value} and "
                    f"record_question writes an OPEN question: a terminal disposition is "
                    f"written by settle_question and by nothing else (ADR-0250 §9)"
                )
                raise PlanningError(msg)
            if question.goal_id not in self._goals:
                msg = f"cannot record a question for unknown goal {question.goal_id}"
                raise PlanningError(msg)
            attempt = self._attempts.get(question.attempt_id)
            if attempt is None:
                msg = f"cannot record a question for unknown attempt {question.attempt_id}"
                raise PlanningError(msg)
            if attempt.goal_id != question.goal_id:
                msg = (
                    f"question {question.id} names attempt {question.attempt_id}, which "
                    f"belongs to goal {attempt.goal_id} and not to {question.goal_id}: a "
                    f"question's attempt is one its own goal holds (ADR-0250 §9)"
                )
                raise PlanningError(msg)
            if question.id in self._questions:
                msg = f"question {question.id} already exists"
                raise PlanningError(msg)
            if any(
                held.goal_id == question.goal_id
                and held.disposition is GoalQuestionDisposition.OPEN
                for held in self._questions.values()
            ):
                return False
            self._questions[question.id] = question.model_copy(deep=True)
            return True

    async def get_question(self, question_id: str, /) -> GoalQuestion | None:
        """Return the question under that id, whatever its disposition (§9)."""
        async with self._resource.held():
            stored = self._questions.get(question_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def open_question(self, goal_id: str, /) -> GoalQuestion | None:
        """Return that goal's open question, or ``None`` (ADR-0250 §9)."""
        async with self._resource.held():
            for held in self._questions.values():
                if held.goal_id == goal_id and held.disposition is GoalQuestionDisposition.OPEN:
                    return held.model_copy(deep=True)
        return None

    async def outstanding_questions(self) -> tuple[GoalQuestion, ...]:
        """Return every ``OPEN`` question, in ``asked_at`` order (ADR-0250 §9).

        It takes no view of the clock: an expired question is still ``OPEN`` until
        something settles it, and settling it is the caller's (§12).
        """
        async with self._resource.held():
            open_ones = [
                one
                for one in self._questions.values()
                if one.disposition is GoalQuestionDisposition.OPEN
            ]
        return tuple(
            one.model_copy(deep=True)
            for one in sorted(open_ones, key=lambda one: (one.asked_at, one.id))
        )

    async def settle_question(
        self, question_id: str, /, *, disposition: GoalQuestionDisposition, at: UtcInstant
    ) -> bool:
        """Settle an ``OPEN`` question, clearing its content (ADR-0250 §9).

        The resolve-once gate: the read, the comparison and the write happen under one
        hold, so one of two racing callers answers ``True`` and the other ``False``,
        and the content is cleared exactly once.

        Raises:
            PlanningError: If ``disposition`` is ``OPEN``, which settles nothing.
        """
        if disposition is GoalQuestionDisposition.OPEN:
            msg = (
                "settle_question moves an OPEN question to a terminal member: OPEN "
                "settles nothing and no disposition is inferred from silence "
                "(ADR-0250 §9, §12)"
            )
            raise PlanningError(msg)
        async with self._resource.held():
            stored = self._questions.get(question_id)
            if stored is None or stored.disposition is not GoalQuestionDisposition.OPEN:
                return False
            settled = stored.model_copy(
                update={
                    "disposition": disposition,
                    "settled_at": at,
                    "text": None,
                    "about": None,
                }
            )
            try:
                self._questions[question_id] = GoalQuestion.model_validate(settled.model_dump())
            except ValidationError as exc:
                msg = (
                    f"the settlement would leave question {question_id} in a shape it "
                    f"refuses: {exc}"
                )
                raise PlanningError(msg) from exc
            return True

    # --- evidence (ADR-0252 §12, §13) -------------------------------------

    async def record_evidence(
        self, evidence: GoalEvidence, /, *, supersedes: Sequence[str] = ()
    ) -> str:
        """Persist a **new** evidence row, applying its refresh marks (ADR-0252 §12).

        Re-implemented here rather than imported from ``ai_assistant.planning``, for the
        reason this module's docstring gives for the transition graph: importing it
        would pull in the very subsystem the fake stands in for. The shared
        ``PlanStoreContract`` is what holds the statements honest.

        **One indivisible step, in a fixed order: the refusals, then the append, then
        the marks, then §13's elision**, all under the modelled resource and with no
        ``await`` between them — so a caller never has to ask which of its marks landed,
        and a row named by ``supersedes`` is validated against the history as it stood
        before the call.

        **``supersedes`` is observed on the coroutine's first executed line**, which is
        ``core.protocols``' second standing obligation (ADR-0065 §1): "a ``Sequence``
        argument is a container the caller may still be holding", and this store
        suspends inside :meth:`suspend_next_operation`'s modelled resource, so reading
        it again after the suspension would let a caller add a row to the set while the
        call is held and have it marked. It is **revalidated** rather than merely
        snapshotted, because ``Sequence[str]`` is satisfied by a bare ``str`` and
        ``tuple("ev1")`` is ``("e", "v", "1")`` — three rows the caller never named.
        ``evidence`` is snapshotted on that same line too, though for a different
        reason: the revalidation ADR-0023 §2 obliges is what
        produces the detached value, and taking it before the first ``await`` makes it
        this method's ADR-0065 snapshot as well — the shape
        ``SqlitePlanStore.record_evidence`` already has.

        **The row is revalidated before it is kept**, so the three conforming
        implementations admit the same rows: a row copied to ``SUPERSEDED`` with no
        ``superseded_by`` is refused here exactly as the two real stores refuse it, and
        the fake does not certify a weaker contract than they keep.

        Raises:
            PlanningError: If ``supersedes`` is not a container of identifiers, if the
                store already holds a row under this ``id``, if ``goal_id`` names no
                stored goal, or if a row named by ``supersedes`` is not this goal's, is
                not ``STANDING``, or is the row being written.
        """
        named = _revalidated_row_ids(supersedes, what="supersede")
        snapshot = _revalidated_evidence(evidence)
        async with self._resource.held():
            if snapshot.id in self._evidence:
                msg = (
                    f"evidence row {snapshot.id} already exists: record_evidence "
                    f"persists a new row and no member replaces a stored one "
                    f"(ADR-0252 §12)"
                )
                raise PlanningError(msg)
            if snapshot.goal_id not in self._goals:
                msg = f"cannot record evidence for unknown goal {snapshot.goal_id}"
                raise PlanningError(msg)
            self._refuse_unmarkable_locked(
                snapshot.goal_id, named, being_written=snapshot.id, what="supersede"
            )
            self._evidence[snapshot.id] = snapshot
            for row_id in named:
                self._evidence[row_id] = _marked_evidence(
                    self._evidence[row_id],
                    {
                        "standing": EvidenceStanding.SUPERSEDED,
                        "superseded_by": snapshot.id,
                    },
                    what="the supersession",
                )
            self._elide_evidence_locked(snapshot.goal_id, keep=snapshot.id)
            return snapshot.id

    async def get_evidence(self, evidence_id: str, /) -> GoalEvidence | None:
        """Return the evidence row under that id, or ``None`` — under the resource."""
        async with self._resource.held():
            stored = self._evidence.get(evidence_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def evidence_of(self, goal_id: str, /) -> EvidenceHistory:
        """Return one goal's history in §12's total order, with its count."""
        async with self._resource.held():
            return self._history_locked(goal_id)

    def _history_locked(self, goal_id: str) -> EvidenceHistory:
        """That goal's rows in ``(read_at, id)`` order; the caller holds the resource.

        Args:
            goal_id: The goal to read.

        Returns:
            Its history — empty with a zero count for a goal this store does not hold.
        """
        rows = sorted(
            (row for row in self._evidence.values() if row.goal_id == goal_id),
            key=evidence_order,
        )
        return EvidenceHistory(
            goal_id=goal_id,
            rows=tuple(row.model_copy(deep=True) for row in rows),
            elided=self._evidence_elided.get(goal_id, 0),
        )

    def _refuse_unmarkable_locked(
        self,
        goal_id: str,
        named: Sequence[str],
        *,
        being_written: str | None,
        what: str,
    ) -> None:
        """Refuse the whole call where a named row cannot take its mark (§12).

        Args:
            goal_id: The goal whose rows may be marked.
            named: The ids the caller asked to mark.
            being_written: The row this call is appending, or ``None``.
            what: The verb for the message.

        Raises:
            PlanningError: If any named row cannot take the mark.
        """
        for row_id in named:
            if being_written is not None and row_id == being_written:
                msg = (
                    f"cannot {what} evidence row {row_id} with itself: a row is "
                    f"validated against the history as it stood before the call "
                    f"(ADR-0252 §12)"
                )
                raise PlanningError(msg)
            row = self._evidence.get(row_id)
            if row is None or row.goal_id != goal_id:
                msg = (
                    f"cannot {what} evidence row {row_id}: it is not goal {goal_id}'s "
                    f"(ADR-0252 §12)"
                )
                raise PlanningError(msg)
            if row.standing is not EvidenceStanding.STANDING:
                msg = (
                    f"cannot {what} evidence row {row_id}: it is {row.standing.value} "
                    f"and a mark is never un-marked and never re-applied "
                    f"(ADR-0252 §8, §9)"
                )
                raise PlanningError(msg)

    def _elide_evidence_locked(self, goal_id: str, *, keep: str) -> None:
        """Hold the goal's history to :data:`MAX_GOAL_EVIDENCE`, disclosing the drop.

        **By age and by nothing else** (§13), over the history as the marks have just
        left it, and **never the row being written**.

        Args:
            goal_id: The goal whose history to bound.
            keep: The row this write appended, which is never dropped.
        """
        rows = sorted(
            (row for row in self._evidence.values() if row.goal_id == goal_id),
            key=evidence_order,
        )
        excess = len(rows) - MAX_GOAL_EVIDENCE
        if excess <= 0:
            return
        dropped = 0
        for row in rows:
            if dropped == excess:
                break
            if row.id == keep:
                continue
            del self._evidence[row.id]
            dropped += 1
        self._evidence_elided[goal_id] = self._evidence_elided.get(goal_id, 0) + dropped

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Persist a new attempt for a stored goal (ADR-0249 §12).

        **An execution belongs to exactly one attempt** (ADR-0255 §3), and this member
        is half of where that is made true: the tuple may arrive non-empty, so a caller
        could otherwise open a live attempt carrying an ended attempt's execution and
        defeat the claim conjunct without ever calling :meth:`commit_attempt`.

        Raises:
            PlanningError: If ``goal_id`` names no stored goal, the store already holds
                an attempt under this ``id``, or any ``execution_ids`` member is already
                carried by another attempt of that goal (ADR-0255 §3).
        """
        async with self._resource.held():
            if attempt.goal_id not in self._goals:
                msg = f"attempt {attempt.id} refers to unknown goal {attempt.goal_id}"
                raise PlanningError(msg)
            if attempt.id in self._attempts:
                msg = (
                    f"attempt {attempt.id} already exists; a change to an attempt is a "
                    "commit_attempt, which is its only mutation route (ADR-0249 §12)"
                )
                raise PlanningError(msg)
            for plan_id in attempt.plan_ids:
                self._refuse_a_dangling_plan(attempt, plan_id)
            for execution_id in attempt.execution_ids:
                self._refuse_a_dangling_execution(attempt, execution_id)
                self._refuse_a_second_owner(attempt.id, attempt.goal_id, execution_id)
            self._attempts[attempt.id] = attempt.model_copy(deep=True)
        return attempt.id

    async def get_attempt(self, attempt_id: str) -> GoalAttempt | None:
        """Return the attempt with ``attempt_id``, or ``None`` — under the resource (#397)."""
        async with self._resource.held():
            stored = self._attempts.get(attempt_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def attempts_of(self, goal_id: str) -> tuple[GoalAttempt, ...]:
        """Return every attempt of ``goal_id``, in ``opened_at`` order (#397)."""
        async with self._resource.held():
            return tuple(
                attempt.model_copy(deep=True)
                for attempt in sorted(
                    (one for one in self._attempts.values() if one.goal_id == goal_id),
                    key=lambda one: (one.opened_at, one.id),
                )
            )

    async def commit_attempt(self, transition: AttemptTransition) -> GoalAttempt:
        """Apply one attempt transition, compare-and-swap (ADR-0249 §12).

        **An ``add_execution_id`` naming an execution another attempt of that goal
        already carries is refused** (ADR-0255 §3), which is the other half of
        :meth:`open_attempt`'s invariant. ADR-0249 §12's append-only rule is untouched:
        a repeat of the same append **on the owning attempt** is still ignored.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            IllegalTransitionError: If the move is not legal from where it stands.
            PlanningError: If the attempt does not exist, the result is not a shape
                ADR-0249 §5 admits, or the execution it names is already another
                attempt's (ADR-0255 §3).
        """
        async with self._resource.held():
            stored = self._attempts.get(transition.attempt_id)
            if stored is None:
                msg = f"unknown attempt {transition.attempt_id}"
                raise PlanningError(msg)
            if stored.version != transition.expected_version:
                msg = (
                    f"attempt {transition.attempt_id} is at version {stored.version}, not "
                    f"{transition.expected_version}: re-read it and recompute the transition"
                )
                raise StaleExecutionError(msg)
            if transition.add_plan_id is not None:
                self._refuse_a_dangling_plan(stored, transition.add_plan_id)
            if transition.add_execution_id is not None:
                self._refuse_a_dangling_execution(stored, transition.add_execution_id)
                self._refuse_a_second_owner(stored.id, stored.goal_id, transition.add_execution_id)
            updated = self._advanced_attempt(stored, transition)
            self._attempts[updated.id] = updated
            return updated.model_copy(deep=True)

    def _refuse_a_dangling_plan(self, attempt: GoalAttempt, plan_id: str) -> None:
        """Refuse a plan reference that does not resolve under this attempt's goal.

        ADR-0014 §5's export promise kept at write time rather than repaired at read
        time — the division ADR-0228 §5 already records for ``supersedes`` — over the
        references ADR-0249 §11 adds. Confining a reference to the attempt's own goal
        is also what keeps the closure true across a deletion, since ``delete_goal``
        cascades a goal's plans, executions and attempts together.

        Args:
            attempt: The attempt the reference is being written onto.
            plan_id: The plan the write names.

        Raises:
            PlanningError: If the plan is not one this attempt's goal holds.
        """
        plan = self._plans.get(plan_id)
        if plan is None or plan.goal_id != attempt.goal_id:
            msg = (
                f"attempt {attempt.id} names plan {plan_id}, which this store does not "
                f"hold under goal {attempt.goal_id}; an export naming a plan it does "
                "not carry does not validate (ADR-0014 §5, ADR-0249 §11)"
            )
            raise PlanningError(msg)

    def _refuse_a_second_owner(self, attempt_id: str, goal_id: str, execution_id: str) -> None:
        """Refuse an execution reference a **different** attempt already carries (§3).

        ADR-0255 §3's execution-ownership invariant, on both attempt-writing members:
        an execution belongs to exactly one attempt, so without it one execution could
        sit in an ended attempt A and a live attempt B and a claim naming B would pass
        every other condition. **ADR-0249 §12's append-only rule is untouched** — "an
        identifier the tuple already holds is ignored rather than duplicated or
        refused" governs a repeat on the *same* attempt and says nothing about two, so
        a repeat on the owner still lands.

        Spelled out here rather than imported from ``ai_assistant.planning``, for the
        reason this module's docstring gives for the transition graph.

        Args:
            attempt_id: The attempt the reference is being written onto.
            goal_id: That attempt's goal.
            execution_id: The execution the write names.

        Raises:
            PlanningError: If any other attempt of that goal already carries it — never
                ``StaleExecutionError``, since no re-read makes an execution owned by
                attempt A valid for attempt B.
        """
        other = sorted(
            one.id for one in self._owners_of(goal_id, execution_id) if one.id != attempt_id
        )
        if other:
            msg = (
                f"attempt {attempt_id} names execution {execution_id}, which attempt "
                f"{other[0]} of that goal already carries: an execution belongs to "
                f"exactly one attempt, so a second owner is refused rather than "
                f"recorded (ADR-0255 §3)"
            )
            raise PlanningError(msg)

    def _owners_of(self, goal_id: str, execution_id: str) -> list[GoalAttempt]:
        """Every attempt of ``goal_id`` whose ``execution_ids`` names ``execution_id``.

        Args:
            goal_id: The goal whose attempts are searched.
            execution_id: The execution being claimed or referenced.

        Returns:
            The attempts naming it — exactly one in any store written since ADR-0255
            §3, and more only in one written before it.
        """
        return [
            one
            for one in self._attempts.values()
            if one.goal_id == goal_id and execution_id in one.execution_ids
        ]

    def _refuse_a_dangling_execution(self, attempt: GoalAttempt, execution_id: str) -> None:
        """Refuse an execution reference that does not resolve under this goal (§11).

        :meth:`_refuse_a_dangling_plan`'s reasoning over the second reference an
        attempt accumulates, reached through the plan the execution runs.

        Args:
            attempt: The attempt the reference is being written onto.
            execution_id: The execution the write names.

        Raises:
            PlanningError: If the execution is not one this attempt's goal holds.
        """
        state = self._executions.get(execution_id)
        plan = None if state is None else self._plans.get(state.plan_id)
        if plan is None or plan.goal_id != attempt.goal_id:
            msg = (
                f"attempt {attempt.id} names execution {execution_id}, which this store "
                f"does not hold under goal {attempt.goal_id}; an export naming an "
                "execution it does not carry does not validate (ADR-0014 §5)"
            )
            raise PlanningError(msg)

    def _advanced_attempt(self, attempt: GoalAttempt, transition: AttemptTransition) -> GoalAttempt:
        """Apply one transition to ``attempt``; the caller holds the resource.

        Every absent member leaves its field unchanged; an ``add_*`` member appends,
        and an identifier the tuple already holds is ignored rather than duplicated
        or refused (ADR-0249 §12). The phase never moves backwards, no transition
        leaves a terminal state, and neither effort counter is ever reduced.

        Args:
            attempt: The attempt as stored.
            transition: The command to apply.

        Returns:
            The attempt as it stands after the transition.

        Raises:
            IllegalTransitionError: If the move would take the phase backwards or
                move a terminal attempt to another state.
            PlanningError: If an effort counter would be reduced, or the result is
                not a shape ADR-0249 §5 admits.
        """
        state = attempt.state if transition.to_state is None else transition.to_state
        if attempt.state in TERMINAL_ATTEMPT_STATES and state is not attempt.state:
            msg = (
                f"attempt {attempt.id} is {attempt.state.value} and no transition leaves "
                f"a terminal member (ADR-0249 §5)"
            )
            raise IllegalTransitionError(msg)
        phase = attempt.phase if transition.to_phase is None else transition.to_phase
        if _PHASE_ORDER[phase] < _PHASE_ORDER[attempt.phase]:
            msg = (
                f"attempt {attempt.id} stands at {attempt.phase.value} and a phase "
                f"advances in ADR-0249 §6's order and never moves backwards"
            )
            raise IllegalTransitionError(msg)
        calls = (
            attempt.effort.planner_calls
            if transition.planner_calls is None
            else transition.planner_calls
        )
        working = attempt.effort.working if transition.working is None else transition.working
        if calls < attempt.effort.planner_calls or working < attempt.effort.working:
            msg = (
                f"attempt {attempt.id}'s effort is monotonically non-decreasing and no "
                f"implementation subtracts from it (ADR-0249 §5)"
            )
            raise PlanningError(msg)
        try:
            return GoalAttempt(
                id=attempt.id,
                goal_id=attempt.goal_id,
                opened_at=attempt.opened_at,
                phase=phase,
                state=state,
                outcome=attempt.outcome if transition.outcome is None else transition.outcome,
                # **Folded into the stored ledger rather than rebuilt from the
                # transition** (ADR-0251 §5). ``AttemptTransition`` names the two
                # counters and nothing else, so a fresh ``AttemptEffort`` here would
                # clear every member no transition can carry — ``kind`` today, and
                # whatever a later decision adds under ADR-0249 §5's licence. The kind
                # is the opening act's stamp and "is never re-stamped".
                effort=attempt.effort.model_copy(
                    update={"planner_calls": calls, "working": working}
                ),
                plan_ids=_appended_id(attempt.plan_ids, transition.add_plan_id),
                execution_ids=_appended_id(attempt.execution_ids, transition.add_execution_id),
                authorization_ids=_appended_id(
                    attempt.authorization_ids, transition.add_authorization_id
                ),
                ended_at=attempt.ended_at if transition.ended_at is None else transition.ended_at,
                version=attempt.version + 1,
            )
        except ValidationError as exc:
            msg = (
                f"the transition would leave attempt {attempt.id} in a shape "
                f"ADR-0249 §5 refuses: {exc}"
            )
            raise PlanningError(msg) from exc

    async def get_goal(self, goal_id: str) -> Goal | None:
        """Return the goal with ``goal_id``, or ``None``.

        Routed through the modelled resource, like every other read: the
        ``sqlite3`` store answers this from under its connection lock, so it is one
        of the lock sites ADR-0060's clause binds (#397).
        """
        async with self._resource.held():
            stored = self._goals.get(goal_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def save_plan(self, plan: ActionPlan) -> str:
        """Persist a plan, requiring its goal to exist and its id to be free.

        Re-planning must take a new id so the previous plan stays an intact
        audit record; an identical re-save is idempotent (ADR-0014 §2).

        **An unstamped ``targets_revision`` is refused too** (ADR-0249 §8), for the
        reason the ``supersedes`` check below is here: the window is closed at the
        store rather than trusted to close itself. A plan already on disk carrying
        ``None`` decodes, and §8's not-driven rule is what reads it.

        **A ``supersedes`` that does not resolve is refused** (ADR-0228 §5): one
        naming a plan this store does not hold, one naming the saving plan's own
        ``id``, and one naming a plan under a different ``goal_id``. That is
        ADR-0014 §5's export promise kept at write time, exactly as the orphan check
        above keeps it for ``goal_id`` — a plan whose predecessor is missing is a
        supersession whose subject has been lost, discovered only by whoever reads
        the export back.

        **And every ``StepCondition.about`` and ``PlanInterpretation.settles`` must
        already be an element id** (ADR-0253 §9), naming a **condition element** of the
        interpretation this plan's ``targets_revision`` names. It is the same window
        closed at the same place as ``targets_revision``'s, one substitution later.
        **A plan declaring neither is not checked.**

        **And every ``PlanStep.intended_action`` must already be the ``id`` of an
        intended action of this plan's goal** (ADR-0265 §4), on the identical footing
        and with the identical error class. The set is the goal's own tuple, which
        ``targets_revision`` does not narrow, because ``Goal.intended_actions`` is
        appended to rather than revised. **A plan no step of which names an action is
        not checked.**

        **And the plan is revalidated before it is kept, not merely copied** (ADR-0023
        §2): ``model_copy(update=...)`` skips validators, so a caller can hand in a plan
        whose graph ADR-0253 §§1, 6 and 8 make **unconstructible**, and "a write that
        reaches past it must re-validate".

        The tests are spelled out here rather than imported from
        :mod:`ai_assistant.planning.goals`, for the reason this module's own docstring
        gives: a fake that decided conformance by calling the code it stands in for
        would report every implementation conformant. The shared conformance suite is
        what holds the two statements honest.
        """
        snapshot = _revalidated_plan(plan)
        async with self._resource.held():
            held = self._goals.get(snapshot.goal_id)
            if held is None:
                msg = f"plan {snapshot.id} refers to unknown goal {snapshot.goal_id}"
                raise PlanningError(msg)
            self._refuse_an_unsubstituted_condition(snapshot, held)
            self._refuse_an_unsubstituted_action(snapshot, held)
            # ADR-0249 §8: the window between the planner's return and the loop's
            # stamp is closed at the store rather than trusted to close itself.
            if snapshot.targets_revision is None:
                msg = (
                    f"plan {snapshot.id} carries no targets_revision: the unstamped "
                    "state exists only between the planner's return and the loop's "
                    "stamp, and the window is closed at the store (ADR-0249 §8)"
                )
                raise PlanningError(msg)
            if snapshot.supersedes is not None:
                if snapshot.supersedes == snapshot.id:
                    msg = (
                        f"plan {snapshot.id} supersedes itself; a plan cannot replace "
                        "the plan it is"
                    )
                    raise PlanningError(msg)
                predecessor = self._plans.get(snapshot.supersedes)
                if predecessor is None:
                    msg = f"plan {snapshot.id} supersedes unknown plan {snapshot.supersedes}"
                    raise PlanningError(msg)
                if predecessor.goal_id != snapshot.goal_id:
                    msg = (
                        f"plan {snapshot.id} supersedes plan {snapshot.supersedes}, which "
                        f"is under goal {predecessor.goal_id} rather than "
                        f"{snapshot.goal_id}; a revision replaces a plan for the same goal"
                    )
                    raise PlanningError(msg)
            existing = self._plans.get(snapshot.id)
            if existing is not None and existing != snapshot:
                msg = (
                    f"plan {snapshot.id} already exists and differs; re-planning must "
                    "use a new id so the previous plan stays an intact audit record"
                )
                raise PlanningError(msg)
            self._plans[snapshot.id] = snapshot
        return snapshot.id

    @staticmethod
    def _refuse_an_unsubstituted_condition(plan: ActionPlan, goal: Goal) -> None:
        """Refuse a plan naming an element its targeted revision does not carry (§9).

        ADR-0253 §9's conjunct on ``save_plan``, and the fake's **own** statement of
        it. An element carrying no ``id`` (ADR-0253 §7) contributes nothing to the
        resolvable set, which is that clause's fail-closed direction; a revision the
        goal does not hold — one ADR-0249 §2 elided — resolves nothing at all.

        Args:
            plan: The plan being saved.
            goal: The goal it is under, read under the same resource as the write.

        Raises:
            PlanningError: If the plan names an element the targeted revision does not
                carry as a condition.
        """
        named = frozenset(
            [condition.about for step in plan.steps for condition in step.when]
            + [interpretation.settles for interpretation in plan.interpretations]
        )
        if not named:
            return
        known = frozenset(
            element.id
            for revision in goal.interpretation
            if revision.revision == plan.targets_revision
            for element in revision.conditions
            if element.id is not None
        )
        unresolved = sorted(named - known)
        if unresolved:
            msg = (
                f"plan {plan.id} names {', '.join(unresolved)}, which "
                f"{'is' if len(unresolved) == 1 else 'are'} not the id of a condition "
                f"element of revision {plan.targets_revision} of goal {plan.goal_id}: "
                f"the loop substitutes each condition label for an element id once, "
                f"and the window is closed at the store (ADR-0253 §9)"
            )
            raise PlanningError(msg)

    @staticmethod
    def _refuse_an_unsubstituted_action(plan: ActionPlan, goal: Goal) -> None:
        """Refuse a plan naming an intended action the goal does not hold (ADR-0265 §4).

        ADR-0265 §4's conjunct on ``save_plan``, and the fake's **own** statement of
        it. The set read is ``Goal.intended_actions`` whole rather than one revision's,
        because that tuple "is not revised: it is appended to" — which is the one place
        this differs from the condition conjunct beside it.

        Args:
            plan: The plan being saved.
            goal: The goal it is under, read under the same resource as the write.

        Raises:
            PlanningError: If the plan names an action the goal does not hold.
        """
        named = frozenset(
            step.intended_action for step in plan.steps if step.intended_action is not None
        )
        if not named:
            return
        unresolved = sorted(named - {action.id for action in goal.intended_actions})
        if unresolved:
            msg = (
                f"plan {plan.id} names {', '.join(unresolved)}, which "
                f"{'is' if len(unresolved) == 1 else 'are'} not the id of an intended "
                f"action of goal {plan.goal_id}: the loop substitutes each action label "
                f"for an intended action id once, and the window is closed at the store "
                f"(ADR-0265 §4)"
            )
            raise PlanningError(msg)

    async def get_plan(self, plan_id: str) -> ActionPlan | None:
        """Return the plan with ``plan_id``, or ``None`` — under the resource (#397)."""
        async with self._resource.held():
            stored = self._plans.get(plan_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def start_execution(self, plan_id: str) -> ExecutionState:
        """Open and store a fresh execution, derived from the plan's steps.

        The id is ``{plan_id}-exec-{incarnation}-{sequence}``, matching
        ``InMemoryPlanStore``: the monotonic, never-reset ``_sequence`` makes ids
        unique within one incarnation and the per-instance ``_incarnation`` nonce
        makes them unique across restarts, the non-reuse guarantee ADR-0044 §1
        makes normative (#280). The fake must not diverge here or it would
        certify a weaker contract than the real store keeps.
        """
        async with self._resource.held():
            plan = self._plans.get(plan_id)
            if plan is None:
                msg = f"cannot start an execution for unknown plan {plan_id}"
                raise PlanningError(msg)

            self._sequence += 1
            state = ExecutionState(
                id=f"{plan_id}-exec-{self._incarnation}-{self._sequence}",
                plan_id=plan.id,
                steps=tuple(StepExecution(step_id=step.id) for step in plan.steps),
                version=0,
                updated_at=self._now(),
            )
            self._executions[state.id] = state
        return state.model_copy(deep=True)

    async def commit_transition(self, transition: StepTransition) -> ExecutionState:
        """Apply one transition against the stored snapshot and persist it."""
        async with self._resource.held():
            state = self._commit_transition_locked(transition)
        return state.model_copy(deep=True)

    def _commit_transition_locked(self, transition: StepTransition) -> ExecutionState:
        """Apply and store one transition; the caller holds the resource."""
        stored = self._executions.get(transition.execution_id)
        if stored is None:
            msg = f"unknown execution {transition.execution_id}"
            raise PlanningError(msg)

        if transition.expected_version != stored.version:
            msg = (
                f"execution {stored.id} is at version {stored.version}, "
                f"but the write was computed against {transition.expected_version}"
            )
            raise StaleExecutionError(msg)

        current = stored.step(transition.step_id)
        if current is None:
            msg = f"execution {stored.id} has no step {transition.step_id}"
            raise PlanningError(msg)

        if transition.to_status not in _LEGAL_TRANSITIONS[current.status]:
            msg = (
                f"step {current.step_id} cannot go from {current.status} to {transition.to_status}"
            )
            raise IllegalTransitionError(msg)

        # ADR-0249 §8's further claim condition, read inside the same step as the
        # claim: the plan the execution runs must target its goal's current
        # interpretation revision, and a plan carrying no revision at all — the one
        # route being a row ADR-0249 §12 migrated — is not driven either.
        if transition.to_status is StepStatus.RUNNING:
            plan = self._plans.get(stored.plan_id)
            goal = None if plan is None else self._goals.get(plan.goal_id)
            if plan is not None and goal is not None and plan.targets_revision != goal.revision:
                msg = (
                    f"plan {plan.id} targets revision {plan.targets_revision} and goal "
                    f"{goal.id} stands at {goal.revision}: a plan that does not target "
                    f"the goal's current understanding is not driven (ADR-0249 §8)"
                )
                raise StaleExecutionError(msg)
            if plan is not None:
                self._refuse_an_unclaimable_attempt(stored, transition, goal_id=plan.goal_id)
                self._refuse_a_superseded_plan(stored.plan_id)

        updated = self._advance(current, transition)
        state = ExecutionState.model_validate(
            stored.model_copy(
                update={
                    "steps": tuple(
                        updated if step.step_id == updated.step_id else step
                        for step in stored.steps
                    ),
                    "version": stored.version + 1,
                    "updated_at": self._now(),
                }
            ).model_dump()
        )
        self._executions[state.id] = state
        return state

    def _refuse_an_unclaimable_attempt(
        self, stored: ExecutionState, transition: StepTransition, *, goal_id: str
    ) -> None:
        """Refuse a claim whose attempt cannot carry it (ADR-0255 §3).

        The attempt conjunct, read inside the same step as the claim: there is no
        ``await`` between this read and the write, so no decision is taken on a
        separate read. **Four limbs** — the attempt is unknown, it did not open this
        execution, its state is terminal or one of the three ADR-0249 §5 derives
        *paused* from, or the execution is named by more than one attempt of the goal.
        ``EFFECT_UNRESOLVED`` is **accepted**: the limb is not a ``RUNNING`` whitelist
        (ADR-0255 §6). The fifth case a reader expects — a claim carrying no
        ``attempt_id`` — is unconstructible, so no store refuses it.

        Spelled out here rather than imported from ``ai_assistant.planning``, for the
        reason this module's docstring gives for the transition graph.

        Args:
            stored: The execution the transition claims a step of.
            transition: The move being applied.
            goal_id: The goal its plan is under.

        Raises:
            PlanningError: On any of the four limbs — never ``StaleExecutionError``,
                because no re-read makes any of them land.
        """
        attempt_id = transition.attempt_id
        assert attempt_id is not None  # noqa: S101 — the validator's guarantee (ADR-0255 §3)
        named = self._attempts.get(attempt_id)
        if named is None:
            msg = (
                f"the claim on execution {stored.id} names attempt {attempt_id}, which "
                f"this store does not hold: a step is claimed under an attempt that "
                f"exists (ADR-0255 §3)"
            )
            raise PlanningError(msg)
        if stored.id not in named.execution_ids:
            msg = (
                f"attempt {attempt_id} did not open execution {stored.id}, so it cannot "
                f"claim a step of it: `execution_ids` is the binding, and it is "
                f"append-only (ADR-0255 §3, ADR-0249 §12)"
            )
            raise PlanningError(msg)
        if named.state in TERMINAL_ATTEMPT_STATES or named.state in _PAUSED_ATTEMPT_STATES:
            msg = (
                f"attempt {attempt_id} stands at {named.state}, so no step is claimed "
                f"under it: a terminal attempt never lives again, and a paused one "
                f"lives again only by a user act answering what it is paused on "
                f"(ADR-0255 §3)"
            )
            raise PlanningError(msg)
        owners = self._owners_of(goal_id, stored.id)
        if len(owners) != 1:
            held = ", ".join(sorted(one.id for one in owners))
            msg = (
                f"execution {stored.id} is named by {len(owners)} attempts of its goal "
                f"({held}), so no claim on it lands whichever one it names: nothing in "
                f"the record says which owns it, and picking one would invent an "
                f"ownership nobody recorded (ADR-0255 §3)"
            )
            raise PlanningError(msg)

    def _refuse_a_superseded_plan(self, plan_id: str) -> None:
        """Refuse a claim on a plan a stored plan supersedes (ADR-0255 §3).

        The successor conjunct, derived by the store and supplied by no caller, in the
        same step as the write — because §7's sweep cannot be atomic with a claim
        another turn is making, and a driver-side check would be the
        time-of-check-to-time-of-use gap §3 refuses. Its ground is permanent: a
        persisted successor is never un-persisted.

        Args:
            plan_id: The plan the claimed execution runs.

        Raises:
            PlanningError: If any stored plan names it in ``supersedes`` — never
                ``StaleExecutionError``.
        """
        successors = sorted(one.id for one in self._plans.values() if one.supersedes == plan_id)
        if successors:
            msg = (
                f"plan {plan_id} is superseded by {successors[0]}, so no further step of "
                f"it is claimed: a persisted successor is never un-persisted, and a "
                f"superseded plan drives nothing further (ADR-0255 §3, ADR-0228 §5)"
            )
            raise PlanningError(msg)

    def _advance(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Build the step's next value, re-validating so invariants still bite."""
        if transition.to_status is StepStatus.RUNNING:
            updated = self._to_running(step, transition)
        elif transition.to_status is StepStatus.AWAITING_APPROVAL:
            updated = self._to_awaiting_approval(step, transition)
        elif transition.to_status is StepStatus.SKIPPED:
            updated = self._to_skipped(step, transition)
        else:
            updated = step.model_copy(
                update={
                    "status": transition.to_status,
                    "output": transition.output,
                    "failure": transition.failure,
                    "finished_at": self._now(),
                }
            )
        return StepExecution.model_validate(updated.model_dump())

    def _to_awaiting_approval(
        self, step: StepExecution, transition: StepTransition
    ) -> StepExecution:
        """Queue the step for approval; there must be a specific tool to approve."""
        bound_tool = transition.bound_tool or step.bound_tool
        if bound_tool is None:
            msg = f"step {step.step_id} cannot await approval without a bound_tool"
            raise IllegalTransitionError(msg)
        return step.model_copy(
            update={"status": StepStatus.AWAITING_APPROVAL, "bound_tool": bound_tool}
        )

    def _to_skipped(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Skip the step, checking the reason is one this status could produce."""
        if transition.skip_reason not in _LEGAL_SKIP_REASONS.get(step.status, frozenset()):
            msg = (
                f"step {step.step_id} cannot be skipped as {transition.skip_reason} "
                f"from {step.status}"
            )
            raise IllegalTransitionError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        if transition.skip_reason is SkipReason.APPROVAL_DENIED and approval_ref is None:
            msg = f"step {step.step_id} cannot record a denial without an approval_ref"
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.SKIPPED,
                "skip_reason": transition.skip_reason,
                "approval_ref": approval_ref,
            }
        )

    def _to_running(self, step: StepExecution, transition: StepTransition) -> StepExecution:
        """Claim the step, enforcing the retry ceiling and the approval rule."""
        if step.status is StepStatus.FAILED and step.attempts >= _MAX_ATTEMPTS:
            msg = f"step {step.step_id} has used its {_MAX_ATTEMPTS} attempts"
            raise RetriesExhaustedError(msg)

        approval_ref = transition.approval_ref or step.approval_ref
        bound_tool = transition.bound_tool or step.bound_tool
        if approval_ref is None or bound_tool is None:
            msg = f"step {step.step_id} cannot run without both an approval_ref and a bound_tool"
            raise IllegalTransitionError(msg)

        if step.bound_tool is not None and bound_tool != step.bound_tool:
            # An approval covers the tool it was granted for; swapping the tool
            # here would launder it into permission for a different action.
            msg = (
                f"step {step.step_id} is bound to {step.bound_tool} and cannot switch "
                f"to {bound_tool}"
            )
            raise IllegalTransitionError(msg)

        return step.model_copy(
            update={
                "status": StepStatus.RUNNING,
                "attempts": step.attempts + 1,
                "bound_tool": bound_tool,
                "approval_ref": approval_ref,
                "started_at": self._now(),
                "finished_at": None,
                "failure": None,
                "output": None,
            }
        )

    async def get_execution(self, execution_id: str) -> ExecutionState | None:
        """Return the execution with ``execution_id``, or ``None`` — under the resource (#397)."""
        async with self._resource.held():
            stored = self._executions.get(execution_id)
            return None if stored is None else stored.model_copy(deep=True)

    async def active_executions(self) -> list[ExecutionState]:
        """Return every execution with outstanding work, oldest first.

        Insertion order, not sorted id order: ids embed a plan prefix, so
        sorting them would interleave plans and put ``exec-10`` before
        ``exec-2``.

        Routed through the modelled resource, like every other read (#397).
        """
        async with self._resource.held():
            return [
                state.model_copy(deep=True)
                for state in self._executions.values()
                if state.is_active
            ]

    async def export(self) -> PlanExport:
        """Return a portable, internally consistent snapshot — under the resource (#397)."""
        async with self._resource.held():
            return PlanExport(
                exported_at=self._now(),
                goals=tuple(goal.model_copy(deep=True) for goal in self._goals.values()),
                plans=tuple(plan.model_copy(deep=True) for plan in self._plans.values()),
                executions=tuple(
                    state.model_copy(deep=True) for state in self._executions.values()
                ),
                attempts=tuple(one.model_copy(deep=True) for one in self._attempts.values()),
                questions=tuple(one.model_copy(deep=True) for one in self._questions.values()),
                # ADR-0252 §13: exactly one history per goal the export carries, each
                # with its rows and its elision count.
                evidence=tuple(self._history_locked(goal_id) for goal_id in self._goals),
            )

    async def delete_goal(self, goal_id: str) -> GoalDeletion:
        """Delete a goal and its plan history, refusing while work is live."""
        async with self._resource.held():
            return self._delete_goal_locked(goal_id)

    def _delete_goal_locked(self, goal_id: str) -> GoalDeletion:
        """Delete a goal and its history; the caller holds the resource."""
        if goal_id not in self._goals:
            return GoalDeletion(deleted=False, blocked_by=("<no such goal>",))

        plan_ids = {plan.id for plan in self._plans.values() if plan.goal_id == goal_id}
        executions = [state for state in self._executions.values() if state.plan_id in plan_ids]

        live = sorted(state.id for state in executions if state.has_live_step)
        if live:
            return GoalDeletion(deleted=False, blocked_by=tuple(live))

        indeterminate = tuple(
            sorted(
                step.step_id
                for state in executions
                for step in state.steps
                if step.status is StepStatus.INDETERMINATE
            )
        )

        for state in executions:
            del self._executions[state.id]
        for plan_id in plan_ids:
            del self._plans[plan_id]
        # ADR-0249 §12: the cascade reaches attempts, extending ADR-0014 §5's "a goal
        # the user deletes must not leave its plan history behind". The live-step
        # refusal above is unchanged and keys on a RUNNING step, so an attempt in a
        # non-terminal state does not block a deletion no execution blocks.
        for attempt_id in [one.id for one in self._attempts.values() if one.goal_id == goal_id]:
            del self._attempts[attempt_id]
        # ADR-0250 §9: and it reaches that goal's questions, open and terminal alike.
        # An open question does not block a deletion, and `GoalDeletion` reports them
        # exactly as it reports attempts — which is to say with no count at all.
        for question_id in [one.id for one in self._questions.values() if one.goal_id == goal_id]:
            del self._questions[question_id]
        # ADR-0252 §12: and it reaches that goal's evidence, of every standing, with the
        # elision count going with the goal exactly as the rows do. No row blocks a
        # deletion.
        evidence_ids = [one.id for one in self._evidence.values() if one.goal_id == goal_id]
        for evidence_id in evidence_ids:
            del self._evidence[evidence_id]
        self._evidence_elided.pop(goal_id, None)
        del self._goals[goal_id]

        return GoalDeletion(
            deleted=True,
            plans_removed=len(plan_ids),
            executions_removed=len(executions),
            indeterminate_steps=indeterminate,
            evidence_removed=len(evidence_ids),
        )

    async def clear(self) -> int:
        """Delete everything, refusing while any execution has a live step."""
        async with self._resource.held():
            live = sorted(state.id for state in self._executions.values() if state.has_live_step)
            if live:
                msg = f"cannot clear while executions are live: {', '.join(live)}"
                raise ActiveExecutionError(msg)

            removed = (
                len(self._goals)
                + len(self._attempts)
                + len(self._questions)
                + len(self._evidence)
                + len(self._plans)
                + len(self._executions)
            )
            self._goals.clear()
            self._attempts.clear()
            self._questions.clear()
            self._evidence.clear()
            self._evidence_elided.clear()
            self._plans.clear()
            self._executions.clear()
        return removed


__all__ = ["FakeGoalAssociator", "FakePlanStore", "FakePlanner", "SkipReason"]
