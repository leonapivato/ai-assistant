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

**Check 4 is taken at `ActionPolicy.decide`, on the concrete request, at every
dispatch** (ADR-0254 §13), and *"there is no cached coverage verdict anywhere"*.
Where it fails the user is asked through the ordinary `CONFIRM` park and the
attempt's move to `AttemptState.AWAITING_AUTHORIZATION` is **the one ADR-0249's
own lane already makes**. §14 adds *"no second writer of that state and no second
asking mechanism"*, so nothing here writes it and nothing here asks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
        deferred: The steps carrying a check whose operands this same plan will
            produce, deferred to their own dispatch (ADR-0255). A deferral neither
            blocks the advance to ``EXECUTE`` nor triggers a replan.
    """

    unfillable: tuple[UnfillableStep, ...] = ()
    deferred: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        """Whether every check passed or was deferred.

        ADR-0255: *"The attempt advances to `EXECUTE` where every check either
        **passed or was deferred**"*, a known failure dominating a deferral.
        """
        return not self.unfillable


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


def evaluate(
    plan: ActionPlan, /, *, candidates: Mapping[str, Sequence[ToolDefinition]]
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

    **Checks 1 and 3 are deferred wherever the step declares one**, and are
    decided at that step's own dispatch (module docstring).

    Args:
        plan: The plan about to be driven.
        candidates: Each step's id mapped to the declarations its capability
            resolves to. The caller performs the registry reads, so this function
            stays a total function of stored values (§14).

    Returns:
        Where the checks leave the plan.
    """
    unfillable: list[UnfillableStep] = []
    deferred: list[str] = []
    for step in plan.steps:
        offered = candidates.get(step.id, ())
        if offered and not any(fillable(step, candidate) for candidate in offered):
            unfillable.append(UnfillableStep(step=step.id, capability=step.capability))
        if step.depends_on or step.when:
            deferred.append(step.id)
    return PhaseFour(unfillable=tuple(unfillable), deferred=tuple(deferred))


__all__ = [
    "PhaseFour",
    "UnfillableStep",
    "evaluate",
    "fillable",
    "required_arguments",
]
