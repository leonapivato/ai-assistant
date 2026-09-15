"""Phase 4: validating the plan in code before any step of it is dispatched.

ADR-0254 §14. `orchestration` evaluates, **deterministically and over stored
values alone**, four checks in one order:

1. **Dependency validity** — `depends_on` over the stored steps' status and
   `verifies` (ADR-0253 §1, §2).
2. **Arguments present or referenced** — every argument the declaration's schema
   requires is a literal on the step, filled by a `ResultReference` (ADR-0253 §6),
   **or classified `system_supplied` on that declaration and filled by
   `orchestration`** (ADR-0254 §3).
3. **Sufficiency to act** — every member of the step's `when`, by ADR-0252 §6's
   four tests, evaluated at the moment of dispatch.
4. **Coverage** — ADR-0254 §3's comparison.

*"Phase 4 adds no fifth check of its own, and a lane that adds one is changing
this decision."* Three of the four are other decisions' predicates evaluated here
rather than restated here, and this module is careful to evaluate only the one
that is nobody else's.

**Check 2 is what this module computes**, because it is the check §14 states over
values a plan already carries and because its third limb — the `system_supplied`
classification — is ADR-0254 §3's and therefore this lane's.

**Checks 1 and 3 are deferred here and decided at each step's own dispatch**,
which is ADR-0255's third case added to §14's enumeration: *"A check of a step at
least one of whose operands this same plan will produce before that step is
dispatched … is **deferred**, not failed … The attempt advances to `EXECUTE` where
every check either passed or was deferred."* Without it *"every plan carrying a
`depends_on` replans forever, because a dependent step's dependency and condition
are unsatisfied at phase 4 for every such plan by construction"*. **Evaluating
them is not this lane's in any case**: ADR-0253 §2 reserves its own rule in terms
— *"No lane of this decision dispatches a step, claims one, **evaluates this
rule** or writes a `SkipReason`. The stage that walks a plan in dependency order
is **A7's**"* — and ADR-0255 §1 gives that driver its four evaluations per step.

**The step being dispatched gets no deferral over a producer that has not run.** The
deferral ADR-0255 grants is conditional on the producer running *"before that step is
dispatched"*, so for the step a caller is dispatching **now** the condition is
falsified by the dispatch itself, and a producer the stored execution still calls
``PENDING`` refuses it (:class:`OutstandingDependency`). A ``SUCCEEDED`` producer is
untouched by this — its ``verifies`` half is A7's and the check stays deferred. That
is check 1 applied to one step at the one place the dispatch happens, not a walk of
the plan in dependency order, which stays A7's.

**Check 4 is taken at `ActionPolicy.decide`, on the concrete request, at every
dispatch** (ADR-0254 §13), and *"there is no cached coverage verdict anywhere"*.
Where it fails the user is asked through the ordinary `CONFIRM` park and the
attempt's move to `AttemptState.AWAITING_AUTHORIZATION` is **the one ADR-0249's
own lane already makes**. §14 adds *"no second writer of that state and no second
asking mechanism"*, so nothing here writes it and nothing here asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import StepStatus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import ActionPlan, PlanStep, ToolDefinition


@dataclass(frozen=True, slots=True)
class UnfillableStep:
    """A step no candidate for its capability could be given every required argument.

    Attributes:
        step: The step's id.
        capability: What it asked for, for the record a caller logs.
    """

    step: str
    capability: str


@dataclass(frozen=True, slots=True)
class UnmetDependency:
    """A step whose dependency on an already-disposed producer has **failed**.

    ADR-0253 §2: a dependency is satisfied only where the producing step is
    ``SUCCEEDED`` **and** its ``verifies`` predicate holds over its output; a
    producer that is ``FAILED`` or ``SKIPPED`` **fails** it, and one that is
    ``INDETERMINATE`` *"fails it and stops the branch"*.

    Attributes:
        step: The dependent step's id.
        producer: The step it depends on.
        status: How that producer was disposed of.
    """

    step: str
    producer: str
    status: StepStatus


@dataclass(frozen=True, slots=True)
class OutstandingDependency:
    """A dependency of the step **being dispatched** that is not yet satisfied.

    ADR-0255's deferral is conditional, and the condition names dispatch order in
    terms: a check is deferred only where an operand *"this same plan will produce
    **before that step is dispatched**"* is outstanding. For the step the caller is
    dispatching **now** there is no such later moment — the producer has not run, and
    the dependent is about to act anyway — so the deferral's own condition is
    falsified and the check is not deferred.

    **This is §14's check 1 applied to one step, not a walk of the plan.** Ordering a
    plan's steps and claiming each in turn is A7's driver (ADR-0253 §2, ADR-0255 §1),
    which this decision's lanes do not touch; refusing to dispatch *the step handed
    to this stage* over an undisposed producer of its own is a guard at the one place
    the dispatch happens, and it holds whether the caller is that driver or anything
    else.

    **A ``SUCCEEDED`` producer is not one of these.** It has run; what is left of
    ADR-0253 §2's conjunction is the ``verifies`` half, which is A7's to evaluate —
    so a dependent over it stays a *deferred* check, exactly as before. Refusing
    there would refuse every dependent step the driver will ever dispatch, which is
    a lock rather than a guard. What this names is a producer that has not acted at
    all (:func:`_unproduced`).

    Attributes:
        step: The dependent step's id — the one being dispatched.
        producer: The step it depends on, which the stored execution does not record
            as having run.
    """

    step: str
    producer: str


#: The dispositions that **fail** a dependency where phase 4 can already see them
#: (ADR-0253 §2).
#:
#: ``INDETERMINATE`` is among them for that section's own reason, and with a
#: different consequence further on: skipping the dependent step *"would record that
#: the producer did not act, which is exactly the half of the ambiguity that state
#: refuses to pick; driving it would record that the producer did"*. **At phase 4
#: both answers are the same** — the plan is not ready and nothing is dispatched —
#: and *which* disposal the branch then takes, and when, is A7's and A8's (§2, §11).
#: Nothing here writes a ``SkipReason``, which §2 forbids this lane in terms.
_FAILS_A_DEPENDENCY: Final = frozenset(
    {StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.INDETERMINATE}
)


#: The stored statuses at which a producer **has run**: ADR-0253 §2's three failing
#: dispositions and ``SUCCEEDED``.
#:
#: Stated as the set that *has* produced rather than the set that has not, so that a
#: status this tree does not yet carry — and a producer the stored execution does not
#: name at all — is treated as not having produced. That is the fail-closed direction
#: for the one thing this set decides: whether the step being dispatched may act over
#: it (:class:`OutstandingDependency`).
_HAS_PRODUCED: Final = _FAILS_A_DEPENDENCY | {StepStatus.SUCCEEDED}


@dataclass(frozen=True, slots=True)
class PhaseFour:
    """Where phase 4's checks leave the plan (ADR-0254 §14).

    **No enumeration is minted for this** — §14's *"where phase 4 leaves an
    attempt, over vocabularies that already exist"* — so this states the two facts
    a caller acts on and leaves ``AttemptPhase`` and ``AttemptState`` to say where
    the attempt then stands.

    Attributes:
        unfillable: The steps check 2 failed on. Non-empty is §14's *"A
            deterministic check failed on the plan"*: the attempt stays ``RUNNING``
            and the plan is replanned within the attempt, and where no replan can
            satisfy the check the attempt is left for A3's ``BLOCKED`` producer,
            which this decision does not write.
        unmet: The steps check 1 failed on — a dependency whose producer has
            already been disposed of in a way ADR-0253 §2 says fails it. **A failure
            here is available at phase 4 and is never deferred**, which is ADR-0255's
            *"a known failure dominating a deferral"*.
        outstanding: The dependencies of the step this caller named as the one it is
            **dispatching** whose producer has not run
            (:class:`OutstandingDependency`). Empty where no step was named, which
            is a plan-level evaluation asking nothing about dispatch order.
        deferred: The steps carrying a check whose operands this same plan will
            produce, deferred to their own dispatch (ADR-0255). A deferral neither
            blocks the advance to ``EXECUTE`` nor triggers a replan. The dispatched
            step is **not** among them for a producer that has not run — a check
            whose deferral condition is falsified is not a deferred check.
    """

    unfillable: tuple[UnfillableStep, ...] = ()
    unmet: tuple[UnmetDependency, ...] = ()
    outstanding: tuple[OutstandingDependency, ...] = ()
    deferred: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        """Whether every check passed or was deferred.

        ADR-0255: *"The attempt advances to `EXECUTE` where every check either
        **passed or was deferred**"*, a known failure dominating a deferral — *"so
        a check with an operand available now and failing now stays a failed check
        whatever else it waits on"*.

        ``outstanding`` counts against it for the same reason ``unmet`` does: a
        producer of the step about to be dispatched that has not run is a check that
        **is not** deferred, ADR-0255's deferral condition being about a producer
        that runs *before* that step is dispatched
        (:class:`OutstandingDependency`).
        """
        return not self.unfillable and not self.unmet and not self.outstanding


def required_arguments(candidate: ToolDefinition, /) -> tuple[str, ...]:
    """The keys ``candidate``'s schema requires, at depth one.

    **Only ``required`` is read, and the schema is not evaluated.** ADR-0254 §14:
    *"The schema check itself is ADR-0145 §1's, at construction, and is neither
    moved nor duplicated."* This asks whether a value will **be there**, not
    whether it is valid — two different questions, and ADR-0145 §2 forbids a
    second evaluator for the latter.

    A declaration whose schema names no ``required`` requires nothing, which is
    ADR-0145 §9's *"An absent schema declares no constraint"* — and the empty
    mapping a declaration carrying no schema holds is exactly that case.

    Args:
        candidate: The declaration a step's capability could resolve to.

    Returns:
        The required key names, in the schema's own order.
    """
    required = candidate.parameters_schema.get("required")
    if not isinstance(required, list | tuple):
        return ()
    return tuple(key for key in required if isinstance(key, str))


def fillable(step: PlanStep, candidate: ToolDefinition, /) -> bool:
    """Whether every argument ``candidate`` requires would be there for ``step``.

    ADR-0254 §14's check 2, in its three limbs: a **literal** on the step, an
    argument a **`ResultReference`** fills (ADR-0253 §6), or a key the declaration
    classifies **`system_supplied`** and `orchestration` fills (ADR-0254 §3).
    *"A key that is none of the three is still `UNMET_DEPENDENCY`'s neighbour and
    still refuses the step."*

    **The `system_supplied` limb is admitted here and filled nowhere yet.** What
    value `orchestration` supplies for such a key is the half of §3 no clause
    states (issue #2373, ruled into ADR-0266), so a declaration *requiring* a key
    it classifies system-supplied is admitted by this check and is then ineligible
    at ADR-0144 §7's fit test — which is the behaviour before ADR-0254 and is the
    fail-closed direction: the step does not dispatch. Admitting it here rather
    than refusing it is what keeps this check's answer true once the fill lands,
    and it is why this module states the limb rather than omitting it.

    Args:
        step: The planned step.
        candidate: The declaration its capability could resolve to.

    Returns:
        Whether every required argument has a source.
    """
    available = set(step.parameters)
    available.update(reference.parameter for reference in step.resolves)
    available.update(candidate.system_supplied)
    return all(key in available for key in required_arguments(candidate))


def _dependency_defects(
    step: PlanStep, disposed: Mapping[str, StepStatus], /
) -> tuple[tuple[UnmetDependency, ...], tuple[str, ...]]:
    """ADR-0254 §14's check 1 over one step, and whether it is deferred.

    ADR-0255 makes the deferral **conditional**, and the condition is the half a
    lane most easily drops: a check is deferred only where at least one operand
    *"this same plan will produce"* is outstanding **and** *"every one of whose
    operands already available at phase 4 is satisfied"*. So a producer already
    disposed of in a way ADR-0253 §2 says fails the dependency is a **failure**, not
    a deferral — *"a known failure dominating a deferral, so a check with an operand
    available now and failing now stays a failed check whatever else it waits on"*.

    **A `SUCCEEDED` producer defers rather than passing**, because ADR-0253 §2's
    rule is a conjunction — ``SUCCEEDED`` **and** the producer's ``verifies``
    predicate holding over its output — and the second conjunct's evaluator is A7's
    (§2: *"No lane of this decision … **evaluates this rule**"*, and ADR-0255 §1
    gives the driver its four evaluations per step). Deferring the half this stage
    cannot see is what keeps a deferral honest; asserting the dependency satisfied
    on the status alone would be the permissive half of a conjunction reported as
    the whole of it.

    Args:
        step: The step whose ``depends_on`` is read.
        disposed: The stored execution's step statuses, by step id. A step the
            execution does not name is outstanding.

    Returns:
        The failed dependencies, and the producers still outstanding, in the step's
        own ``depends_on`` order.
    """
    defects: list[UnmetDependency] = []
    outstanding: list[str] = []
    for producer in step.depends_on:
        status = disposed.get(producer)
        if status is None or status not in _FAILS_A_DEPENDENCY:
            # Either not yet disposed of, or `SUCCEEDED` with a `verifies` half
            # this stage does not evaluate: an operand this plan will produce.
            outstanding.append(producer)
            continue
        defects.append(UnmetDependency(step=step.id, producer=producer, status=status))
    return tuple(defects), tuple(outstanding)


def _unproduced(step: PlanStep, disposed: Mapping[str, StepStatus], /) -> tuple[str, ...]:
    """The producers of ``step`` the stored execution does not record as having run.

    Narrower than "outstanding" in :func:`_dependency_defects`, and deliberately so.
    A ``SUCCEEDED`` producer **has** run; what is left of ADR-0253 §2's conjunction
    there is the ``verifies`` half, whose evaluator is A7's driver — so a dependent
    over a succeeded producer is still a *deferred* check and not a refused one, and
    refusing it would lock the driver out of every dependent step it will ever
    dispatch. What this names is the producer that has not acted at all: ``PENDING``,
    ``AWAITING_APPROVAL``, ``RUNNING``, or a step the stored execution does not name.

    Args:
        step: The step being dispatched.
        disposed: The stored execution's step statuses, by step id.

    Returns:
        Those producers, in the step's own ``depends_on`` order.
    """
    return tuple(
        producer for producer in step.depends_on if disposed.get(producer) not in _HAS_PRODUCED
    )


def evaluate(
    plan: ActionPlan,
    /,
    *,
    candidates: Mapping[str, Sequence[ToolDefinition]],
    disposed: Mapping[str, StepStatus] | None = None,
    dispatching: str | None = None,
) -> PhaseFour:
    """Run phase 4's checks over ``plan`` and say where they leave it.

    **Check 2 is taken over every step of the plan and not only the one about to
    be dispatched**, which is the whole of what a plan-level gate buys: §14 puts
    it *"Before any step of a plan is dispatched"*, so a plan whose third step can
    never be completed does not get its first step's irreversible act performed
    first. The selection stage's own fit test (ADR-0144 §7) answers a different
    question one step at a time, and neither stands in for the other.

    **A step is unfillable only where *no* candidate for its capability could be
    given every argument it requires.** Which candidate a step will actually
    resolve to is the selection stage's (ADR-0144), taken at that step's own
    dispatch against the registry as it then stands, so refusing a plan because
    *one* candidate could not be completed would refuse plans the selection would
    have driven.

    **A step whose capability the registry offers no candidate for is not this
    check's business.** ADR-0211 §6 rules that *"Neither the planner nor any later
    stage rejects a plan envelope, or a step of one, on the ground that its
    capability is outside the stated vocabulary"*, and §14 repeats it: an emitted
    name is resolved *"through ADR-0053's alias layer at selection, and failing
    that through ADR-0037 §1's `NO_CAPABLE_TOOL`"*. So an empty candidate list is
    passed over here and disposed of there.

    **Check 1 fails where it can already see a failure and defers otherwise**
    (:func:`_dependency_defects`) — **except on the step named by ``dispatching``**,
    where ADR-0255's deferral condition is falsified by the dispatch itself and a
    producer that has not run refuses the step instead
    (:class:`OutstandingDependency`, :func:`_unproduced`).
    **Check 3 is deferred wherever a step declares a `when`**, because ADR-0252
    §6's four tests have no evaluator on this tree and
    are the sufficiency decision's own lane's; a deferral is ADR-0255's ruled
    treatment for a check this plan's own work will settle, and the driver decides
    it *"at the moment of dispatch, in the words the sufficiency decision fixes"*.

    Args:
        plan: The plan about to be driven.
        candidates: Each step's id mapped to the declarations its capability
            resolves to. The caller performs the registry reads, so this function
            stays a total function of stored values (§14).
        disposed: The stored execution's step statuses, by step id, for check 1.
            ``None`` is an execution none of whose steps has been disposed of,
            which is every plan at its first drive.
        dispatching: The id of the step the caller is about to dispatch, where it
            has one. Check 1 is **not deferred** for that step over a producer that
            has not run (:class:`OutstandingDependency`). ``None`` asks the
            plan-level question alone and defers check 1 everywhere, which is what a
            caller that is dispatching nothing means.

    Returns:
        Where the checks leave the plan.
    """
    statuses: Mapping[str, StepStatus] = {} if disposed is None else disposed
    unfillable: list[UnfillableStep] = []
    unmet: list[UnmetDependency] = []
    blocking: list[OutstandingDependency] = []
    deferred: list[str] = []
    for step in plan.steps:
        offered = candidates.get(step.id, ())
        if offered and not any(fillable(step, candidate) for candidate in offered):
            unfillable.append(UnfillableStep(step=step.id, capability=step.capability))
        defects, outstanding = _dependency_defects(step, statuses)
        unmet.extend(defects)
        unproduced = _unproduced(step, statuses) if step.id == dispatching else ()
        blocking.extend(
            OutstandingDependency(step=step.id, producer=producer) for producer in unproduced
        )
        if (outstanding and not unproduced) or step.when:
            deferred.append(step.id)
    return PhaseFour(
        unfillable=tuple(unfillable),
        unmet=tuple(unmet),
        outstanding=tuple(blocking),
        deferred=tuple(deferred),
    )


__all__ = [
    "OutstandingDependency",
    "PhaseFour",
    "UnfillableStep",
    "UnmetDependency",
    "evaluate",
    "fillable",
    "required_arguments",
]
