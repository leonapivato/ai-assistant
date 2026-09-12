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

from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ActiveExecutionError,
    IllegalTransitionError,
    PlanningError,
    RetriesExhaustedError,
    StaleExecutionError,
)
from ai_assistant.core.types import (
    MAX_GOAL_INTERPRETATIONS,
    TERMINAL_ATTEMPT_STATES,
    ActionPlan,
    AttemptEffort,
    AttemptPhase,
    ExecutionState,
    GoalAttempt,
    GoalDeletion,
    PlanExport,
    PlannerOutput,
    SkipReason,
    StepExecution,
    StepStatus,
)
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.types import (
        AttemptTransition,
        CurrentContext,
        EvidenceDigest,
        Goal,
        GoalBrief,
        GoalRevision,
        MemoryRecord,
        ProposedUnderstanding,
        ReadAsk,
        ReadRequest,
        ShownFile,
        StepTransition,
    )
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog

#: Mirror of the ADR-0014 §4 graph; see the module docstring on duplication.
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

    **It records ADR-0240 §7's carrier and reads nothing into it either.**
    ``empty_reads`` joins :attr:`calls` as a **sixth** element, so a consumer's test can
    assert what the planner was *told* — that a turn's first call was handed ``()``,
    that a second call was handed the very ask the first plan emitted byte for byte, and
    that a read the budget did not reach, one the supply's shape blocked, one merely
    deduplicated away and a failed servicing each leave it empty — without standing a
    model up. Nothing here renders it, and nothing here changes what the fake returns on
    account of it: what a planner makes of the fact is an implementation's business, and
    §7's own clause is that "an implementation that accepts it and ignores its value
    means exactly what it meant".

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
        #: index. The sixth is ADR-0240 §7's ``empty_reads``, recorded for the reason
        #: the fifth is: §7 states a property of the **call** — that the second one
        #: receives the very ask the first plan emitted, byte for byte, and nothing the
        #: store returned — which is a fact about no return value.
        self.calls: list[
            tuple[
                GoalBrief,
                str,
                CurrentContext,
                tuple[MemoryRecord, ...],
                tuple[str, ...],
                tuple[ShownFile, ...],
                tuple[ReadAsk, ...],
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

    async def plan(  # noqa: PLR0913 — the brief plus one keyword per thing the pipeline assembled before planning, as the Protocol declares them; ADR-0230 §3, ADR-0240 §7 and ADR-0249 §7 each add to it
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        empty_reads: Sequence[ReadAsk] = (),
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
            empty_reads: The asks of this turn's already-serviced reads that came back
                empty (ADR-0240 §7). Recorded and **not acted on**, for ``files``' own
                reason: what a planner makes of the fact is an implementation's
                business, and a fake that broadened its own scripted ask on account of
                it would be a fake with an opinion the contract leaves to an
                implementation — and would put ADR-0228 §2's last clause, that no
                implementation widens a request, out of a consumer's reach. Empty is
                legal and is every first call. Frozen into a tuple, as the others are.
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
                tuple(empty_reads),
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

        Raises:
            PlanningError: If the store already holds a goal under this ``id``.
        """
        async with self._resource.held():
            if goal.id in self._goals:
                msg = (
                    f"goal {goal.id} already exists: save_goal is the opening write "
                    "alone, and a later change to a goal is a record_interpretation "
                    "(ADR-0249 §12)"
                )
                raise PlanningError(msg)
            self._goals[goal.id] = goal.model_copy(deep=True)
        return goal.id

    async def record_interpretation(self, revision: GoalRevision) -> Goal:
        """Append one interpretation revision, compare-and-swap (ADR-0249 §12).

        Re-implemented here rather than imported from ``ai_assistant.planning``, for
        the reason this module's docstring gives for the transition graph: importing
        it would pull in the very subsystem the fake stands in for. The shared
        ``PlanStoreContract`` is what holds the two statements honest.

        Raises:
            StaleExecutionError: If the stored version has moved on.
            PlanningError: If ``goal_id`` names no stored goal, or the revision does
                not follow the goal's current one.
        """
        async with self._resource.held():
            stored = self._goals.get(revision.goal_id)
            if stored is None:
                msg = f"cannot record an interpretation for unknown goal {revision.goal_id}"
                raise PlanningError(msg)
            if stored.version != revision.expected_version:
                msg = (
                    f"goal {revision.goal_id} is at version {stored.version}, not "
                    f"{revision.expected_version}: re-read it and recompute the revision"
                )
                raise StaleExecutionError(msg)
            current = stored.interpretation[-1]
            if revision.interpretation.revision != current.revision + 1:
                msg = (
                    f"goal {revision.goal_id} is at revision {current.revision}, so the "
                    f"next revision is {current.revision + 1} and not "
                    f"{revision.interpretation.revision} (ADR-0249 §1)"
                )
                raise PlanningError(msg)
            history = (*stored.interpretation, revision.interpretation)
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
            return updated.model_copy(deep=True)

    async def open_attempt(self, attempt: GoalAttempt) -> str:
        """Persist a new attempt for a stored goal (ADR-0249 §12).

        Raises:
            PlanningError: If ``goal_id`` names no stored goal, or the store already
                holds an attempt under this ``id``.
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

        Raises:
            StaleExecutionError: If the stored version has moved on.
            IllegalTransitionError: If the move is not legal from where it stands.
            PlanningError: If the attempt does not exist, or the result is not a shape
                ADR-0249 §5 admits.
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
            updated = self._advanced_attempt(stored, transition)
            self._attempts[updated.id] = updated
            return updated.model_copy(deep=True)

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
                effort=AttemptEffort(planner_calls=calls, working=working),
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
        """
        async with self._resource.held():
            if plan.goal_id not in self._goals:
                msg = f"plan {plan.id} refers to unknown goal {plan.goal_id}"
                raise PlanningError(msg)
            # ADR-0249 §8: the window between the planner's return and the loop's
            # stamp is closed at the store rather than trusted to close itself.
            if plan.targets_revision is None:
                msg = (
                    f"plan {plan.id} carries no targets_revision: the unstamped state "
                    "exists only between the planner's return and the loop's stamp, "
                    "and the window is closed at the store (ADR-0249 §8)"
                )
                raise PlanningError(msg)
            if plan.supersedes is not None:
                if plan.supersedes == plan.id:
                    msg = f"plan {plan.id} supersedes itself; a plan cannot replace the plan it is"
                    raise PlanningError(msg)
                predecessor = self._plans.get(plan.supersedes)
                if predecessor is None:
                    msg = f"plan {plan.id} supersedes unknown plan {plan.supersedes}"
                    raise PlanningError(msg)
                if predecessor.goal_id != plan.goal_id:
                    msg = (
                        f"plan {plan.id} supersedes plan {plan.supersedes}, which is under "
                        f"goal {predecessor.goal_id} rather than {plan.goal_id}; a revision "
                        "replaces a plan for the same goal"
                    )
                    raise PlanningError(msg)
            existing = self._plans.get(plan.id)
            if existing is not None and existing != plan:
                msg = (
                    f"plan {plan.id} already exists and differs; re-planning must use a new "
                    "id so the previous plan stays an intact audit record"
                )
                raise PlanningError(msg)
            self._plans[plan.id] = plan.model_copy(deep=True)
        return plan.id

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
        del self._goals[goal_id]

        return GoalDeletion(
            deleted=True,
            plans_removed=len(plan_ids),
            executions_removed=len(executions),
            indeterminate_steps=indeterminate,
        )

    async def clear(self) -> int:
        """Delete everything, refusing while any execution has a live step."""
        async with self._resource.held():
            live = sorted(state.id for state in self._executions.values() if state.has_live_step)
            if live:
                msg = f"cannot clear while executions are live: {', '.join(live)}"
                raise ActiveExecutionError(msg)

            removed = (
                len(self._goals) + len(self._attempts) + len(self._plans) + len(self._executions)
            )
            self._goals.clear()
            self._attempts.clear()
            self._plans.clear()
            self._executions.clear()
        return removed


__all__ = ["FakePlanStore", "FakePlanner", "SkipReason"]
