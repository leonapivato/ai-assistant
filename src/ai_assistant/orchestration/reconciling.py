"""ADR-0259 §§3-4, §7: the turn-start reconciliation pass and the check that follows it.

Two collaborators live here and they are **deliberately two**.

:class:`ReconciliationPass` is §4's pass — *"a concrete collaborator run **inside a
turn**, **after that turn has engaged its goal** … **over that one goal and no
other**, and **wholly before the turn's first ``Planner.plan`` call**"*. It performs
**exactly four acts, in order, and no fifth**, every one of them a repair of a
record: it reaches ``PlanStore`` and ``AuditTrail.resolution_of`` and **nothing
else**, calls neither ``StepRunner`` nor ``ToolInvoker``, stamps no
``AttemptPhase``, opens no attempt, writes no ``GoalStatus``, dispatches no step and
replays no recorded ``ALLOW`` (§5).

:class:`ReconciliationCheck` is §3's check, and §3 puts it somewhere else on purpose:
*"the check is the turn's **investigation phase's**, never the pass's, and nothing
checks on its own initiative"*. It is the one thing here that reaches
``ToolInvoker.invoke``, it takes **at most one reconciliation call per step per
turn**, and it resolves only what §3's conjunction admits — a committed
``bound_tool`` whose recorded ``ToolDefinition`` is **not** ``side_effecting``
**and** a ``PermissionDecision`` carrying **no** ``egress_binding``. Every other
``INDETERMINATE`` step is uncheckable — *"every side-effecting step whatever its
``Idempotency``, ``NATURAL`` included, and every egress step whatever its
declaration"* — and is left exactly as it stood.

**It is a reconciliation and not a retry** (§3). ADR-0029 §5's exclusion binds
verbatim and is not relaxed: the one call admitted is a **read**, which ADR-0029 §4
rules changes nothing when repeated, and no clause here re-calls a side-effecting
tool of any declaration.

**What the two share is the turn's remainder and nothing else.**
:class:`TurnRemainder` reads a **monotonic** source, which is ADR-0255 §9's own
discipline — *"every unit of work the walk starts"* — and the two gates are stated
separately: the pass gates **each candidate** of each of its four acts (§4), and the
check gates the one call it makes and passes the remainder as that call's
``timeout`` (§3). Neither is derived from the other, and **the pass passes a
``timeout`` nowhere**.

**Neither writes anything about the uncertainty beyond act 3's attempt state.** The
step's own ``INDETERMINATE`` status is *"the authoritative record of the
uncertainty"* (ADR-0255 §6), so no mark is minted, no model gains a field and no
``PlanStore`` member is added for one (§9).

**What is *not* here.** No retry policy (§10): nothing re-calls a side-effecting
tool, nothing re-drives a stopped walk (§7), and no ``INDETERMINATE`` step is moved
anywhere but ``SUCCEEDED`` — the one row out of it ADR-0014 §4 gains. No ``ALLOW`` is
replayed, no ``StepRunner.resume`` is called, no permission record is authored and
``StepRunner`` is touched in nothing (§5, §11).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum, auto
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import (
    AuditError,
    AuthorisationSpentError,
    PlanningError,
    SpendCeilingError,
    SpendUndeterminedError,
    ToolBindingError,
    UnrecordedAuthorisationError,
)
from ai_assistant.core.types import (
    ActionRequest,
    AttemptState,
    AttemptTransition,
    PermissionOutcome,
    SkipReason,
    StepStatus,
    StepTransition,
    ToolCall,
    ToolOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from ai_assistant.core.protocols import AuditTrail, PlanStore, ToolInvoker
    from ai_assistant.core.types import (
        ActionPlan,
        ExecutionState,
        GoalAttempt,
        PermissionDecision,
        PlanStep,
        StepExecution,
    )

#: ADR-0255 §7's two source statuses for a supersession sweep, which
#: ``planning/execution.py``'s ``_LEGAL_SKIP_REASONS`` admits ``SUPERSEDED`` from:
#: *"``AWAITING_APPROVAL`` steps are swept as well as ``PENDING`` ones, and that is
#: stated rather than left to the word *pending*"*.
_SWEPT_FROM: Final = frozenset({StepStatus.PENDING, StepStatus.AWAITING_APPROVAL})

#: Act 2's one source status (ADR-0259 §4).
_PARKED: Final = frozenset({StepStatus.AWAITING_APPROVAL})

#: What act 4 waits on: *"no step of any of its executions stands ``INDETERMINATE``
#: or ``RUNNING``"* (§4, §7).
_OUTSTANDING: Final = frozenset({StepStatus.INDETERMINATE, StepStatus.RUNNING})

#: ADR-0259 §3's **six declared refusals of this call** — *"exactly six of them are
#: refusals of this call that a later turn could meet differently"* — named one by
#: one rather than folded into a base class. ``AuthorisationSpentError`` and
#: ``UnrecordedAuthorisationError`` are ``AuditError`` subclasses and are still named,
#: because this tuple is §3's own enumeration and a reader checks it against the ADR
#: rather than against the class hierarchy. **Nothing wider is caught**: a
#: ``ValueError``, a bare ``RuntimeError`` from a broken invoker and a
#: ``CancelledError`` each propagate out of the check unchanged (§3), because *"a seam
#: that raises where its contract says it returns is broken, and catching it would
#: repeat one silent failure on **every** engagement of the goal for ever"*.
_DECLARED_REFUSALS: Final[tuple[type[Exception], ...]] = (
    ToolBindingError,
    SpendCeilingError,
    SpendUndeterminedError,
    AuthorisationSpentError,
    UnrecordedAuthorisationError,
    AuditError,
)

#: The endings §4 gives the pass — *"a stale ``expected_version`` or a **failure of
#: either store it reads — ``PlanStore``, or the trail through ``resolution_of``,
#: whose ``AuditError`` is one such failure — ends the pass for that turn**"*.
#: ``StaleExecutionError`` is a ``PlanningError``, so the compare-and-swap that loses
#: arrives here too, which is §4's *"stops at the first that loses"*.
_PASS_ENDINGS: Final[tuple[type[Exception], ...]] = (PlanningError, AuditError)

_ZERO: Final = timedelta(0)


@dataclass(frozen=True, slots=True)
class TurnRemainder:
    """How much of the turn's budget is left, read from a monotonic source.

    ADR-0255 §9 rules that *"immediately before it begins **any** of them"* the
    remainder is read from that turn's **monotonic** source and nothing is started
    where it is **not strictly positive**. A wall clock cannot serve: ADR-0009 gives
    the injected clock no monotonicity, so an adjustment backwards would hand a gate
    a remainder larger than one an earlier read observed.

    **One of these per turn, shared by the pass and the check**, so that both measure
    the same turn while each reads it itself immediately before its own unit of work.

    Attributes:
        budget: The turn's whole budget.
        started: The monotonic reading the turn began at.
        monotonic: The source, injected on ADR-0026's discipline so an arm can drive
            it. It returns seconds and need not relate to any wall clock.
    """

    budget: timedelta
    started: float
    monotonic: Callable[[], float] = time.monotonic

    @classmethod
    def opened(
        cls, budget: timedelta, *, monotonic: Callable[[], float] = time.monotonic
    ) -> TurnRemainder:
        """Open a remainder now, reading ``monotonic`` once for its start.

        Args:
            budget: The turn's whole budget.
            monotonic: The source to measure against.

        Returns:
            The remainder, which callers then call to read what is left.
        """
        return cls(budget=budget, started=monotonic(), monotonic=monotonic)

    def __call__(self) -> timedelta:
        """What is left of the budget at this instant.

        Returns:
            The remainder. It may be zero or negative — the gate's test is **strictly
            positive**, and a non-positive value is reported rather than floored so
            that no caller can mistake an exhausted budget for a tiny one.
        """
        return self.budget - timedelta(seconds=self.monotonic() - self.started)


def _positive(remainder: timedelta) -> bool:
    """Whether a unit of work may be started on this remainder (ADR-0255 §9)."""
    return remainder > _ZERO


@dataclass(frozen=True, slots=True)
class Reconciled:
    """What one turn's check found and what it established (ADR-0259 §3).

    **Neither member is a record of anything** (§4): the step's own status is the
    authoritative record. These exist so the turn can *say* what it found rather than
    resolve it silently, which is what §3's surfacing clause asks and what arm 9
    asserts — *"an implementation that resolved the step silently … fails this arm"*.

    Attributes:
        uncertain: The ids of the steps the check found standing ``INDETERMINATE``
            for this goal, in the order it found them, and read **before** it
            reconciled any of them: what the user is told is that the assistant is
            unsure whether the action went through, and a step the check went on to
            establish is one it was unsure about when the turn began.
        established: The ids of the steps the check committed ``INDETERMINATE →
            SUCCEEDED``, in commit order. A subsequence of :attr:`uncertain`.
    """

    uncertain: tuple[str, ...] = ()
    established: tuple[str, ...] = ()


class _Verdict(Enum):
    """What one candidate of §3's check produced, for the loop above it."""

    #: The call returned a successful ``ToolResult`` and the step is ``SUCCEEDED``.
    ESTABLISHED = auto()
    #: The step is uncheckable (§3's conjunction refuses it). **No call was made**,
    #: the step stays ``INDETERMINATE``, and the check goes on to the next candidate:
    #: §3 ends the check on a *refusal of this call*, and an uncheckable step is one
    #: no call was ever admitted for.
    UNCHECKABLE = auto()
    #: The check ends here — the call could not be built, the call returned anything
    #: but a success, one of §3's six declared refusals was raised, the commit lost a
    #: compare-and-swap, or the remainder ran out. In every case *"the step stays
    #: ``INDETERMINATE``, the check ends there, no second step of that turn is
    #: reconciled, nothing is retried inside the turn … and the turn does not fail"*.
    ENDED = auto()


@dataclass(slots=True)
class _Residual:
    """One read of everything the pass and the check work over, for one goal.

    Assembled from ``attempts_of`` and the ids the attempts themselves carry —
    ``plan_ids`` and ``execution_ids`` — because ``PlanStore`` offers no *"every plan
    of this goal"* member and **this decision adds none**: ADR-0259 §9 rules the store
    gains exactly one member, ``claim_effect``, and L1 landed it.

    **Mutable on purpose.** Every write the pass makes is its own compare-and-swap
    returning the row it wrote, and the next act has to see that row rather than the
    one the opening read returned — which is what keeps act 4's *"no step … stands
    ``INDETERMINATE`` or ``RUNNING``"* a question about the record as it now stands.

    Attributes:
        attempts: The goal's attempts, in the store's own order.
        executions: Every execution those attempts name, by id.
        plans: Every plan those attempts name, and every plan those executions run,
            by id.
        superseded: The ids of the plans a stored plan supersedes, computed from
            ``ActionPlan.supersedes`` — the corpus's own direction for the link
            (ADR-0228 §5).
    """

    attempts: list[GoalAttempt] = field(default_factory=list)
    executions: dict[str, ExecutionState] = field(default_factory=dict)
    plans: dict[str, ActionPlan] = field(default_factory=dict)
    superseded: frozenset[str] = frozenset()

    def plan_of(self, state: ExecutionState) -> ActionPlan | None:
        """The plan an execution runs, or ``None`` where the store answered none."""
        return self.plans.get(state.plan_id)

    def walk(self) -> Iterator[ExecutionState]:
        """Every execution of every attempt, once each, in attempt order."""
        seen: set[str] = set()
        for attempt in self.attempts:
            for execution_id in attempt.execution_ids:
                if execution_id in seen:
                    continue
                seen.add(execution_id)
                held = self.executions.get(execution_id)
                if held is not None:
                    yield held

    def standing(self, attempt: GoalAttempt, statuses: frozenset[StepStatus]) -> bool:
        """Whether any step of any execution ``attempt`` names stands at one of these."""
        return any(
            step.status in statuses
            for execution_id in attempt.execution_ids
            if (held := self.executions.get(execution_id)) is not None
            for step in held.steps
        )


async def _read_residual(plans: PlanStore, goal_id: str) -> _Residual:
    """Read the goal's attempts, their plans and their executions, once.

    **Every store failure propagates**, because what a failure *means* is the
    caller's: for the pass it is *end this turn's pass* (§4), and for the check it is
    *leave every step where it stood* (§3).

    Args:
        plans: The planning store.
        goal_id: The goal the turn engaged, and no other (§4).

    Returns:
        The residual.

    Raises:
        PlanningError: As the store's own reads raise it.
    """
    residual = _Residual(attempts=list(await plans.attempts_of(goal_id)))
    for attempt in residual.attempts:
        for plan_id in attempt.plan_ids:
            await _hold_plan(plans, plan_id, residual)
        for execution_id in attempt.execution_ids:
            if execution_id in residual.executions:
                continue
            state = await plans.get_execution(execution_id)
            if state is None:
                # A store that kept its closure answers every id an attempt names;
                # one that did not leaves nothing here for an act to work over, which
                # is the direction ``_every_step_settled`` already takes for the same
                # read.
                continue
            residual.executions[execution_id] = state
            await _hold_plan(plans, state.plan_id, residual)
    residual.superseded = frozenset(
        plan.supersedes for plan in residual.plans.values() if plan.supersedes is not None
    )
    return residual


async def _hold_plan(plans: PlanStore, plan_id: str, residual: _Residual) -> None:
    """Read one plan into ``residual`` unless it is already held."""
    if plan_id in residual.plans:
        return
    plan = await plans.get_plan(plan_id)
    if plan is not None:
        residual.plans[plan_id] = plan


def _reached_by_uncertainty(state: ExecutionState, plan: ActionPlan | None) -> frozenset[str]:
    """The steps ADR-0255 §6's override keeps out of a sweep.

    §6 states the prohibition *"over exactly three sets of steps and over no others:
    the **``INDETERMINATE`` step itself**, **its dependents, transitively**, and
    **every step the walk did not reach**, which behind an ``INDETERMINATE`` step is
    every step after it in ``steps`` order"*. **This rule overrides §7's supersession
    clause**, and ADR-0259 §4 restates it over acts 1 and 2 — *"a sweep that meets one
    **is not thereby partial**"*.

    The positions are the **execution's** ``steps`` order, which is the order the walk
    took; the dependency closure is read off the **plan**, which is where
    ``depends_on`` lives. A plan the store did not answer for contributes no closure
    and the positional half still binds, which is the conservative direction: the half
    that is computable already keeps every later step out.

    Args:
        state: The execution.
        plan: The plan it runs, or ``None``.

    Returns:
        The ids of the steps no act may sweep. Empty where nothing stands
        ``INDETERMINATE``, which is every execution the uncertainty never reached.
    """
    uncertain = [
        index for index, step in enumerate(state.steps) if step.status is StepStatus.INDETERMINATE
    ]
    if not uncertain:
        return frozenset()
    reached = {step.step_id for step in state.steps[min(uncertain) :]}
    if plan is not None:
        roots = {state.steps[index].step_id for index in uncertain}
        reached |= _dependents_of(roots, steps=plan.steps)
    return frozenset(reached)


def _dependents_of(roots: set[str], *, steps: Sequence[PlanStep]) -> set[str]:
    """The transitive dependents of ``roots`` within ``steps`` (ADR-0253 §2).

    Walked to a fixed point rather than in one pass: ``steps`` is a dependency order
    by construction, but a plan that named a dependent before its producer would
    otherwise leave a step §6 protects out of the set, and that is the unsafe
    direction.
    """
    reached = set(roots)
    while True:
        grown = reached | {step.id for step in steps if reached & set(step.depends_on)}
        if grown == reached:
            return reached - roots
        reached = grown


def _candidates(
    state: ExecutionState, statuses: frozenset[StepStatus], protected: frozenset[str]
) -> list[StepExecution]:
    """The steps of ``state`` an act may take, in the execution's own order."""
    return [
        step for step in state.steps if step.status in statuses and step.step_id not in protected
    ]


class ReconciliationPass:
    """ADR-0259 §4's four-act pass: inside one turn, over one goal, repairing records.

    **It reaches a dispatch through no act at all.** Every act is a compare-and-swap
    on a record the store already holds; none calls ``StepRunner`` or
    ``ToolInvoker``, none takes or passes a ``timeout``, and none takes §3's check —
    *"which is the investigation phase's"*.

    **It stops at the first write that loses**, and a failure of either store it reads
    ends it the same way: *"what landed stands, nothing is undone, nothing is retried
    within the turn"*, and **the turn does not fail**. A ``CancelledError`` is not an
    early end and is never a store failure — it propagates unchanged at whatever await
    it arrives, and no further act is taken after one.

    **It infers nothing** (§4): ``EFFECT_UNRESOLVED`` is *written* by act 3, never
    derived at read time, and ``SUPERSEDED`` is committed by act 1, never inferred
    from a ``supersedes`` chain by a consumer.
    """

    def __init__(self, *, plans: PlanStore, trail: AuditTrail) -> None:
        """Wire the pass to the two stores §4 admits, and to nothing else.

        Args:
            plans: The planning store, read and written by every act.
            trail: The audit trail — read by act 2 through ``resolution_of`` and
                **written by no act**: §9 rules ``AuditTrail`` gains no member and the
                pass writes none of it.
        """
        self._plans = plans
        self._trail = trail

    async def run(self, goal_id: str, *, remaining: TurnRemainder) -> None:
        """Perform the four acts over one goal, in order, gating each candidate.

        Args:
            goal_id: The goal the turn engaged (ADR-0250 §1), and no other — a second
                goal carrying the same residuals is untouched until a turn engages it.
            remaining: The turn's remainder, read immediately before **each
                candidate**, since *"the gated unit is one candidate, not one act"*.
                It is never handed to a callable from inside this pass.

        Raises:
            asyncio.CancelledError: Delivered at any await and propagated unchanged;
                the turn is cancelled rather than continued (ADR-0060).
        """
        try:
            residual = await _read_residual(self._plans, goal_id)
            for act in (
                self._sweep_superseded,
                self._apply_refusals,
                self._repair_attempts,
                self._release_attempts,
            ):
                if not await act(residual, remaining=remaining):
                    return
        except _PASS_ENDINGS:
            # §4: the pass ends for this turn, what landed stands, nothing is retried
            # within the turn, and **the turn does not fail** — every act is a repair
            # of a record, not a prerequisite of the turn's work. The next turn that
            # engages the goal runs the pass again over whatever is then residual.
            return

    async def _sweep_superseded(self, residual: _Residual, *, remaining: TurnRemainder) -> bool:
        """Act 1 — complete a supersession sweep (ADR-0255 §7, ADR-0259 §4).

        *"For every plan of that goal that a stored plan supersedes, each step
        standing ``PENDING`` or ``AWAITING_APPROVAL`` is committed ``→ SKIPPED`` with
        ``skip_reason=SUPERSEDED``, which is ADR-0255 §7's own sweep, from its own two
        source statuses."*

        **This act releases no effect row and deletes none**: a row is reached only
        through ``claim_effect``, and freeing the claim of a ``FAILED`` holder whose
        plan is superseded is that member's own branch, *"decided in the store because
        only there is it atomic with the write"*.

        Returns:
            Whether the pass may take a later act.
        """
        for state in list(residual.walk()):
            plan = residual.plan_of(state)
            if plan is None or plan.id not in residual.superseded:
                continue
            if not await self._sweep(residual, state.id, remaining=remaining):
                return False
        return True

    async def _sweep(
        self, residual: _Residual, execution_id: str, *, remaining: TurnRemainder
    ) -> bool:
        """Sweep one execution's undisposed steps, gating before each of them."""
        held = residual.executions[execution_id]
        protected = _reached_by_uncertainty(held, residual.plan_of(held))
        for step in _candidates(held, _SWEPT_FROM, protected):
            if not _positive(remaining()):
                return False
            held = await self._plans.commit_transition(
                StepTransition(
                    execution_id=held.id,
                    step_id=step.step_id,
                    to_status=StepStatus.SKIPPED,
                    expected_version=held.version,
                    skip_reason=SkipReason.SUPERSEDED,
                )
            )
            residual.executions[held.id] = held
        return True

    async def _apply_refusals(self, residual: _Residual, *, remaining: TurnRemainder) -> bool:
        """Act 2 — apply a recorded refusal (ADR-0259 §4, §5).

        *"For every step standing ``AWAITING_APPROVAL`` on a plan **no** stored plan
        supersedes whose binding ``AuditTrail.resolution_of`` answers **``DENY``**,
        commit ``AWAITING_APPROVAL → SKIPPED`` with ``skip_reason=APPROVAL_DENIED``,
        naming that decision. **A refusal is a repair and reaches no dispatch**, so it
        belongs here."*

        **The ``ALLOW`` half is not taken by this decision at all** (§5). A recorded
        ``ALLOW`` is left exactly as it stands, its resolution unspent in the trail;
        this act calls no ``StepRunner.resume``, reaches no ``ToolInvoker.invoke``,
        claims no effect, commits no transition for it and authors no permission
        record. *"An implementation that replayed it fails this row, and it is the row
        that pins §5's asymmetry."*

        Returns:
            Whether the pass may take a later act.
        """
        for state in list(residual.walk()):
            plan = residual.plan_of(state)
            if plan is None or plan.id in residual.superseded:
                continue
            if not await self._refuse(residual, state.id, remaining=remaining):
                return False
        return True

    async def _refuse(
        self, residual: _Residual, execution_id: str, *, remaining: TurnRemainder
    ) -> bool:
        """Apply one execution's recorded refusals, gating before each candidate."""
        held = residual.executions[execution_id]
        protected = _reached_by_uncertainty(held, residual.plan_of(held))
        for step in _candidates(held, _PARKED, protected):
            if not _positive(remaining()):
                return False
            decision = await self._trail.resolution_of(execution_id=held.id, step_id=step.step_id)
            if decision is None or decision.ruling.outcome is not PermissionOutcome.DENY:
                continue
            held = await self._plans.commit_transition(
                StepTransition(
                    execution_id=held.id,
                    step_id=step.step_id,
                    to_status=StepStatus.SKIPPED,
                    expected_version=held.version,
                    skip_reason=SkipReason.APPROVAL_DENIED,
                    approval_ref=decision.id,
                )
            )
            residual.executions[held.id] = held
        return True

    async def _repair_attempts(self, residual: _Residual, *, remaining: TurnRemainder) -> bool:
        """Act 3 — repair the attempt's state (ADR-0259 §4, §6).

        *"For every attempt of that goal whose ``state`` is ``RUNNING`` and one of
        whose executions holds a step standing ``INDETERMINATE``, commit it
        ``EFFECT_UNRESOLVED`` through ``commit_attempt``."*

        There are **exactly two** producers of that state in the corpus — the driver,
        for a step it drove (ADR-0255 §6), and this act — and **the startup recovery
        scan is not one**: it writes no ``AttemptState`` at all (§6), so the residual
        it leaves is repaired when the goal is next engaged and not before.

        Returns:
            Whether the pass may take a later act.
        """
        for index, attempt in enumerate(residual.attempts):
            if attempt.state is not AttemptState.RUNNING:
                continue
            if not residual.standing(attempt, frozenset({StepStatus.INDETERMINATE})):
                continue
            if not _positive(remaining()):
                return False
            residual.attempts[index] = await self._plans.commit_attempt(
                AttemptTransition(
                    attempt_id=attempt.id,
                    expected_version=attempt.version,
                    to_state=AttemptState.EFFECT_UNRESOLVED,
                )
            )
        return True

    async def _release_attempts(self, residual: _Residual, *, remaining: TurnRemainder) -> bool:
        """Act 4 — release the attempt (ADR-0259 §4, §7).

        *"Where an attempt stands ``EFFECT_UNRESOLVED`` and **no** step of any of its
        executions stands ``INDETERMINATE`` or ``RUNNING``, commit it ``RUNNING``."*
        ``EFFECT_UNRESOLVED`` is **not terminal** (ADR-0249 §5), so the move is legal;
        **no lane moves an attempt out of a terminal state**, and **no lane moves it to
        ``RUNNING`` while an uncertain effect stands**. No ``AttemptOutcome`` is
        written — a non-terminal state with no outcome is the shape ADR-0249 §5's
        validator requires, and which member an attempt earns is A10's.

        Returns:
            Whether the pass may take a later act. There is no fifth, so the value is
            read by nothing but symmetry with the other three.
        """
        for index, attempt in enumerate(residual.attempts):
            if attempt.state is not AttemptState.EFFECT_UNRESOLVED:
                continue
            if residual.standing(attempt, _OUTSTANDING):
                continue
            if not _positive(remaining()):
                return False
            residual.attempts[index] = await self._plans.commit_attempt(
                AttemptTransition(
                    attempt_id=attempt.id,
                    expected_version=attempt.version,
                    to_state=AttemptState.RUNNING,
                )
            )
        return True


class ReconciliationCheck:
    """ADR-0259 §3's check: the investigation phase's, never the pass's.

    *"An effect left ``INDETERMINATE`` is **surfaced to the user in the next turn's
    investigation phase** — the assistant says it is unsure whether the action went
    through — and is **verified there only where a read the assistant is already
    permitted to make can establish it**."*

    **What it admits is a read and nothing else.** A step is reconcilable exactly
    where the ``ToolDefinition`` recorded for its committed ``bound_tool`` is **not
    ``side_effecting``** *and* the ``PermissionDecision`` its ``approval_ref`` names
    carries **no ``egress_binding``** — the complete conjunction, never one half of
    it. A side-effecting ``NATURAL`` tool is excluded because its declaration is about
    the **effect** and not about the answer; an egress step is excluded because
    ADR-0148 §9 rules the seam it would go through.

    **The request is rebuilt from durable state and the rebuild is proved rather than
    trusted**: the step is read from the stored plan, the decision from the trail, and
    ``PermissionDecision.authorises`` is what says the rebuild reproduced the
    authorised call. Where it returns false **no call is made** and the step stays
    ``INDETERMINATE``, which is the safe direction.

    **It takes no step claim** (ADR-0014 §4's claim-before-invocation rule is stated
    over the ``→ RUNNING`` transition, and a reconciliation makes none), and the
    concurrency that leaves is admitted rather than overlooked: two turns may each make
    the call, and **both ``→ SUCCEEDED`` commits are compare-and-swaps on one
    ``ExecutionState``, so exactly one lands**.
    """

    def __init__(self, *, plans: PlanStore, trail: AuditTrail, invoker: ToolInvoker) -> None:
        """Wire the check to the store, the trail and the one seam §3 admits.

        Args:
            plans: The planning store — read for the residual, written only by the one
                ``INDETERMINATE → SUCCEEDED`` commit a returning call earns.
            trail: The audit trail, read through ``get`` for the decision a step's
                ``approval_ref`` names. **Nothing is recorded**: no ``ActionPolicy``
                call is taken, no new decision is authored and no new authority is
                sought (§3).
            invoker: The seam. ``ToolInvoker`` gains no member and no signature moves
                (§9); this is the ordinary ``invoke``, which appends its own invocation
                claim and completion like any other call.
        """
        self._plans = plans
        self._trail = trail
        self._invoker = invoker

    async def run(self, goal_id: str, *, remaining: TurnRemainder) -> Reconciled:
        """Surface this goal's uncertain effects and reconcile what §3 admits.

        **At most one reconciliation call per step per turn**, and no step the same
        turn already reconciled is re-called. The candidates are read once, before any
        call, so the set the turn surfaces is the set that stood when it began.

        Args:
            goal_id: The goal the turn engaged, and no other.
            remaining: The turn's remainder, read immediately before the call and
                passed as its ``timeout`` — ADR-0255 §9's rule reaching this call
                *"wherever the call is taken"*, and the one ``timeout`` this decision
                passes anywhere.

        Returns:
            What was found and what was established. An empty
            :class:`Reconciled` where the goal holds no uncertain effect, and where
            the store could not be read at all.

        Raises:
            asyncio.CancelledError: Propagated unchanged, as at every other await in
                this system, and never counted among §3's six.
            Exception: Any exception ``ToolInvoker.invoke``'s contract does not name —
                a ``ValueError``, a broken seam's own defect — propagated unchanged
                out of the check and into the turn's own work (§3).
        """
        try:
            residual = await _read_residual(self._plans, goal_id)
        except PlanningError:
            # The same store failure §4 answers for its own reads, answered the same
            # way: nothing is written, no call is made, and the turn does not fail.
            return Reconciled()
        candidates = [
            (state, step)
            for state in residual.walk()
            for step in state.steps
            if step.status is StepStatus.INDETERMINATE
        ]
        established: list[str] = []
        for state, step in candidates:
            verdict = await self._reconcile(residual, state.id, step, remaining=remaining)
            if verdict is _Verdict.ESTABLISHED:
                established.append(step.step_id)
            elif verdict is _Verdict.ENDED:
                break
        return Reconciled(
            uncertain=tuple(step.step_id for _, step in candidates),
            established=tuple(established),
        )

    async def _reconcile(  # noqa: C901, PLR0911 — ADR-0259 §3 enumerates the ways a reconciliation does not happen, and arm 10 is a table with one row per way; one exit per clause is the decision rather than a shape to fold, and folding any pair would put two of §3's cases behind one branch
        self,
        residual: _Residual,
        execution_id: str,
        step: StepExecution,
        *,
        remaining: TurnRemainder,
    ) -> _Verdict:
        """Take §3's one call for one step, or say why none was taken."""
        held = residual.executions[execution_id]
        plan = residual.plan_of(held)
        planned = None if plan is None else _planned_step(plan, step.step_id)
        if plan is None or planned is None:
            # The call cannot be built: there is no stored step to rebuild the request
            # from. Nothing is written and the step stays `INDETERMINATE`.
            return _Verdict.ENDED
        if step.approval_ref is None:
            return _Verdict.ENDED
        try:
            decision = await self._trail.get(step.approval_ref)
        except AuditError:
            # *"A closed, corrupt or unreadable trail, which is the same store failure
            # §4 answers for its own reads and is answered the same way here."* The
            # read is taken **before** `ToolInvoker.invoke`, so it reaches no seam and
            # is not one of §3's six.
            return _Verdict.ENDED
        if decision is None:
            return _Verdict.ENDED
        if not _reconcilable(decision, step):
            # *"Every other `INDETERMINATE` step is uncheckable"* — it stays uncertain,
            # its attempt stays `EFFECT_UNRESOLVED`, its key answers `UNCERTAIN` to
            # every later claim, and **no call is made**. The check goes on: §3 ends it
            # on a *refusal of this call*, and no call was ever admitted here.
            return _Verdict.UNCHECKABLE
        request = ActionRequest(
            tool=decision.tool,
            parameters=planned.parameters,
            goal=plan.goal_id,
            intended_action=planned.intended_action,
            step_id=planned.id,
            execution_id=held.id,
        )
        if not decision.authorises(request):
            # *"A rebuild that drifted — a plan edited, a reference whose producer's
            # output changed, a binding no longer available — fails that comparison and
            # the step stays uncertain, which is the safe direction."*
            return _Verdict.ENDED
        remainder = remaining()
        if not _positive(remainder):
            return _Verdict.ENDED
        try:
            result = await self._invoker.invoke(
                ToolCall(request=request, decision=decision), timeout=remainder
            )
        except _DECLARED_REFUSALS:
            # §3's six. *"On those six the reconciliation writes nothing, the step stays
            # `INDETERMINATE`, the check ends there, no second step of that turn is
            # reconciled, nothing is retried inside the turn, none of them escapes into
            # the turn's own work, and the turn does not fail."*
            return _Verdict.ENDED
        if result.outcome is not ToolOutcome.SUCCEEDED:
            # *"Neither a failed reconciliation nor an unbuildable one is ever read as
            # establishing that the effect did not happen."* `INDETERMINATE → FAILED`
            # stays illegal and no row is added for it (§7).
            return _Verdict.ENDED
        try:
            residual.executions[held.id] = await self._plans.commit_transition(
                StepTransition(
                    execution_id=held.id,
                    step_id=step.step_id,
                    to_status=StepStatus.SUCCEEDED,
                    expected_version=held.version,
                    output=result.output,
                )
            )
        except PlanningError:
            # The stale compare-and-swap §3's admitted concurrency produces: *"the loser
            # writes nothing, retries nothing, makes no second reconciliation call and
            # does not fail its turn, whose own work continues."* `attempts` is not
            # incremented on either side — the store's tracker leaves it untouched on
            # every row of §7's three.
            return _Verdict.ENDED
        return _Verdict.ESTABLISHED


def _reconcilable(decision: PermissionDecision, step: StepExecution) -> bool:
    """ADR-0259 §3's conjunction, read off the recorded declaration.

    *"A step is reconcilable exactly where the ``ToolDefinition`` recorded for its
    committed ``bound_tool`` is **not ``side_effecting``** *and* the
    ``PermissionDecision`` its ``approval_ref`` names carries **no
    ``egress_binding``** — the complete conjunction, never one half of it."*

    The declaration is read from the decision, which carries *"the whole
    ``ToolDefinition``, embedded by value"* — never from a registry lookup a mutated
    declaration could answer differently, which is ``interrupted_outcome``'s own stated
    reason. A decision whose embedded definition is not the one the step committed as
    its ``bound_tool`` is **not** that recorded declaration, so such a step is left
    uncertain rather than checked against a definition the record does not pair it
    with.

    **This is narrower than ADR-0192 §1's non-spendability and is its own test.** The
    non-spendable set is two declarations — a read and a side-effecting ``NATURAL``
    tool — and only the first is admitted here.

    Args:
        decision: The decision the step's ``approval_ref`` names.
        step: The step, for the ``bound_tool`` it committed.

    Returns:
        Whether §3 admits a reconciliation call for it.
    """
    return (
        step.bound_tool == decision.tool.id
        and not decision.tool.side_effecting
        and decision.egress_binding is None
    )


def _planned_step(plan: ActionPlan, step_id: str) -> PlanStep | None:
    """The plan's step with ``step_id``, or ``None`` where it carries none."""
    return next((step for step in plan.steps if step.id == step_id), None)


class ReconciliationStage:
    """The pass and the check, wired together and run in §4's and §3's order.

    **They stay two objects** — §3 rules the check *"is the turn's investigation
    phase's, never the pass's"* and §4 rules the pass *"performs no verification at
    all"* — and this composes them for one caller so the turn holds one collaborator
    rather than two and one remainder rather than two.

    *"§4's acts 1-4 run first and leave the uncertain step standing ``INDETERMINATE``
    with its attempt repaired to ``EFFECT_UNRESOLVED`` by act 3; the turn's
    **investigation phase** then surfaces and checks it (§3); and **both are before
    the turn's first ``Planner.plan`` call**, so the planner reads the record settled
    where the check resolved it and still ``INDETERMINATE`` where it did not"* (§7).
    """

    def __init__(
        self,
        *,
        plans: PlanStore,
        trail: AuditTrail,
        invoker: ToolInvoker,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Wire both halves.

        Args:
            plans: The planning store both halves read.
            trail: The audit trail — ``resolution_of`` for act 2, ``get`` for the
                check. Neither writes it.
            invoker: The seam, reached by the check alone and by no act of the pass.
            monotonic: The turn's monotonic source (ADR-0255 §9), injected so an arm
                can drive it.
        """
        self._pass = ReconciliationPass(plans=plans, trail=trail)
        self._check = ReconciliationCheck(plans=plans, trail=trail, invoker=invoker)
        self._monotonic = monotonic

    def opened(self, budget: timedelta) -> TurnRemainder:
        """Open the turn's remainder **now**, against this stage's monotonic source.

        **Called at the turn's entry and not at this stage's**, which is ADR-0255 §9's
        *"the turn's remaining budget"* read literally: a turn that spent most of its
        budget resolving its conversation and its goal before it reached the pass has
        that much less left, and a remainder opened here would hand §3's call the whole
        figure again. The two are separated so the caller states when the turn began and
        this stage states what it is measured against.

        Args:
            budget: The turn's whole budget.

        Returns:
            The remainder, to be handed back to :meth:`run`.
        """
        return TurnRemainder.opened(budget, monotonic=self._monotonic)

    async def run(self, goal_id: str, *, remaining: TurnRemainder) -> Reconciled:
        """Run the pass and then the check, over one goal, under one remainder.

        Args:
            goal_id: The goal the turn engaged.
            remaining: The turn's remainder, opened at the turn's entry
                (:meth:`opened`) and read by each half immediately before its own unit
                of work.

        Returns:
            What the check found and established, for the turn to say.
        """
        await self._pass.run(goal_id, remaining=remaining)
        return await self._check.run(goal_id, remaining=remaining)
