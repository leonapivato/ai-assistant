"""The ``VERIFY`` comparison: what the goal's own records establish (ADR-0262 §§2-4, §6).

ADR-0262 §11's **L4**, the comparison half. This module is A10's *"§3's rung, §2's
three results, and §4's six limbs"*, computed **wholly before the composing stage**
(§1) so that no reply exists for an implementation to take as an operand. The commits
the comparison decides — the ``→ ENDED`` transition and §5's ``ACHIEVED`` write — are
taken **after** that stage, by the engine, from the values fixed here and from no value
the reply produced.

**Nothing here calls anything on the world** (§3). The comparison makes *"no model
call, no tool call, no ``StepRunner`` or ``StepExecutor`` entry and no
``ToolInvoker.invoke``"*: it reads the plan store's executions, the audit trail's
rulings and the :class:`~ai_assistant.core.types.Authorization` those rulings name,
through :class:`~ai_assistant.core.protocols.AuthorizationResolution` — the one new
collaborator this decision adds, ``resolve(id)`` and nothing else. The two read seams
are narrowed here to :class:`_Executions` and :class:`_Decisions`, module-private
Protocols that can name neither ``record`` nor ``commit_transition``: *"an independent
read that a criterion needs is a step of a later attempt"*, and a phase that could
write is one that could take it.

**No model authors any operand** (§2). A criterion is established by three facts the
record already carries — the **user's** own confirmed coverage member, the
**authorisation** that proved the concrete call against it, and the **tool author's**
own declared postconditions — and by nothing a planner returned. ``PlanStep.verifies``
is read here by nothing, ``IntendedAction.serves`` is read by nothing, and no criterion
is established from a ``GoalElement.text``, a ``GoalInterpretation.outcome``, an
``IntendedAction.intent``, a ``StepFailure.message``, a composed reply or any other
free text.

**The predicate is the tree's one statement of ADR-0253 §4 and is not restated here.**
:func:`~ai_assistant.orchestration.effects.verification_holds` is that statement — its
own module records that *"this module is the one statement of each, so the driver reads
it rather than restating it"* — and it already carries §4's refusal of every numeric and
boolean coercion, walked into containers. A second spelling here would be *"one carrier
for two facts"* read in the other direction: two implementations of one rule, free to
disagree about whether an integer ``1`` satisfies a declaration naming ``1.0``.
**``VerificationKind.OUTPUT_PRESENT`` is unreachable through it from here**, L1's
validator refusing that kind as a declared postcondition (§2's R48 clause).

**Store failures are never converted into verdicts** (§2). An
:class:`~ai_assistant.core.errors.AuthorizationError`, an
:class:`~ai_assistant.core.errors.AuditError` or any other failure of the two reads
propagates with its cause; what fails *closed* is a record that could be read and said
nothing — a decision the trail does not hold, a row the resolution answers ``None``
for, a definition declaring no postcondition.

**A ``MONEY`` criterion is compared against the charge the act reported, and exactly one
function says how** (ADR-0271 §§2-4). ADR-0262 §2 ruled every such criterion
``unestablished`` *"whatever else holds"*, on the ground that *"the charge is not an
operand this decision has"*; ADR-0271 lands that operand — the quote the dispatch was
proved against, pinned to the ruling by value (§1) — and **reverses that blanket**, so
such a criterion now takes §2's own three results over §2's own calls.
:func:`classify_bound_step` is where that lands: §2's classification of a **bound step**
restated as ADR-0271 §3's **three ordered limbs**, with the charge read and tested by
:mod:`ai_assistant.orchestration.charges`. **No other function in this module reads**
:class:`~ai_assistant.core.types.BoundKind`.

**The finding is a report and never a prevention** (ADR-0271 §3). A charge that
disagrees with its pin makes its step *contradicting*, and what the user is told is the
criterion's own result by the route ADR-0262 already fixes — §4's limbs to an
``AttemptOutcome`` and §6's two-field ``AttemptReport``. **No ``Authorization`` is
written, settled or revoked, no decision is recorded, no dispatch is refused, nothing is
retried, reversed or refunded, and no statement names a figure**: the act has already
run by the time this comparison is taken, and what binds spending stays ADR-0266 §7's
proof **before** it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from ai_assistant.core.types import (
    AttemptOutcome,
    AttemptReport,
    AuthorizationOrigin,
    BoundKind,
    GoalStatus,
    PermissionOutcome,
    Reversibility,
    SkipReason,
    StepStatus,
)
from ai_assistant.orchestration.charges import ChargeTest, charge_test
from ai_assistant.orchestration.effects import verification_holds

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.protocols import AuthorizationResolution
    from ai_assistant.core.types import (
        ActionQuote,
        Authorization,
        CoverageMember,
        ExecutionState,
        FrozenJson,
        Goal,
        GoalAttempt,
        GoalElement,
        PermissionDecision,
        StepExecution,
        ToolDefinition,
    )

__all__ = [
    "Comparison",
    "CriterionResult",
    "Rung",
    "classify_bound_step",
    "compare",
    "continues_on",
]


class CriterionResult(StrEnum):
    """What the record establishes about one criterion, at the instant of comparison.

    ADR-0262 §2's three results, which are *"total by construction"*: **"no fourth
    result exists, no result is a degree, and no lane reads *unestablished* as either
    of the other two"**.
    """

    MET = "met"
    """No call is contradicting, no call is ambiguous, and some call is satisfying."""

    UNMET = "unmet"
    """Some call is contradicting — a successful act's own answer refused it."""

    UNESTABLISHED = "unestablished"
    """Otherwise. Never reported as met, and never read as either of the other two."""


class Rung(StrEnum):
    """The strength a goal's verification owes, off what the attempt actually did (§3).

    Read off ``ToolDefinition``'s **required** declarations and the pinned decision's
    ``egress_binding``, over every step that reached a committed ``→ RUNNING`` claim or
    stands ``SUCCEEDED`` carrying ADR-0259 §2's satisfaction identifiers. ``risk_level``
    is **not** read: risk is the scale a policy thresholds to decide whether to *ask*,
    and the question here is what an act *did*.
    """

    NOTHING = "nothing"
    """Rung 0 — nothing was claimed at all."""

    ACTED = "acted"
    """Rung 1 — an act ran that is not rung 2's."""

    CONSEQUENTIAL = "consequential"
    """Rung 2 — a consequential act ran, and an unestablished criterion is uncertainty."""


@dataclass(frozen=True, slots=True)
class Comparison:
    """What one turn's ``VERIFY`` phase computed, before anything was composed.

    Attributes:
        outcome: The member §4's six limbs yielded. Never ``CANCELLED``, which that
            function reaches by no limb (§4).
        rung: §3's rung, kept so that the engine's own logging and this module's arms
            can assert the ladder apart from the limbs it feeds.
        results: §2's result per criterion, in the order the current
            :class:`~ai_assistant.core.types.GoalInterpretation` carries them. Empty
            for a goal carrying no criterion, which §4's ``fully_met`` requires at
            least one of.
        report: The two values §6 hands the composing stage and rides
            ``TurnOutcome.attempt_report``, **where the attempt ends** — which is the
            engine's own test and not this value's.
        versions: **The snapshot of the set this comparison read** (§4) — one pair per
            execution the attempt names, in ``execution_ids``' own order, each at the
            ``ExecutionState.version`` this comparison's own read returned. It rides the
            ending transition and is compared there, which is what closes the window the
            status set only narrows: a ``FAILED → RUNNING → SUCCEEDED`` retry landing
            between the comparison and the commit leaves every step terminal at both
            instants, and *"the version pairs close it"*.

            **It is the comparison's read and never a later one.** §4 fixes the field as
            *"the ``ExecutionState.version`` the caller read **when it computed the
            comparison**"*, so a figure re-read at the commit would report the ground as
            unmoved over exactly the interval the field exists to cover — the composing
            stage, which is an arbitrarily slow model call. **An execution the store did
            not answer for contributes no pair**, which leaves the snapshot short, and §4
            makes a short snapshot a malformed command the store refuses outright rather
            than a write that silently protects less than it claims.
    """

    outcome: AttemptOutcome
    rung: Rung
    results: tuple[CriterionResult, ...]
    report: AttemptReport
    versions: tuple[tuple[str, int], ...]


class _Executions(Protocol):
    """The one plan-store read this comparison takes, narrowed at its own seam.

    ``PlanStore`` satisfies it structurally. What the annotation buys is that this
    phase can name neither ``commit_transition`` nor ``claim_effect`` nor
    ``set_goal_status``: §3 rules that verification *"performs no call on the world"*
    and *"writes at most the two commits §4 and §5 name"* — both of which are the
    engine's, after composing.
    """

    async def get_execution(self, execution_id: str) -> ExecutionState | None: ...


class _Decisions(Protocol):
    """The one audit-trail read this comparison takes, narrowed at its own seam.

    ``AuditTrail`` satisfies it structurally, and the narrowing is what keeps
    ``record`` unnameable here — the same argument ADR-0254 §16 makes for
    ``AuthorizationResolution``, one seam over.
    """

    async def get(self, decision_id: str) -> PermissionDecision | None: ...


@dataclass(frozen=True, slots=True)
class _Act:
    """One step of the attempt, with §2's and §3's provenance already followed.

    A step satisfied from an effect the goal already completed (ADR-0259 §2) carries
    **the holder's** definition and the holder's own route and ``authorised_by``, which
    is §2's *"the operative definition … are the holder's"* and §3's *"its rung … comes
    from the step those identifiers name"*. Its ``output`` is the borrowed one the
    store copied onto it.

    Attributes:
        status: The step's own stored status.
        output: The step's own stored output — borrowed, where it was satisfied.
        acted: Whether it is in §3's set at all: a committed ``→ RUNNING`` claim of its
            own, or ``SUCCEEDED`` carrying both satisfaction identifiers.
        decision: The **operative** ruling, or ``None`` where it could not be read.
        skip_reason: Why it was skipped, where it was — §4's ``blocked`` reads it.
        readable: Whether that ruling could be read. ``False`` where a claimed step's
            ``approval_ref`` names a decision the trail does not hold or names none at
            all, and where a satisfied step's holder cannot be read — §3's rung 2 in
            both cases, *"the harmless rung"* being the error that clause closes.
    """

    status: StepStatus
    skip_reason: SkipReason | None
    output: FrozenJson
    acted: bool
    decision: PermissionDecision | None
    readable: bool


@dataclass(frozen=True, slots=True)
class _BoundStep:
    """A bound step of one criterion, reduced to the three facts §2 compares.

    Attributes:
        status: Whether the tool returned. Only a ``SUCCEEDED`` step is ever decisive.
        output: What it returned — the operand, and the only one.
        definition: The **pinned** declaration, embedded by value in the ruling the
            step's ``approval_ref`` names, and never a definition the registry holds
            now (§2).
        digest: The ``ActionRequest.parameters_digest`` the policy computed over the
            concrete request, which is what groups two steps into **one call**.
        pinned: The quote ``ActionPolicy.decide`` proved this dispatch against
            (:attr:`~ai_assistant.core.types.PermissionRuling.proved_quote`, ADR-0271
            §1), carried by value on the ruling and read here and nowhere else.
            ``None`` where the decision carries none — *"a decision recorded without
            one is a decision whose dispatch was not proved against a quote"*, and
            **nothing back-fills, refreshes, re-selects or repairs it**. It is an
            operand and never the verdict of a comparison: ADR-0254 §13's *"no cached
            coverage verdict anywhere"* is untouched, and reading it establishes no
            authority.
    """

    status: StepStatus
    output: FrozenJson
    definition: ToolDefinition
    digest: str
    pinned: ActionQuote | None


class _Verdict(StrEnum):
    """§2's classification of one bound step, and the one ADR-0271 P3 restates."""

    SATISFYING = "satisfying"
    CONTRADICTING = "contradicting"
    NEITHER = "neither"


def classify_bound_step(bound: _BoundStep, *, member: CoverageMember) -> _Verdict:
    """Classify one bound step: ADR-0262 §2, as ADR-0271 §3 restates it.

    **ADR-0262 §2's own two tests, word for word** (:func:`_declared_verdict`). A bound
    step is **satisfying** where it stands ``SUCCEEDED``, its operative definition
    declares **at least one** postcondition, and **every** declaration of that
    definition holds over its stored ``output``; **contradicting** where it stands
    ``SUCCEEDED`` and **some** declaration does **not** hold — *"and in no other case"*;
    and neither otherwise. **A ``FAILED`` bound step is never decisive**: a failure
    returns no answer to hold a declaration against (ADR-0029 §3), and *"no failure
    proves non-occurrence"*.

    **For a criterion whose confirmed member is a ``MONEY`` one, that classification is
    ADR-0271 §3's three ordered limbs** — total and disjoint by construction, taken in
    this order and stopping at the first that holds. A step is **(1) contradicting**
    where §2's own contradicting test holds **or** where the charge test **fails**;
    **(2) satisfying** where §2's own satisfying test holds **and** the charge test
    **holds**; **(3) neither**, in every remaining case — which is where the charge test
    was **not taken** over a step §2 would otherwise have called satisfying, and every
    case §2 already called neither. **A ``FAILED`` step reaches limb 3 in every case**,
    the charge test being taken over a ``SUCCEEDED`` step alone.

    **The order is the whole of the answer to a step that would qualify twice**, and it
    is ordered this way because *"a step whose own tool's declaration refuses its output
    is contradicting on the record's own evidence, which the absence of a readable
    charge neither supplies nor erases"*. An implementation taking the *charge test not
    taken* case first would answer ``neither`` where §3 answers ``contradicting``, and
    its criterion ``unestablished`` where §3 reaches ``unmet``.

    **The charge test is taken over no step of any other criterion** (§3), so a
    ``PERIOD`` or a ``TERMS`` criterion is classified by §2's two tests alone and this
    function reads no charge for one. That is not the limbs disapplied: limb 2 requires
    the charge test to *hold*, and a test that is never taken over such a step would
    make every one of them ``neither``.

    **No other clause of §2 moves** (§3): its grouping of bound steps into **calls** by
    ``ActionRequest.parameters_digest``, its satisfying/contradicting/**ambiguous** rule
    over a call, its three results, its *"no fourth result exists"* and its *"a
    ``FAILED`` bound step is never decisive"* all bind entire, and these limbs are
    stated inside them. A failed charge test *"makes a step contradicting and overrides
    neither §2's grouping nor its ambiguity rule"* — a mismatch inside an ambiguous call
    is reported as that call's ambiguity, *"the record declining to say what happened
    rather than a finding suppressed"* — and it is never promoted straight to a
    criterion-level ``unmet``.

    Args:
        bound: The bound step, with its pinned declaration, its stored output and the
            quote its dispatch was proved against.
        member: The **confirmed member**, whose ``kind`` §2 makes the criterion's kind
            and whose bound §3's third conjunct reads.

    Returns:
        Which of §2's three the step is.
    """
    declared = _declared_verdict(bound)
    if member.kind is not BoundKind.MONEY:
        return declared
    charge = charge_test(
        status=bound.status,
        definition=bound.definition,
        output=bound.output,
        pinned=bound.pinned,
        member=member,
    )
    if declared is _Verdict.CONTRADICTING or charge is ChargeTest.FAILS:
        return _Verdict.CONTRADICTING
    if declared is _Verdict.SATISFYING and charge is ChargeTest.HOLDS:
        return _Verdict.SATISFYING
    return _Verdict.NEITHER


def _declared_verdict(bound: _BoundStep) -> _Verdict:
    """ADR-0262 §2's classification of a bound step against its own declarations.

    The half of :func:`classify_bound_step` that reads the **tool author's** declared
    postconditions against the **provider's** returned output, and nothing else. It is
    stated apart from the limbs so that ADR-0271 §3's *"§2's own contradicting test"*
    and *"§2's own satisfying test"* name one thing each rather than a condition spelled
    twice at two positions of an ordered chain.

    Args:
        bound: The bound step, with its pinned declaration and its stored output.

    Returns:
        Which of §2's three the step is, before any charge is read.
    """
    if bound.status is not StepStatus.SUCCEEDED:
        return _Verdict.NEITHER
    declared = bound.definition.postconditions
    if not declared:
        # The empty tuple is the fail-closed claim (ADR-0016 §1 as ADR-0262 partially
        # supersedes it): a tool declaring none establishes nothing here.
        return _Verdict.NEITHER
    if all(verification_holds(one, bound.output) for one in declared):
        return _Verdict.SATISFYING
    return _Verdict.CONTRADICTING


def continues_on(outcome: AttemptOutcome, status: GoalStatus) -> bool:
    """§6's ``continues``, computed from two facts and never by a model.

    ``True`` **exactly** where the outcome is ``PARTIAL``, ``FAILED`` or ``UNCERTAIN``
    **and** the goal is **open** — ADR-0250 §1's ``ACTIVE`` or ``BLOCKED``. ``False``
    on ``VERIFIED``, on ``ANSWERED`` and on ``CONDITION_PREVENTED``, unconditionally
    and with no second fact consulted. **No lane derives it from a model's opinion,
    makes it configurable, or sets it on a closed goal.**

    Args:
        outcome: The member §4's limbs yielded.
        status: The goal's status **as the comparison read it** (§6) — the two commits
            have not happened when this is computed.

    Returns:
        Whether the goal's work is unfinished and the user may take it further.
    """
    unfinished = {AttemptOutcome.PARTIAL, AttemptOutcome.FAILED, AttemptOutcome.UNCERTAIN}
    open_goal = {GoalStatus.ACTIVE, GoalStatus.BLOCKED}
    return outcome in unfinished and status in open_goal


async def compare(
    goal: Goal,
    attempt: GoalAttempt,
    *,
    executions: _Executions,
    decisions: _Decisions,
    rows: AuthorizationResolution | None,
) -> Comparison:
    """Run ADR-0262's comparison over one attempt, before anything is composed.

    §3's rung, §2's three results and §4's six limbs, in that dependency order and over
    nothing else. **At the instant this runs no reply exists**, which is §1's whole
    mechanism for making the circularity unreachable rather than merely forbidden: no
    lane passes a ``ComposedReply`` or any part of one in here, and no lane re-runs this
    after composing.

    **The criteria are the ``criteria`` tuple of the goal's *current*
    ``GoalInterpretation``, read at this instant, and nothing else is one** (§1) — not
    an earlier revision's, not the plan's expectations, not a step's ``verifies``, not
    a ``constraints`` or ``conditions`` element. **A goal carrying no criterion is not
    thereby verified**: the empty tuple is the ordinary shape at revision 1 and §4's
    ``fully_met`` requires at least one, so such an attempt reaches ``ANSWERED`` at rung
    0 or 1 and ``UNCERTAIN`` at rung 2 and never ``VERIFIED``.

    Args:
        goal: The goal, as the store holds it **before** the comparison runs — its
            current interpretation, its status and the ``version`` §5's write is taken
            under.
        attempt: The attempt this turn would end.
        executions: The plan store, narrowed to the one read this takes.
        decisions: The audit trail, narrowed to the one read this takes.
        rows: :class:`~ai_assistant.core.protocols.AuthorizationResolution`, the one
            new collaborator §3 adds. ``None`` where a deployment wired none, which
            resolves no row and leaves every criterion ``unestablished`` — the
            fail-closed direction, and never an error.

    Returns:
        The comparison, with the two values §6 hands the composing stage.

    Raises:
        PlanningError: As ``get_execution`` raises it. **A store failure is never
            converted into a verdict** (§2).
        AuditError: As the trail's own read raises it, on the same rule.
        AuthorizationError: As ``resolve`` raises it, on the same rule.
    """
    criteria = goal.interpretation[-1].criteria
    acts, versions = await _acts(attempt, executions=executions, decisions=decisions)
    rung = _rung(acts)
    authorising = await _authorising_rows(acts, goal_id=goal.id, rows=rows)
    results = tuple(
        _result(criterion, acts=acts, authorising=authorising) for criterion in criteria
    )
    outcome = _outcome(results, rung=rung, acts=acts)
    return Comparison(
        outcome=outcome,
        rung=rung,
        results=results,
        report=AttemptReport(outcome=outcome, continues=continues_on(outcome, goal.status)),
        versions=versions,
    )


async def _acts(
    attempt: GoalAttempt, *, executions: _Executions, decisions: _Decisions
) -> tuple[tuple[_Act, ...], tuple[tuple[str, int], ...]]:
    """Every step of every execution the attempt names, with its provenance followed.

    One walk serves §2 and §3, because both ask the same question about a step's
    provenance and a second walk would be free to answer it differently. **The set
    reaches no further than the attempt**: ``GoalAttempt.execution_ids`` and the
    holders those steps themselves name, and no enumeration of the goal's rows, plans
    or executions.

    Each execution is read **once** and memoised for the walk, because a holder
    ADR-0259 §2 names commonly sits in an execution the attempt already names, and a
    second read of one row inside one comparison could answer differently.

    An execution the store has lost contributes nothing rather than failing the turn —
    the same fail-closed branch the engine's own settled-step read takes, and
    unreachable against a store that kept its write-time closure.

    Args:
        attempt: The attempt being compared.
        executions: The plan store, narrowed.
        decisions: The audit trail, narrowed.

    Returns:
        One :class:`_Act` per step, in execution order, and §4's version snapshot over
        the same reads — so the pairs the ending transition carries are **this
        comparison's** own figures rather than a second read's.

    Raises:
        PlanningError: As ``get_execution`` raises it.
        AuditError: As the trail's read raises it.
    """
    held: dict[str, ExecutionState | None] = {}

    async def read(execution_id: str) -> ExecutionState | None:
        if execution_id not in held:
            held[execution_id] = await executions.get_execution(execution_id)
        return held[execution_id]

    acts: list[_Act] = []
    versions: list[tuple[str, int]] = []
    for execution_id in attempt.execution_ids:
        state = await read(execution_id)
        if state is None:  # pragma: no cover — the store's own write-time closure
            # Unreachable against a store that kept its write-time closure. There is
            # **no version to report** and none is invented: the pair is omitted, which
            # leaves the snapshot short, and §4 makes a short snapshot a malformed
            # command the store refuses outright.
            continue
        versions.append((execution_id, state.version))
        for step in state.steps:
            acts.append(await _act(step, read=read, decisions=decisions))
    return tuple(acts), tuple(versions)


async def _act(
    step: StepExecution,
    *,
    read: Callable[[str], Awaitable[ExecutionState | None]],
    decisions: _Decisions,
) -> _Act:
    """Reduce one stored step to the facts §2 and §3 read off it.

    **A step satisfied from an earlier completed effect follows its holder** (ADR-0259
    §2, §9): ADR-0262 §3 gives it *"the rung of the step those identifiers name"* and
    §2 gives it that step's *"operative definition, and the decision whose route and
    ``authorised_by`` are read above"*. **Where that holder cannot be read the step is
    at rung 2** — *"reading it at rung 0 is the error this clause closes"*, its
    borrowed output being an operand under §2.

    **A claimed step whose own pinned decision cannot be read is at rung 2 likewise**,
    which is the same fail-closed answer: neither its definition nor its
    ``egress_binding`` can be read, so nothing says the act was not irreversible or
    disclosing. Under §2 such a step establishes nothing, which is a statement about
    *evidence* where this is one about *strength* — both fail closed, in the directions
    their own sections run.

    Args:
        step: The stored step.
        read: The walk's own memoised execution read.
        decisions: The audit trail, narrowed.

    Returns:
        The step, reduced.

    Raises:
        PlanningError: As the execution read raises it.
        AuditError: As the trail's read raises it.
    """
    borrowed = step.satisfied_by_execution is not None and step.satisfied_by_step is not None
    satisfied = borrowed and step.status is StepStatus.SUCCEEDED
    if not (step.attempts > 0 or satisfied):
        # "A step a plan declared and no walk claimed contributes nothing, because
        # nothing happened" (§3) — and it names no decision either, so it is no
        # authorising row's step under §2.
        return _Act(
            status=step.status,
            skip_reason=step.skip_reason,
            output=step.output,
            acted=False,
            decision=None,
            readable=True,
        )
    holder = step if not satisfied else await _holder(step, read=read)
    if holder is None:
        # §3: "where that step cannot be read the attempt is at rung 2".
        return _Act(
            status=step.status,
            skip_reason=step.skip_reason,
            output=step.output,
            acted=True,
            decision=None,
            readable=False,
        )
    decision = None if holder.approval_ref is None else await decisions.get(holder.approval_ref)
    return _Act(
        status=step.status,
        skip_reason=step.skip_reason,
        output=step.output,
        acted=True,
        decision=decision,
        readable=decision is not None,
    )


async def _holder(
    step: StepExecution, *, read: Callable[[str], Awaitable[ExecutionState | None]]
) -> StepExecution | None:
    """The step ADR-0259 §2's satisfaction identifiers name, or ``None``.

    Args:
        step: The satisfied step, carrying both identifiers.
        read: The walk's own memoised execution read.

    Returns:
        The holder, or ``None`` where it cannot be read.

    Raises:
        PlanningError: As the execution read raises it.
    """
    if step.satisfied_by_execution is None:  # pragma: no cover — the caller checked both
        return None
    found = await read(step.satisfied_by_execution)
    if found is None:
        return None
    for one in found.steps:
        if one.step_id == step.satisfied_by_step:
            return one
    return None


def _rung(acts: Sequence[_Act]) -> Rung:
    """§3's three rungs, off ``ToolDefinition``'s required declarations.

    **Rung 2** where some contributing step's pinned definition is ``side_effecting``
    and at least one of: its ``reversibility`` is **more severe than** ``REVERSIBLE``;
    its ``discloses`` is non-empty; or its decision carries an ``egress_binding``. An
    unreadable pinned decision is rung 2 too, on the clause above. **Rung 1** where
    some contributing step exists and none reaches rung 2. **Rung 0** where none does.

    **``reversibility`` is compared on ADR-0016 §2's severity ordering and never
    lexicographically** — that class overrides all four comparison operators for
    exactly this reason, under which a plain string comparison makes
    ``"irreversible" > "reversible"`` evaluate to ``False``. **``discloses`` is read
    beside it and neither stands alone**, a ``REVERSIBLE`` tool with a non-empty
    ``discloses`` having performed an irrevocable disclosure while making a revocable
    change. **``risk_level`` is not read.**

    Args:
        acts: Every step of the attempt, reduced.

    Returns:
        The rung.
    """
    acted = [act for act in acts if act.acted]
    if not acted:
        return Rung.NOTHING
    for act in acted:
        if not act.readable or act.decision is None:
            return Rung.CONSEQUENTIAL
        definition = act.decision.tool
        if not definition.side_effecting:
            continue
        if (
            definition.reversibility > Reversibility.REVERSIBLE
            or bool(definition.discloses)
            or act.decision.egress_binding is not None
        ):
            return Rung.CONSEQUENTIAL
    return Rung.ACTED


def _route_d(decision: PermissionDecision | None) -> str | None:
    """The row a step's own pinned ruling points at, where it is a route-(d) ``ALLOW``.

    ADR-0254 §7's discriminator, read verbatim: *"``resolves`` unset, ``authorised_by``
    set, ``authorised_subject`` set, ``authorised_goal`` **set**"*. **A step whose
    decision is a route-(a), (b) or (c) ``ALLOW``, or carries no ``authorised_by`` at
    all, contributes no row** — the cost §2a states.

    Args:
        decision: The step's operative ruling, or ``None``.

    Returns:
        The ``authorised_by`` identifier, or ``None``.
    """
    if decision is None or decision.resolves is not None:
        return None
    ruling = decision.ruling
    if ruling.outcome is not PermissionOutcome.ALLOW:
        return None
    if ruling.authorised_by is None or ruling.authorised_subject is None:
        return None
    if ruling.authorised_goal is None:
        return None
    return ruling.authorised_by


async def _authorising_rows(
    acts: Sequence[_Act], *, goal_id: str, rows: AuthorizationResolution | None
) -> Mapping[str, Authorization]:
    """§2's authorising rows — **exactly the rows the attempt's own steps name**.

    Every distinct route-(d) ``authorised_by`` whose ``authorised_goal`` is this goal,
    resolved through ``AuthorizationResolution.resolve``, keeping the rows that come
    back with ``origin`` ``CONFIRMED`` — ADR-0254 §1's path (i), *"put to the user as a
    question and answered"*, the only route on which the user saw the rendered values
    and assented.

    **The disposition is not re-tested here, and that is deliberate**: ``record``
    already refused the row unless the store's row was ``ESTABLISHED`` and live at
    ``decided_at``, so the pinned decision **is** the proof of the row's standing at
    the moment the act ran, and a row **revoked or superseded afterwards** must not
    retract a verification of something that already happened.

    **The set is enumerable from the attempt alone and reaches no further**: a row no
    step of this attempt acted under is not an authorising row, is not looked for, and
    establishes and refuses nothing. **No lane enumerates the goal's rows, calls
    ``standing``, ``recent`` or ``live_for``, or reads a row by any route but a pinned
    decision's own pointer.**

    Args:
        acts: Every step of the attempt, reduced.
        goal_id: The goal being verified.
        rows: The resolution seam, or ``None`` where a deployment wired none.

    Returns:
        The authorising rows, keyed by id.

    Raises:
        AuthorizationError: As ``resolve`` raises it — never converted into a verdict.
    """
    if rows is None:
        return {}
    wanted: list[str] = []
    for act in acts:
        found = _route_d(act.decision)
        if (
            found is not None
            and act.decision is not None
            and act.decision.ruling.authorised_goal == goal_id
            and found not in wanted
        ):
            wanted.append(found)
    authorising: dict[str, Authorization] = {}
    for authorization_id in wanted:
        row = await rows.resolve(authorization_id)
        if row is None:
            continue
        if row.origin is not AuthorizationOrigin.CONFIRMED:
            continue
        if row.goal != goal_id:
            continue
        authorising[authorization_id] = row
    return authorising


def _confirmed_member(
    criterion: GoalElement, authorising: Mapping[str, Authorization]
) -> tuple[str, CoverageMember] | None:
    """The criterion's confirmed member — **unique among those rows, or there is none**.

    A criterion's **matching members** are every ``CoverageMember`` of every authorising
    row whose ``basis.span`` equals the criterion's own ``span`` **byte for byte**, no
    fold applied. **The criterion has a confirmed member exactly where it has *one*
    matching member.**

    **Where it has no matching member, and equally where it has more than one, it is
    ``unestablished``**, and the second half is the load-bearing one: *"a precedence
    rule between them would be this decision inventing which of the user's own
    statements governs"*, which is R50's *"an ambiguous acceptance is never reported as
    a verified outcome"* read at the operand. **No lane orders the rows, unions them,
    prefers the earliest, the narrowest or the one whose step succeeded, or evaluates
    the criterion once per matching member.**

    A criterion carrying **no ``span`` at all** — every ground but ``USER_STATED`` — has
    no matching member by construction. **No lane matches a span by prefix,
    containment, normalisation, similarity or a model call.**

    Args:
        criterion: One element of the current interpretation's ``criteria``.
        authorising: The attempt's authorising rows.

    Returns:
        The row's id and its member, or ``None``.
    """
    if criterion.span is None:
        return None
    matching = [
        (authorization_id, member)
        for authorization_id, row in authorising.items()
        for member in row.coverage
        if member.basis.span == criterion.span
    ]
    if len(matching) != 1:
        return None
    return matching[0]


def _result(
    criterion: GoalElement, *, acts: Sequence[_Act], authorising: Mapping[str, Authorization]
) -> CriterionResult:
    """§2's three results over one criterion, and never a fourth.

    The criterion's **bound steps** are every step that contributed its confirmed
    member's row — those whose route-(d) ``authorised_by`` is that row's id — **and no
    other step of any execution**. They are grouped by **the call each made**: two
    bound steps are of one call where their pinned decisions carry the same
    ``ActionRequest.parameters_digest``, *"the policy's rather than the planner's"*,
    and of different calls otherwise.

    A call is **satisfying** where it has a decisive step and every one of its decisive
    steps is satisfying, **contradicting** where it has one and every one is
    contradicting, and **ambiguous** where it has both — *"no order breaks the tie, and
    the last step does not govern"*. Then: **unmet** where some call is contradicting;
    **met** where no call is contradicting, no call is ambiguous and some call is
    satisfying; **unestablished** otherwise.

    **``PlanStep.intended_action`` would answer the grouping question and is refused**:
    a planner writes it, and a verdict turning on it is the allow ADR-0249 §7 forbids.

    Args:
        criterion: One element of the current interpretation's ``criteria``.
        acts: Every step of the attempt, reduced.
        authorising: The attempt's authorising rows.

    Returns:
        Which of §2's three it is.
    """
    confirmed = _confirmed_member(criterion, authorising)
    if confirmed is None:
        return CriterionResult.UNESTABLISHED
    authorization_id, member = confirmed
    calls: dict[str, list[_Verdict]] = defaultdict(list)
    for act in acts:
        if _route_d(act.decision) != authorization_id or act.decision is None:
            continue
        bound = _BoundStep(
            status=act.status,
            output=act.output,
            definition=act.decision.tool,
            digest=act.decision.parameters_digest,
            pinned=act.decision.ruling.proved_quote,
        )
        calls[bound.digest].append(classify_bound_step(bound, member=member))
    contradicting = False
    ambiguous = False
    satisfying = False
    for verdicts in calls.values():
        decisive = [one for one in verdicts if one is not _Verdict.NEITHER]
        if not decisive:
            continue
        if all(one is _Verdict.SATISFYING for one in decisive):
            satisfying = True
        elif all(one is _Verdict.CONTRADICTING for one in decisive):
            contradicting = True
        else:
            ambiguous = True
    if contradicting:
        return CriterionResult.UNMET
    if ambiguous or not satisfying:
        return CriterionResult.UNESTABLISHED
    return CriterionResult.MET


def _outcome(
    results: Sequence[CriterionResult], *, rung: Rung, acts: Sequence[_Act]
) -> AttemptOutcome:
    """§4's six limbs, in order and over nothing else.

    **The three derived facts**, over every step of every execution the attempt names:
    ``failed`` where any stands ``FAILED``; ``blocked`` where any stands ``SKIPPED``
    carrying ``UNMET_DEPENDENCY`` or ``APPROVAL_DENIED``; ``fully_met`` where the goal
    carries **at least one** criterion and every one is met. **None is stored, none is
    a field and no consumer reads any.**

    **A step standing ``INDETERMINATE`` reaches no limb at all**: the third ending
    condition refuses to end an attempt naming one, so ``VERIFIED`` — and with it
    ``ACHIEVED`` — is unreachable beside a possible effect by the attempt not ending,
    rather than by a conjunct on limbs 4 and 5. **Nothing here derives a possible
    effect from a side-effecting ``FAILED`` step**, which would collapse ADR-0032 §2's
    ratified ``FAILED``/``INDETERMINATE`` distinction.

    **Five of the order's positions are load-bearing.** ``FAILED`` and
    ``CONDITION_PREVENTED`` precede everything, because such an attempt may also have
    every criterion unestablished and would otherwise fall to ``ANSWERED``, whose
    ratified definition asserts *"that no step failed and that no condition blocked"*;
    ``FAILED`` is first, so an established failure is not suppressed by a condition;
    **both are refused at rung 2 unless a criterion is actually ``unmet``**, because a
    consequential act ran and *"an unrelated ``FAILED`` or ``SKIPPED`` step does not
    convert a rung-2 attempt whose criteria are merely unestablished into a claim about
    them"*; ``UNCERTAIN`` precedes ``PARTIAL`` so that a rung-2 attempt with a met and
    an unestablished criterion is uncertain rather than partly not done; and
    ``VERIFIED`` sits below ``PARTIAL`` so that no combination of met criteria outvotes
    an unmet one, which is R53 read at the member level.

    **``CANCELLED`` is reached by no limb.** A cancelled attempt is terminal and
    ADR-0261 §2's act, and *"no transition leaves a terminal member"*.

    Args:
        results: §2's result per criterion.
        rung: §3's rung.
        acts: Every step of the attempt, reduced.

    Returns:
        The member the attempt earns.
    """
    blocking = {SkipReason.UNMET_DEPENDENCY, SkipReason.APPROVAL_DENIED}
    failed = any(act.status is StepStatus.FAILED for act in acts)
    blocked = any(act.status is StepStatus.SKIPPED and act.skip_reason in blocking for act in acts)
    any_met = any(one is CriterionResult.MET for one in results)
    any_unmet = any(one is CriterionResult.UNMET for one in results)
    fully_met = bool(results) and all(one is CriterionResult.MET for one in results)
    consequential = rung is Rung.CONSEQUENTIAL
    if not any_met and (any_unmet or (failed and not consequential)):
        return AttemptOutcome.FAILED
    if not any_met and not any_unmet and blocked and not failed and not consequential:
        return AttemptOutcome.CONDITION_PREVENTED
    if consequential and not any_unmet and not fully_met:
        return AttemptOutcome.UNCERTAIN
    if any_met and not fully_met:
        return AttemptOutcome.PARTIAL
    if fully_met:
        return AttemptOutcome.VERIFIED
    return AttemptOutcome.ANSWERED
