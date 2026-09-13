"""Phase 4's checks over a plan, before any step of it is dispatched (ADR-0254 §14).

The evaluation is a total function of stored values, so it is exercised directly
here; ``test_runner.py`` pins that a plan it refuses commits nothing.

**Only check 2 is evaluated.** Checks 1 and 3 are deferred to each step's own
dispatch, which is ADR-0255's third case, and ADR-0253 §2 reserves evaluating the
dependency rule to A7's driver in terms. Check 4 is taken at
``ActionPolicy.decide`` (ADR-0254 §13). The module's own docstring carries the
division.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from authorizing_builders import AT, GOAL, a_tool

from ai_assistant.core.types import (
    ActionPlan,
    EvidenceBasis,
    PlanStep,
    ResultReference,
    StepCondition,
    StepOutputRef,
    StepStatus,
)
from ai_assistant.orchestration.validating import (
    PhaseFour,
    UnfillableStep,
    UnmetDependency,
    evaluate,
    fillable,
    required_arguments,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from ai_assistant.core.types import ToolDefinition

#: A schema requiring two keys, one of which a declaration may classify
#: system-supplied.
REQUIRING = {
    "type": "object",
    "properties": {"to": {"type": "string"}, "idempotency_key": {"type": "string"}},
    "required": ["to", "idempotency_key"],
}


def a_step(
    step_id: str = "step-1",
    *,
    parameters: Mapping[str, str] | None = None,
    resolves: tuple[ResultReference, ...] = (),
    depends_on: tuple[str, ...] = (),
    when: tuple[StepCondition, ...] = (),
) -> PlanStep:
    """One planned step."""
    return PlanStep(
        id=step_id,
        intent="send the note",
        capability="send_email",
        parameters={} if parameters is None else parameters,
        resolves=resolves,
        depends_on=depends_on,
        when=when,
    )


def a_condition(about: str = "element-1") -> StepCondition:
    """One ``when`` member, so a step can declare a sufficiency requirement."""
    return StepCondition(about=about, basis=EvidenceBasis.READ_OUTCOME)


def a_plan(*steps: PlanStep) -> ActionPlan:
    """A plan carrying ``steps``."""
    return ActionPlan(id="p-1", goal_id=GOAL, steps=steps, created_at=AT, targets_revision=1)


def _offered(plan: ActionPlan, *candidates: ToolDefinition) -> dict[str, Sequence[ToolDefinition]]:
    """Offer the same candidates for every step of ``plan``."""
    return {step.id: candidates for step in plan.steps}


# --- what the schema requires (ADR-0254 §14's check 2) -------------------


def test_a_declaration_naming_no_required_keys_requires_nothing() -> None:
    """ADR-0145 §9: "An absent schema declares no constraint"."""
    assert required_arguments(a_tool()) == ()


def test_the_required_keys_are_read_and_the_schema_is_not_evaluated() -> None:
    """ADR-0254 §14: the schema check "is neither moved nor duplicated"."""
    assert required_arguments(a_tool(parameters_schema=REQUIRING)) == (
        "to",
        "idempotency_key",
    )


# --- the three limbs a required argument may be filled by ----------------


def test_a_literal_on_the_step_fills_a_required_argument() -> None:
    """The first limb, and the one every plan before ADR-0253 used."""
    candidate = a_tool(parameters_schema=REQUIRING)
    step = a_step(parameters={"to": "a@example.com", "idempotency_key": "k-1"})

    assert fillable(step, candidate)


def test_a_result_reference_fills_a_required_argument() -> None:
    """ADR-0253 §6's second limb: an argument a producing step's output fills."""
    candidate = a_tool(parameters_schema=REQUIRING)
    step = a_step(
        "step-2",
        parameters={"idempotency_key": "k-1"},
        resolves=(ResultReference(parameter="to", source=StepOutputRef(step="step-1")),),
        depends_on=("step-1",),
    )

    assert fillable(step, candidate)


def test_a_system_supplied_classification_fills_a_required_argument() -> None:
    """ADR-0254 §3's third limb, which is why §14's check 2 reads the way it does.

    A declaration whose schema **requires** a key it classifies system-supplied
    would otherwise be ineligible for every step, "because the clause above forbids
    the model naming that key at all".
    """
    candidate = a_tool(parameters_schema=REQUIRING, system_supplied=("idempotency_key",))
    step = a_step(parameters={"to": "a@example.com"})

    assert fillable(step, candidate)


def test_a_key_that_is_none_of_the_three_refuses_the_step() -> None:
    """ADR-0254 §3: "A key that is none of the three … still refuses the step"."""
    candidate = a_tool(parameters_schema=REQUIRING)
    step = a_step(parameters={"to": "a@example.com"})

    assert not fillable(step, candidate)


# --- the evaluation over a whole plan ------------------------------------


def test_a_plan_every_step_of_which_can_be_completed_is_ready() -> None:
    """ADR-0254 §14's first case: every check passed."""
    plan = a_plan(a_step(), a_step("step-2"))

    gate = evaluate(plan, candidates=_offered(plan, a_tool()))

    assert gate == PhaseFour()
    assert gate.ready


def test_a_later_step_that_can_never_be_completed_refuses_the_plan() -> None:
    """The whole of what a plan-level gate buys (ADR-0254 §14).

    §14 puts the evaluation "Before any step of a plan is dispatched", so a plan
    whose **second** step can never be given an argument it requires does not get
    its **first** step's irreversible act performed first. The selection stage's
    own fit test asks about one step at a time and would not have caught this.
    """
    first = a_step(parameters={"to": "a@example.com", "idempotency_key": "k-1"})
    second = a_step("step-2", parameters={"to": "a@example.com"})
    plan = a_plan(first, second)

    gate = evaluate(plan, candidates=_offered(plan, a_tool(parameters_schema=REQUIRING)))

    assert not gate.ready
    assert gate.unfillable == (UnfillableStep(step="step-2", capability="send_email"),)


def test_a_step_is_unfillable_only_where_no_candidate_could_take_it() -> None:
    """Which candidate a step resolves to is the selection stage's (ADR-0144).

    Refusing a plan because *one* candidate could not be completed would refuse
    plans the selection would have driven.
    """
    strict = a_tool("strict", parameters_schema=REQUIRING)
    lax = a_tool("lax")
    plan = a_plan(a_step(parameters={"to": "a@example.com"}))

    assert evaluate(plan, candidates=_offered(plan, strict, lax)).ready
    assert not evaluate(plan, candidates=_offered(plan, strict)).ready


def test_a_capability_the_registry_offers_nothing_for_is_passed_over() -> None:
    """ADR-0211 §6: no stage rejects a step on its capability's vocabulary.

    It is disposed of at its own dispatch through ADR-0037 §1's
    ``NO_CAPABLE_TOOL``, which is where §14 says an emitted name is resolved.
    """
    plan = a_plan(a_step())

    assert evaluate(plan, candidates={}).ready


# --- ADR-0255's deferral -------------------------------------------------


def test_a_dependency_on_an_undisposed_producer_is_deferred_and_does_not_fail() -> None:
    """ADR-0255's third case added to §14's enumeration.

    "Without it every plan carrying a `depends_on` replans forever, because a
    dependent step's dependency and condition are unsatisfied at phase 4 for every
    such plan by construction."
    """
    plan = a_plan(a_step(), a_step("step-2", depends_on=("step-1",)))

    gate = evaluate(plan, candidates=_offered(plan, a_tool()))

    assert gate.deferred == ("step-2",)
    assert gate.unmet == ()
    assert gate.ready


def test_a_step_declaring_a_when_is_deferred() -> None:
    """ADR-0252 §6's four tests have no evaluator here; the driver decides them.

    ADR-0255 puts that decision "at the moment of dispatch, in the words the
    sufficiency decision fixes".
    """
    conditional = a_step("step-2", when=(a_condition(),))
    plan = a_plan(a_step(), conditional)

    gate = evaluate(plan, candidates=_offered(plan, a_tool()))

    assert gate.deferred == ("step-2",)
    assert gate.ready


@pytest.mark.parametrize(
    "status",
    [StepStatus.FAILED, StepStatus.SKIPPED, StepStatus.INDETERMINATE],
    ids=["failed", "skipped", "indeterminate"],
)
def test_a_dependency_on_a_disposed_producer_fails_and_is_never_deferred(
    status: StepStatus,
) -> None:
    """ADR-0253 §2's rule, and ADR-0255's "a known failure dominating a deferral".

    A producer that is `FAILED` or `SKIPPED` fails the dependency, and one that is
    `INDETERMINATE` "fails it and stops the branch". Each is an operand **already
    available at phase 4 and not satisfied**, so the check is a failure whatever
    else that step waits on — a lane that deferred unconditionally lets the
    dependent step dispatch over a producer the store says did not deliver.
    """
    plan = a_plan(a_step(), a_step("step-2", depends_on=("step-1",)))

    gate = evaluate(plan, candidates=_offered(plan, a_tool()), disposed={"step-1": status})

    assert gate.unmet == (UnmetDependency(step="step-2", producer="step-1", status=status),)
    assert not gate.ready


def test_a_succeeded_producer_defers_rather_than_passing() -> None:
    """ADR-0253 §2's rule is a conjunction and this stage sees one conjunct.

    A dependency is satisfied only where the producer is `SUCCEEDED` **and** its
    `verifies` predicate holds over its output. That second conjunct's evaluator is
    A7's, so asserting the dependency satisfied on the status alone would report the
    permissive half of a conjunction as the whole of it.
    """
    plan = a_plan(a_step(), a_step("step-2", depends_on=("step-1",)))

    gate = evaluate(
        plan,
        candidates=_offered(plan, a_tool()),
        disposed={"step-1": StepStatus.SUCCEEDED},
    )

    assert gate.deferred == ("step-2",)
    assert gate.unmet == ()
    assert gate.ready


def test_a_failed_dependency_dominates_a_second_outstanding_one() -> None:
    """ADR-0255: "a check with an operand available now and failing now stays a
    failed check whatever else it waits on"."""
    plan = a_plan(
        a_step(),
        a_step("step-2"),
        a_step("step-3", depends_on=("step-1", "step-2")),
    )

    gate = evaluate(
        plan, candidates=_offered(plan, a_tool()), disposed={"step-1": StepStatus.FAILED}
    )

    assert gate.deferred == ("step-3",)  # step-2 is still outstanding
    assert [one.producer for one in gate.unmet] == ["step-1"]
    assert not gate.ready


def test_a_known_check_2_failure_dominates_a_deferral() -> None:
    """The same dominance one check over: a deferred step does not rescue a plan."""
    plan = a_plan(
        a_step(parameters={"to": "a@example.com", "idempotency_key": "k-1"}),
        a_step("step-2", depends_on=("step-1",)),
    )

    gate = evaluate(plan, candidates=_offered(plan, a_tool(parameters_schema=REQUIRING)))

    assert gate.deferred == ("step-2",)
    assert not gate.ready
