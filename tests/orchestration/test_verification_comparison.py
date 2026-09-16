"""ADR-0262 §12's arms 3, 4, 5 and 6 over the comparison itself (L4).

`§2`'s three results, `§3`'s ladder and `§4`'s six limbs, driven against the records
§2 says establish a criterion and against **no model output at all**. Every arm here
calls :func:`~ai_assistant.orchestration.verification.compare` directly, over
controlled fakes (ADR-0255 §13): the goal, the attempt, the executions, the rulings and
the rows are built by hand, so an arm varies exactly the fact its clause is about.

**What is asserted is the comparison and never a commit.** §1 puts the commits after
the composing stage and this function takes neither, so nothing here writes a
``GoalStatus``, ends an attempt, or reads a reply — the arms that pin *those* are
``test_engine_verify_phase.py``'s.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from authorizing_builders import a_binding
from verification_builders import (
    DIGEST,
    EXECUTION,
    OTHER_DIGEST,
    RIVERSIDE,
    SUNDAY,
    UNDER_150,
    Decisions,
    Executions,
    Rows,
    a_criterion,
    a_decision,
    a_goal,
    a_member,
    a_row,
    a_ruling,
    a_step,
    a_tool,
    an_attempt,
    an_execution,
    an_unbound_ruling,
    field_equals,
    field_present,
    paired,
)

from ai_assistant.core.errors import AuditError, AuthorizationError, PlanningError
from ai_assistant.core.types import (
    AttemptOutcome,
    AuthorizationDisposition,
    AuthorizationOrigin,
    BoundKind,
    DataTier,
    GoalStatus,
    Idempotency,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    SkipReason,
    StepStatus,
)
from ai_assistant.orchestration.verification import (
    CriterionResult,
    Rung,
    compare,
    continues_on,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import (
        FrozenJson,
        Goal,
        GoalElement,
        PermissionDecision,
        StepExecution,
    )
    from ai_assistant.orchestration.verification import Comparison

# The declaration the booking steps are pinned to in most arms: two postconditions,
# which is the shape §12's arm 3 is stated over.
_BOOKED = (field_equals("status", "confirmed"), field_present("reservation_id"))
_HOLDS = {"status": "confirmed", "reservation_id": "r-9"}
_REFUSES = {"status": "rejected", "reservation_id": "r-9"}
_HALF = {"status": "confirmed"}


async def _compared(
    goal: Goal,
    *steps: StepExecution,
    decisions: tuple[PermissionDecision, ...] = (),
    rows: Rows | None = None,
    executions: Executions | None = None,
    execution_ids: tuple[str, ...] = (EXECUTION,),
) -> Comparison:
    """Run the comparison over one attempt naming ``execution_ids``.

    **The rows and the rulings are reconciled before the comparison sees them**
    (:func:`~verification_builders.paired`), so every pair an arm compares over is one
    ``AuditTrail.record`` could have admitted under ADR-0254 §7 — the row's ``tool``
    equal to the decision's by value, and the ruling's ``authorised_subject`` the row's
    own recomputed digest. §2 reads neither field, so this changes no arm's verdict; what
    it removes is a fixture that could only have existed as impossible state.
    """
    standing = rows if rows is not None else Rows(a_row("auth-1", a_member(RIVERSIDE)))
    held, ruled = paired(standing.held, decisions)
    standing.reconcile(held)
    return await compare(
        goal,
        an_attempt(*execution_ids),
        executions=executions if executions is not None else Executions(an_execution(*steps)),
        decisions=Decisions(*ruled),
        rows=standing,
    )


def _one(comparison: Comparison) -> CriterionResult:
    """The single criterion's result."""
    (only,) = comparison.results
    return only


# --------------------------------------------------------------------------- #
# Arm 3 — the three results, R50, and the per-criterion comparison             #
# --------------------------------------------------------------------------- #


async def test_a_successful_step_satisfying_both_declarations_reads_met() -> None:
    """§2's **met**: no call contradicting, none ambiguous, and some call satisfying."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert _one(comparison) is CriterionResult.MET


async def test_a_successful_step_refusing_one_declaration_reads_unmet() -> None:
    """§2's **unmet**: *"**some** declaration … does not hold"* makes the call contradicting.

    It satisfies ``reservation_id`` and refuses ``status``, which is arm 3's own
    *"it satisfies one and refuses the other"* — and it is the arm that keeps
    *established not to hold* reachable at all.
    """
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_REFUSES),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert _one(comparison) is CriterionResult.UNMET


async def test_a_tool_declaring_nothing_establishes_nothing() -> None:
    """§2: the empty tuple is *"the **fail-closed** claim"* — a step under it is not decisive."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=())),),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_no_bound_step_succeeded_reads_unestablished() -> None:
    """§2's last limb: *"no bound step is satisfying or contradicting"*."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", status=StepStatus.RUNNING, output=None),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_a_failed_side_effecting_step_is_unestablished_under_every_idempotency() -> None:
    """§2: *"a ``FAILED`` bound step is never decisive"*, whatever the tool's idempotency.

    ADR-0029 §4 commits a timed-out ``NATURAL`` call ``FAILED`` on the ground that
    *"whether it acted does not change what a repeat does"* — **not** that it did not
    act — so no failure proves non-occurrence and none of the three answers differently.
    **The arm that fails against an implementation reading a failure as proof the
    outcome does not hold.**
    """
    for idempotency in (Idempotency.NATURAL, Idempotency.KEYED, Idempotency.NONE):
        declaration = a_tool(
            postconditions=_BOOKED,
            idempotency=idempotency,
            idempotency_window=(timedelta(hours=1) if idempotency is Idempotency.KEYED else None),
        )
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            a_step("s-1", status=StepStatus.FAILED, output=None),
            decisions=(a_decision("d-1", definition=declaration),),
        )

        assert _one(comparison) is CriterionResult.UNESTABLISHED, idempotency
        assert _one(comparison) is not CriterionResult.UNMET, idempotency


async def test_a_failed_read_is_unestablished_and_never_unmet() -> None:
    """§2: for a **read**, *"the failure is about the observation and not about the world"*.

    A status check that could not reach its provider establishes neither that the
    reservation holds nor that it does not.
    """
    declaration = a_tool(postconditions=_BOOKED, side_effecting=False)
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", status=StepStatus.FAILED, output=None),
        decisions=(a_decision("d-1", definition=declaration),),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_each_criterion_is_compared_against_its_own_member() -> None:
    """Arm 3's per-criterion half, in **both** directions.

    A goal carrying a ``PERIOD`` criterion and a ``TERMS`` criterion whose spans are the
    two the confirmed row's two members rest on, over one booking step → **both met**;
    the same goal where the row carries the ``PERIOD`` member alone → **met and
    unestablished** respectively. **The arm that fails against any rule giving one
    verdict to every criterion of a goal.**
    """
    goal = a_goal(a_criterion(SUNDAY), a_criterion(RIVERSIDE))
    both = a_row(
        "auth-1",
        a_member(SUNDAY, kind=BoundKind.PERIOD),
        a_member(RIVERSIDE, kind=BoundKind.TERMS),
    )
    decisions = (a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),)

    paired = await _compared(
        goal, a_step("s-1", output=_HOLDS), decisions=decisions, rows=Rows(both)
    )
    assert paired.results == (CriterionResult.MET, CriterionResult.MET)

    one_member = a_row("auth-1", a_member(SUNDAY, kind=BoundKind.PERIOD))
    partial = await _compared(
        goal, a_step("s-1", output=_HOLDS), decisions=decisions, rows=Rows(one_member)
    )
    assert partial.results == (CriterionResult.MET, CriterionResult.UNESTABLISHED)


async def test_one_call_whose_steps_disagree_is_ambiguous_in_either_order() -> None:
    """§2: *"no order breaks the tie, and the last step does not govern"*.

    Two bound steps of **one call** — the same ``parameters_digest`` — one satisfying
    and one contradicting, both ``SUCCEEDED`` → the group is ambiguous and the criterion
    ``unestablished``; and **the same pair in the other order** answers the same.
    """
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED)),
    )
    forward = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", output=_REFUSES, approval_ref="d-2"),
        decisions=decisions,
    )
    backward = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_REFUSES, approval_ref="d-1"),
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=decisions,
    )

    assert _one(forward) is CriterionResult.UNESTABLISHED
    assert _one(backward) is CriterionResult.UNESTABLISHED


async def test_one_call_whose_steps_agree_takes_their_verdict() -> None:
    """§2: a call is satisfying where **every** decisive step is, and contradicting likewise."""
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED)),
    )
    agreeing = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=decisions,
    )
    refusing = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_REFUSES, approval_ref="d-1"),
        a_step("s-2", output=_REFUSES, approval_ref="d-2"),
        decisions=decisions,
    )

    assert _one(agreeing) is CriterionResult.MET
    assert _one(refusing) is CriterionResult.UNMET


async def test_a_failed_step_beside_a_satisfying_step_of_one_call_leaves_it_met() -> None:
    """§2: *"a failure inside a group settles nothing either way"*.

    **The arm that fails against a rule reading a failure as an answer** — what the
    failure leaves open is whether that dispatch *also* took effect, which is A8's
    idempotency question and not a claim about whether the outcome holds.
    """
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED)),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", status=StepStatus.FAILED, output=None, approval_ref="d-1"),
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=decisions,
    )

    assert _one(comparison) is CriterionResult.MET


async def test_a_later_call_does_not_clear_an_earlier_contradiction() -> None:
    """§2: *"a second, different act … is a different call, so its success clears nothing"*.

    Two bound steps of **different** calls — the two rooms — the first contradicting and
    the later satisfying → **unmet**, and neither ``VERIFIED`` nor ``ACHIEVED``.
    """
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED), digest=DIGEST),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED), digest=OTHER_DIGEST),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_REFUSES, approval_ref="d-1"),
        a_step("s-2", output=_HOLDS, approval_ref="d-2"),
        decisions=decisions,
    )

    assert _one(comparison) is CriterionResult.UNMET
    assert comparison.outcome is not AttemptOutcome.VERIFIED


async def test_a_contradicting_call_beside_an_ambiguous_one_reads_unmet() -> None:
    """§2's order: **unmet** is tested before **unestablished**.

    *"Some call is contradicting"* is the first limb, so an ambiguous group beside a
    contradicting one does not soften the verdict. **The arm that pins the order of the
    three results.**
    """
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED), digest=DIGEST),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED), digest=DIGEST),
        a_decision("d-3", definition=a_tool(postconditions=_BOOKED), digest=OTHER_DIGEST),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", output=_REFUSES, approval_ref="d-2"),
        a_step("s-3", output=_REFUSES, approval_ref="d-3"),
        decisions=decisions,
    )

    assert _one(comparison) is CriterionResult.UNMET


async def test_a_money_criterion_is_unestablished_whatever_else_holds() -> None:
    """§2's ``MONEY`` rule, pre-ADR-0271: *"no criterion about an amount is ever met here"*.

    A confirmed ``MONEY`` member over a booking step **every declaration holds over** →
    ``unestablished``, the attempt ``UNCERTAIN`` at rung 2 and the goal not
    ``ACHIEVED``. ADR-0271 §3 lands the operand and P3 restates exactly this
    classification; until then the fail-closed direction is what the record can honestly
    say about a booking that charges.
    """
    consequential = a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE)
    comparison = await _compared(
        a_goal(a_criterion(UNDER_150)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=consequential),),
        rows=Rows(a_row("auth-1", a_member(UNDER_150, kind=BoundKind.MONEY))),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED
    assert comparison.rung is Rung.CONSEQUENTIAL
    assert comparison.outcome is AttemptOutcome.UNCERTAIN


async def test_prose_is_never_an_operand() -> None:
    """§2: no criterion is established from a ``GoalElement.text`` or any other free text.

    The criterion's own **text** spells out word for word what a satisfied booking would
    say, and the step's own output carries that same prose — at a key nothing declared.
    The tool declares nothing, so there is no operand this decision can read, and the
    criterion is **unestablished**. *"A ``SUCCEEDED`` step records that the tool
    returned, and **what it returned** is the operand"* — and a declaration is what says
    which part of it to read.

    **The pair is what makes the arm mean something**: the identical records with the
    declaration present and an output that holds over it read **met**, so what moved the
    verdict is the tool author's declaration against the provider's answer and never the
    prose that was there all along.
    """
    saying_it = a_criterion(RIVERSIDE, text='status is "confirmed" and reservation_id is "r-9"')
    echoing = {"note": 'status is "confirmed" and reservation_id is "r-9"'}

    prose_only = await _compared(
        a_goal(saying_it),
        a_step("s-1", output=echoing),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=())),),
    )
    assert _one(prose_only) is CriterionResult.UNESTABLISHED

    answered = await _compared(
        a_goal(saying_it),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )
    assert _one(answered) is CriterionResult.MET


async def test_a_declared_literal_is_compared_byte_exactly() -> None:
    """ADR-0253 §4: ``FIELD_EQUALS`` compares **byte-exactly**, folding nothing.

    *"No lane folds case, coerces a number to a string, compares a float by tolerance,
    or treats ``1`` as ``true``."* Python's own ``==`` performs two of those unaided —
    ``1 == 1.0`` and ``True == 1`` are both true — so the **equal-valued** float is the
    boundary that matters and it is walked here beside the unequal one.

    **The comparison is the tree's one statement of §4** and this module restates none
    of it: :func:`~ai_assistant.orchestration.effects.verification_holds` is that
    statement, and these arms assert that §2's comparison reads it rather than a second
    spelling free to disagree with it. Adversarial review, round 1, ``blocker``.
    """
    declaration = a_tool(postconditions=(field_equals("nights", 2),))
    for output in ({"nights": "2"}, {"nights": 2.0}, {"nights": 2.5}, {"nights": True}):
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            a_step("s-1", output=output),
            decisions=(a_decision("d-1", definition=declaration),),
        )
        assert _one(comparison) is CriterionResult.UNMET, output

    exact = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output={"nights": 2}),
        decisions=(a_decision("d-1", definition=declaration),),
    )
    assert _one(exact) is CriterionResult.MET


async def test_the_byte_exact_comparison_is_walked_into_containers() -> None:
    """ADR-0253 §4, one level down: ``equals`` is a ``FrozenJsonValue``, and so is an object.

    ``{"count": true}`` equals ``{"count": 1}`` under a top-level ``==`` and ``[1]``
    equals ``[1.0]`` — the same coercions §4 names, reached through a container. Each
    reads **unmet**, and the identical shape reads **met**.
    """
    nested = a_tool(postconditions=(field_equals("room", {"beds": 1, "tags": [2]}),))
    coerced: tuple[Mapping[str, FrozenJson], ...] = (
        {"room": {"beds": True, "tags": [2]}},
        {"room": {"beds": 1, "tags": [2.0]}},
        {"room": {"beds": 1}},
    )
    for output in coerced:
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            a_step("s-1", output=output),
            decisions=(a_decision("d-1", definition=nested),),
        )
        assert _one(comparison) is CriterionResult.UNMET, output

    exact = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output={"room": {"beds": 1, "tags": [2]}}),
        decisions=(a_decision("d-1", definition=nested),),
    )
    assert _one(exact) is CriterionResult.MET


async def test_a_field_present_predicate_refuses_a_null_and_a_non_object() -> None:
    """ADR-0253 §4: *"an ``output`` that is not an object, an absent key, and a key whose
    value is ``null`` each fail it"*."""
    declaration = a_tool(postconditions=(field_present("reservation_id"),))
    for output in ({"reservation_id": None}, {"other": "x"}):
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            a_step("s-1", output=output),
            decisions=(a_decision("d-1", definition=declaration),),
        )
        assert _one(comparison) is CriterionResult.UNMET, output


# --------------------------------------------------------------------------- #
# Arm 4 — the campsite case, and each conjunct removed in turn                 #
# --------------------------------------------------------------------------- #


def _campsite() -> tuple[GoalElement, GoalElement, GoalElement]:
    """The three criteria of §12's arm 4: *Riverside*, *Sunday* and *up to 150 euros*."""
    return a_criterion(RIVERSIDE), a_criterion(SUNDAY), a_criterion(UNDER_150)


def _campsite_row() -> Rows:
    """The confirmed row carrying the three members those spans rest on."""
    return Rows(
        a_row(
            "auth-1",
            a_member(RIVERSIDE, kind=BoundKind.TERMS),
            a_member(SUNDAY, kind=BoundKind.PERIOD),
            a_member(UNDER_150, kind=BoundKind.MONEY),
        )
    )


def _booking() -> PermissionDecision:
    """The route-(d) ruling a consequential booking step ran under."""
    return a_decision(
        "d-1",
        definition=a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE),
    )


async def test_the_campsite_case_is_uncertain_and_the_goal_is_not_achieved() -> None:
    """Arm 4: the first two criteria **met**, the third **unestablished** because it is ``MONEY``.

    So not ``fully_met``, the attempt ``UNCERTAIN`` at rung 2 and the goal **not**
    ``ACHIEVED`` — *"which is the whole of what this decision can honestly say about a
    booking that charges"*.
    """
    riverside, sunday, money = _campsite()
    comparison = await _compared(
        a_goal(riverside, sunday, money),
        a_step("s-1", output=_HOLDS),
        decisions=(_booking(),),
        rows=_campsite_row(),
    )

    assert comparison.results == (
        CriterionResult.MET,
        CriterionResult.MET,
        CriterionResult.UNESTABLISHED,
    )
    assert comparison.outcome is AttemptOutcome.UNCERTAIN
    assert comparison.report.continues is True


async def test_the_same_goal_without_the_money_criterion_is_verified() -> None:
    """Arm 4's pair: *"the same goal without the third criterion → ``VERIFIED``"*.

    The half that shows the mechanism works, beside the half that shows exactly what §7
    says it does not cover.
    """
    riverside, sunday, _ = _campsite()
    comparison = await _compared(
        a_goal(riverside, sunday),
        a_step("s-1", output=_HOLDS),
        decisions=(_booking(),),
        rows=_campsite_row(),
    )

    assert comparison.results == (CriterionResult.MET, CriterionResult.MET)
    assert comparison.outcome is AttemptOutcome.VERIFIED
    assert comparison.report.continues is False


async def test_each_conjunct_removed_in_turn_leaves_the_criterion_unestablished() -> None:
    """Arm 4: the five removals, each on its own and each fail-closed.

    The row's ``origin`` ``OPENING_ACT``; the row belonging to **another goal**; the
    step's decision a route-(a), (b) or (c) ``ALLOW``; the same carrying no
    ``authorised_by``; and the member's ``basis.span`` differing from the criterion's by
    one character.
    """
    criterion = a_criterion(RIVERSIDE)
    holding = a_step("s-1", output=_HOLDS)
    declaring = a_tool(postconditions=_BOOKED)

    opening = await _compared(
        a_goal(criterion),
        holding,
        decisions=(a_decision("d-1", definition=declaring),),
        rows=Rows(a_row("auth-1", a_member(RIVERSIDE), origin=AuthorizationOrigin.OPENING_ACT)),
    )
    assert _one(opening) is CriterionResult.UNESTABLISHED, "origin OPENING_ACT"

    elsewhere = await _compared(
        a_goal(criterion),
        holding,
        decisions=(a_decision("d-1", definition=declaring),),
        rows=Rows(a_row("auth-1", a_member(RIVERSIDE), goal="g-other")),
    )
    assert _one(elsewhere) is CriterionResult.UNESTABLISHED, "another goal's row"

    plain = await _compared(
        a_goal(criterion),
        holding,
        decisions=(
            a_decision(
                "d-1",
                definition=declaring,
                ruling=a_ruling(authorised_by=None, goal=None),
            ),
        ),
    )
    assert _one(plain) is CriterionResult.UNESTABLISHED, "a route-(a) ALLOW"

    unbound = await _compared(
        a_goal(criterion),
        holding,
        decisions=(
            a_decision(
                "d-1",
                definition=declaring,
                ruling=PermissionRuling(
                    outcome=PermissionOutcome.ALLOW,
                    reason="a standing grant of this destination covers this call",
                ),
            ),
        ),
    )
    assert _one(unbound) is CriterionResult.UNESTABLISHED, "no authorised_by at all"

    off_by_one = await _compared(
        a_goal(a_criterion("Riversid")),
        holding,
        decisions=(a_decision("d-1", definition=declaring),),
    )
    assert _one(off_by_one) is CriterionResult.UNESTABLISHED, "a span differing by one character"


async def test_a_criterion_carrying_no_span_has_no_matching_member() -> None:
    """§2: *"a criterion carrying no ``span`` at all … has no matching member by construction"*."""
    comparison = await _compared(
        a_goal(a_criterion(None)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_a_row_revoked_after_the_dispatch_still_establishes() -> None:
    """§2: *"a row revoked or superseded afterwards must not retract a verification"*.

    *"No lane reads a present disposition as evidence about a past dispatch, in either
    direction"* — the pinned decision **is** the proof of the row's standing at the
    moment the act ran. **The arm that fails against an implementation re-testing the
    disposition at ``VERIFY``.**
    """
    for retired in (AuthorizationDisposition.REVOKED, AuthorizationDisposition.SUPERSEDED):
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            a_step("s-1", output=_HOLDS),
            decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
            rows=Rows(a_row("auth-1", a_member(RIVERSIDE), disposition=retired)),
        )
        assert _one(comparison) is CriterionResult.MET, retired


async def test_two_rows_carrying_one_span_leave_the_criterion_unestablished() -> None:
    """§2: the join is **unique or nothing**, and in **whichever order the rows are read**.

    Two ``ESTABLISHED``/``CONFIRMED`` rows of this goal for two declarations, each
    carrying a member on that one span, one row's bound step satisfying its declarations
    and the other's contradicting them → **unestablished**, and neither ``met`` nor
    ``unmet``. *"A precedence rule between them would be this decision inventing which
    of the user's own statements governs."*
    """
    rows = (
        a_row("auth-1", a_member(RIVERSIDE), tool_id="bookings"),
        a_row("auth-2", a_member(RIVERSIDE), tool_id="quotes"),
    )
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),
        a_decision(
            "d-2",
            definition=a_tool(postconditions=_BOOKED),
            ruling=a_ruling(authorised_by="auth-2"),
            digest=OTHER_DIGEST,
        ),
    )
    steps = (
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", output=_REFUSES, approval_ref="d-2"),
    )

    forward = await _compared(
        a_goal(a_criterion(RIVERSIDE)), *steps, decisions=decisions, rows=Rows(*rows)
    )
    backward = await _compared(
        a_goal(a_criterion(RIVERSIDE)), *steps, decisions=decisions, rows=Rows(*reversed(rows))
    )

    assert _one(forward) is CriterionResult.UNESTABLISHED
    assert _one(backward) is CriterionResult.UNESTABLISHED


async def test_two_members_of_one_row_on_one_span_leave_it_unestablished() -> None:
    """§2's second half again, over **two members of one row** at two kinds.

    ADR-0266 §3's *"no two members of one ``Authorization`` carry the same ``kind``"*
    leaves two members of one row free to rest on one span at two kinds, and the
    criterion is ``unestablished`` — the arm that fails against any implementation that
    picks a member or unions them.
    """
    row = a_row(
        "auth-1",
        a_member(RIVERSIDE, kind=BoundKind.TERMS),
        a_member(RIVERSIDE, kind=BoundKind.PERIOD),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
        rows=Rows(row),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_a_row_the_attempt_never_acted_under_is_not_an_authorising_row() -> None:
    """§2: *"a row no step of this attempt acted under … is not looked for"*.

    A third row of this goal carrying a member on that same span, named by no step's
    decision, leaves the criterion **met** — **the arm that fails against an
    implementation enumerating the goal's rows** rather than resolving the ones its own
    steps point at. The resolution is asked only for the id the pinned decision named.
    """
    rows = Rows(
        a_row("auth-1", a_member(RIVERSIDE)),
        a_row("auth-3", a_member(RIVERSIDE), tool_id="elsewhere"),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
        rows=rows,
    )

    assert _one(comparison) is CriterionResult.MET
    assert rows.calls == ["auth-1"], "only the id a pinned decision named was resolved"


async def test_a_request_the_member_does_not_fit_is_never_dispatched() -> None:
    """Arm 4's Saturday case: the step is committed ``AWAITING_APPROVAL`` and never runs.

    ADR-0254 §13 refuses the dispatch at ``ActionPolicy.decide``, so no bound step
    succeeds and the criterion is **unestablished** — **the arm that fails against any
    implementation reading a provider's ``{"status": "ok"}`` as agreement with the
    date**, there being no provider answer at all.
    """
    comparison = await _compared(
        a_goal(a_criterion(SUNDAY)),
        a_step(
            "s-1",
            status=StepStatus.AWAITING_APPROVAL,
            output=None,
            approval_ref=None,
            attempts=0,
        ),
        decisions=(),
        rows=Rows(a_row("auth-1", a_member(SUNDAY, kind=BoundKind.PERIOD))),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_the_span_is_compared_and_never_the_text() -> None:
    """Arm 4's residual, asserted as §9's residual rather than as a guarantee.

    A criterion whose **text** describes an unrelated fact while its ``span`` stays the
    one the row's member rests on reads **met**. §2 compared the span and never the
    text, and this arm records that rather than claiming it is desirable.
    """
    unrelated = a_criterion(RIVERSIDE, text="the dog was fed")
    comparison = await _compared(
        a_goal(unrelated),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert _one(comparison) is CriterionResult.MET


# --------------------------------------------------------------------------- #
# Arm 5 — the ladder, over the declarations and over the ordering              #
# --------------------------------------------------------------------------- #


async def test_nothing_claimed_at_all_is_rung_zero() -> None:
    """§3's rung 0: *"the attempt composed an answer and did nothing else"*."""
    comparison = await _compared(a_goal(), execution_ids=())

    assert comparison.rung is Rung.NOTHING


async def test_a_step_no_walk_claimed_leaves_the_rung_where_it_was() -> None:
    """§3: *"a step a plan declared and no walk claimed contributes nothing"*."""
    comparison = await _compared(
        a_goal(),
        a_step("s-1", status=StepStatus.PENDING, attempts=0, approval_ref=None, bound_tool=None),
    )

    assert comparison.rung is Rung.NOTHING


async def test_a_reversible_non_disclosing_act_is_rung_one() -> None:
    """§3's rung 1: a side-effecting act declared ``REVERSIBLE`` that discloses nothing.

    **And transmitting nothing**, which is the limb the decision carries rather than the
    declaration: a route-(d) ``ALLOW`` is an egress decision and reaches rung 2 on its
    binding alone, so the act that stays at rung 1 is one the policy allowed on its own
    rules (:func:`~verification_builders.an_unbound_ruling`).
    """
    comparison = await _compared(
        a_goal(),
        a_step("s-1", output=_HOLDS),
        decisions=(
            a_decision(
                "d-1", definition=a_tool(postconditions=_BOOKED), ruling=an_unbound_ruling()
            ),
        ),
    )

    assert comparison.rung is Rung.ACTED


async def test_an_irreversible_act_with_empty_discloses_is_rung_two() -> None:
    """§3: the ordering trap, explicitly.

    A ``side_effecting`` tool with ``reversibility=IRREVERSIBLE`` and empty ``discloses``
    reaches **rung 2** — **the arm that fails against a lexicographic comparison**,
    under which ``"irreversible" > "reversible"`` is ``False``. ADR-0016 §2 overrides
    all four comparison operators for exactly this reason.
    """
    irreversible = a_tool(reversibility=Reversibility.IRREVERSIBLE, discloses=())
    comparison = await _compared(
        a_goal(), a_step("s-1"), decisions=(a_decision("d-1", definition=irreversible),)
    )

    assert comparison.rung is Rung.CONSEQUENTIAL


async def test_a_reversible_act_that_discloses_is_rung_two() -> None:
    """§3: *"``discloses`` is read beside ``reversibility`` and neither stands alone"*."""
    disclosing = a_tool(reversibility=Reversibility.REVERSIBLE, discloses=(DataTier.OPERATIONAL,))
    comparison = await _compared(
        a_goal(), a_step("s-1"), decisions=(a_decision("d-1", definition=disclosing),)
    )

    assert comparison.rung is Rung.CONSEQUENTIAL


async def test_risk_level_alone_never_reaches_rung_two() -> None:
    """§3: *"``risk_level`` is **not** read"*, and no lane adds a limb for it."""
    risky = a_tool(risk_level=RiskLevel.CRITICAL, reversibility=Reversibility.REVERSIBLE)
    comparison = await _compared(
        a_goal(),
        a_step("s-1"),
        decisions=(a_decision("d-1", definition=risky, ruling=an_unbound_ruling()),),
    )

    assert comparison.rung is Rung.ACTED


async def test_a_satisfied_step_takes_the_rung_of_the_step_it_borrowed_from() -> None:
    """§3: *"its rung … comes from the step those identifiers name"*.

    A step committed ``SUCCEEDED`` from an earlier completed effect — **no ``→ RUNNING``
    claim of its own** — reaches the holder's rung. **The arm that fails against an
    implementation reading it as rung 0** while §2 verifies against its borrowed output.
    """
    holder = a_step("held", output=_HOLDS, approval_ref="d-1")
    borrower = a_step(
        "s-2",
        output=_HOLDS,
        attempts=0,
        approval_ref=None,
        bound_tool=None,
        satisfied_by=("e-0", "held"),
    )
    consequential = a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE)
    executions = Executions(an_execution(borrower), an_execution(holder, execution_id="e-0"))

    comparison = await compare(
        a_goal(a_criterion(RIVERSIDE)),
        an_attempt(EXECUTION),
        executions=executions,
        decisions=Decisions(a_decision("d-1", definition=consequential)),
        rows=Rows(a_row("auth-1", a_member(RIVERSIDE))),
    )

    assert comparison.rung is Rung.CONSEQUENTIAL
    assert _one(comparison) is CriterionResult.MET, (
        "the holder's pinned declarations and its own route and authorised_by are followed"
    )


async def test_a_satisfied_step_whose_holder_cannot_be_read_is_rung_two() -> None:
    """§3: *"where that step cannot be read the attempt is at rung 2"*."""
    borrower = a_step(
        "s-2",
        output=_HOLDS,
        attempts=0,
        approval_ref=None,
        bound_tool=None,
        satisfied_by=("e-lost", "held"),
    )

    comparison = await _compared(a_goal(), borrower)

    assert comparison.rung is Rung.CONSEQUENTIAL


async def test_a_claimed_step_whose_decision_the_trail_lost_is_rung_two() -> None:
    """§3: an unreadable pinned decision is **rung 2, not rung 1**.

    *"Neither its definition nor its ``egress_binding`` can be read, so nothing says the
    act was not irreversible or disclosing."* **The arm that fails against an
    implementation defaulting an unreadable definition to the harmless rung** — and §2's
    silence about such a step is not in tension with it: there it establishes nothing.
    """
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)), a_step("s-1", output=_HOLDS), decisions=()
    )

    assert comparison.rung is Rung.CONSEQUENTIAL
    assert _one(comparison) is CriterionResult.UNESTABLISHED
    assert comparison.outcome is AttemptOutcome.UNCERTAIN


async def test_a_decision_carrying_an_egress_binding_is_rung_two() -> None:
    """§3's third limb: *"or its decision carries an ``egress_binding``"*."""
    comparison = await _compared(
        a_goal(),
        a_step("s-1"),
        decisions=(a_decision("d-1", definition=a_tool(), egress_binding=a_binding()),),
    )

    assert comparison.rung is Rung.CONSEQUENTIAL


async def test_the_declaration_is_the_pinned_one_and_never_the_registry_s() -> None:
    """§2: the operative definition is *"the whole definition embedded by value"* in the ruling.

    The comparison is handed the ruling and never a registry, so a re-registration under
    the same id cannot reach it: the two decisions below carry the same tool **id** and
    different declarations, and each step's verdict follows the one **pinned to the act
    that ran**.
    """
    pinned = a_decision("d-1", definition=a_tool(postconditions=(field_equals("status", "ok"),)))
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output={"status": "ok"}),
        decisions=(pinned,),
    )

    assert _one(comparison) is CriterionResult.MET


async def test_a_store_failure_is_never_converted_into_a_verdict() -> None:
    """§2: an audit read and a ``resolve`` that each raise **propagate with their cause**.

    *"No lane reports a broken trail or an unreadable authorization as ``UNCERTAIN`` or
    ``ANSWERED``"*, and the execution read is on the same rule — while a decision the
    trail does **not hold** and a row the resolution answers ``None`` for are each
    ``unestablished``, which the two arms above already pin.
    """
    goal = a_goal(a_criterion(RIVERSIDE))
    with pytest.raises(AuditError):
        await compare(
            goal,
            an_attempt(),
            executions=Executions(an_execution(a_step("s-1"))),
            decisions=Decisions(failure=AuditError("the trail is unreadable")),
            rows=Rows(),
        )
    with pytest.raises(AuthorizationError):
        await compare(
            goal,
            an_attempt(),
            executions=Executions(an_execution(a_step("s-1"))),
            decisions=Decisions(a_decision("d-1")),
            rows=Rows(failure=AuthorizationError("the store is unreadable")),
        )
    with pytest.raises(PlanningError):
        await compare(
            goal,
            an_attempt(),
            executions=Executions(failure=PlanningError("the plan store is unreadable")),
            decisions=Decisions(),
            rows=Rows(),
        )


async def test_a_row_the_resolution_answers_none_for_establishes_nothing() -> None:
    """§2: fail-closed, and not an error."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
        rows=Rows(),
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED


async def test_no_resolution_wired_leaves_every_criterion_unestablished() -> None:
    """§3's seam, absent: a deployment wiring none resolves no row.

    The fail-closed direction stated at the wiring rather than at the comparison — no
    criterion is met, no attempt reaches ``VERIFIED``, and nothing raises.
    """
    comparison = await compare(
        a_goal(a_criterion(RIVERSIDE)),
        an_attempt(),
        executions=Executions(an_execution(a_step("s-1", output=_HOLDS))),
        decisions=Decisions(a_decision("d-1", definition=a_tool(postconditions=_BOOKED))),
        rows=None,
    )

    assert _one(comparison) is CriterionResult.UNESTABLISHED
    assert comparison.outcome is not AttemptOutcome.VERIFIED


# --------------------------------------------------------------------------- #
# Arm 6 — §4's six limbs, and each precedence boundary                         #
# --------------------------------------------------------------------------- #


async def test_a_goal_carrying_no_criterion_at_rung_one_is_answered() -> None:
    """§4's limb 6, and §1: *"a goal carrying no criterion is not thereby verified"*.

    ``fully_met`` requires **at least one** criterion, so an empty tuple is never read
    as *every criterion met*.
    """
    comparison = await _compared(
        a_goal(),
        a_step("s-1"),
        decisions=(a_decision("d-1", definition=a_tool(), ruling=an_unbound_ruling()),),
    )

    assert comparison.outcome is AttemptOutcome.ANSWERED
    assert comparison.report.continues is False


async def test_a_met_and_an_unmet_criterion_is_partial_and_never_verified() -> None:
    """§4's limb 4, and the boundary a wrong order passes: ``VERIFIED`` sits **below** it."""
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED), digest=DIGEST),
        a_decision(
            "d-2",
            definition=a_tool(postconditions=_BOOKED),
            ruling=a_ruling(authorised_by="auth-2"),
            digest=OTHER_DIGEST,
        ),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE), a_criterion(SUNDAY)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", output=_REFUSES, approval_ref="d-2"),
        decisions=decisions,
        rows=Rows(
            a_row("auth-1", a_member(RIVERSIDE)),
            a_row("auth-2", a_member(SUNDAY, kind=BoundKind.PERIOD), tool_id="other"),
        ),
    )

    assert comparison.results == (CriterionResult.MET, CriterionResult.UNMET)
    assert comparison.outcome is AttemptOutcome.PARTIAL
    assert comparison.report.continues is True


async def test_a_failed_read_at_rung_one_is_failed_and_never_answered() -> None:
    """§4's limb 1, pinned to ADR-0249 §5's *"no step failed"*.

    Every criterion unestablished beside a failed read at rung 0 or 1 → ``FAILED``, the
    arm that keeps ``ANSWERED`` from asserting two things the record contradicts.
    """
    reading = a_tool(side_effecting=False)
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", status=StepStatus.FAILED, output=None),
        decisions=(a_decision("d-1", definition=reading),),
    )

    assert comparison.outcome is AttemptOutcome.FAILED
    assert comparison.report.continues is True


async def test_a_failed_step_beside_a_met_criterion_is_partial() -> None:
    """§4: limb 1 requires *"no criterion is met"*, so a met one takes it out of reach."""
    # The met criterion's own act is a **read** authorised against the row, so the
    # attempt stays at rung 1 and limb 3 is out of reach — §3's rung-2 test reads
    # `side_effecting` first. The failed step is about something else and ran under the
    # policy's own rules, which is what "unrelated" means and what §7 requires: one row
    # cannot have admitted two different declarations.
    decisions = (
        a_decision(
            "d-1", definition=a_tool(postconditions=_BOOKED, side_effecting=False), digest=DIGEST
        ),
        a_decision(
            "d-2",
            definition=a_tool(side_effecting=False),
            digest=OTHER_DIGEST,
            ruling=an_unbound_ruling(),
        ),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE), a_criterion(SUNDAY)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", status=StepStatus.FAILED, output=None, approval_ref="d-2"),
        decisions=decisions,
    )

    assert comparison.rung is Rung.ACTED
    assert comparison.outcome is AttemptOutcome.PARTIAL


async def test_a_skipped_dependency_with_no_claim_is_condition_prevented() -> None:
    """§4's limb 2, and never ``ANSWERED``."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step(
            "s-1",
            status=StepStatus.SKIPPED,
            attempts=0,
            approval_ref=None,
            bound_tool=None,
            skip_reason=SkipReason.UNMET_DEPENDENCY,
        ),
    )

    assert comparison.outcome is AttemptOutcome.CONDITION_PREVENTED
    assert comparison.report.continues is False


async def test_a_denied_approval_after_a_successful_read_is_condition_prevented() -> None:
    """§4: ``blocked`` is pinned to the **skip** rather than to the absence of any claim."""
    decisions = (a_decision("d-1", definition=a_tool(side_effecting=False)),)
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output={"looked": True}, approval_ref="d-1"),
        a_step(
            "s-2",
            status=StepStatus.SKIPPED,
            attempts=0,
            approval_ref=None,
            bound_tool=None,
            skip_reason=SkipReason.APPROVAL_DENIED,
        ),
        decisions=decisions,
    )

    assert comparison.outcome is AttemptOutcome.CONDITION_PREVENTED


async def test_the_same_state_at_rung_one_with_no_skip_is_answered() -> None:
    """§4's limb 6, the pair of the arm above: a read that succeeded and nothing else."""
    decisions = (a_decision("d-1", definition=a_tool(side_effecting=False)),)
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output={"looked": True}, approval_ref="d-1"),
        decisions=decisions,
    )

    assert comparison.outcome is AttemptOutcome.ANSWERED


async def test_a_consequential_act_with_no_criterion_at_all_is_uncertain() -> None:
    """§4: ``UNCERTAIN`` precedes ``ANSWERED`` for a rung-2 attempt carrying no criterion.

    *"A consequential act ran and nothing verified it, which is what ``UNCERTAIN`` says
    and what ``ANSWERED`` would deny."*
    """
    comparison = await _compared(a_goal(), a_step("s-1", output=_HOLDS), decisions=(_booking(),))

    assert comparison.outcome is AttemptOutcome.UNCERTAIN


async def test_a_met_and_an_unestablished_criterion_at_rung_two_is_uncertain() -> None:
    """§4: ``UNCERTAIN`` precedes ``PARTIAL``, so it is not reported as partly not done."""
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE), a_criterion(SUNDAY)),
        a_step("s-1", output=_HOLDS),
        decisions=(_booking(),),
        rows=Rows(a_row("auth-1", a_member(RIVERSIDE))),
    )

    assert comparison.results == (CriterionResult.MET, CriterionResult.UNESTABLISHED)
    assert comparison.outcome is AttemptOutcome.UNCERTAIN


async def test_an_unrelated_failure_beside_a_consequential_success_is_uncertain() -> None:
    """§4: *"an unrelated ``FAILED`` or ``SKIPPED`` step therefore does not convert a
    rung-2 attempt whose criteria are merely unestablished into a claim about them"*.

    The two arms that fail against limbs 1 and 2 reading a failure about something else
    as a verdict about the criteria.
    """
    decisions = (
        a_decision("d-1", definition=_booking().tool, digest=DIGEST),
        a_decision(
            "d-2",
            definition=a_tool(side_effecting=False),
            digest=OTHER_DIGEST,
            ruling=an_unbound_ruling(),
        ),
    )
    failing = await _compared(
        a_goal(a_criterion(SUNDAY)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", status=StepStatus.FAILED, output=None, approval_ref="d-2"),
        decisions=decisions,
    )
    skipping = await _compared(
        a_goal(a_criterion(SUNDAY)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step(
            "s-2",
            status=StepStatus.SKIPPED,
            attempts=0,
            approval_ref=None,
            bound_tool=None,
            skip_reason=SkipReason.UNMET_DEPENDENCY,
        ),
        decisions=decisions,
    )

    assert failing.outcome is AttemptOutcome.UNCERTAIN
    assert skipping.outcome is AttemptOutcome.UNCERTAIN


async def test_a_rung_two_failure_is_uncertain_whether_or_not_it_is_bound() -> None:
    """§4: *"the member does not turn on the criterion join"*.

    A rung-2 attempt whose **only** consequential step stands ``FAILED`` with every
    criterion unestablished is ``UNCERTAIN``, and the identical record with that step
    **bound** to a criterion is ``UNCERTAIN`` likewise — never ``FAILED``. The arms that
    fail against an implementation reading a side-effecting failure as a disproof.
    """
    failing = a_step("s-1", status=StepStatus.FAILED, output=None)
    decisions = (_booking(),)
    unbound = await _compared(a_goal(a_criterion(SUNDAY)), failing, decisions=decisions)
    bound = await _compared(a_goal(a_criterion(RIVERSIDE)), failing, decisions=decisions)

    assert unbound.outcome is AttemptOutcome.UNCERTAIN
    assert bound.outcome is AttemptOutcome.UNCERTAIN


async def test_a_reversible_side_effecting_failure_at_rung_one_is_failed() -> None:
    """§4: *"``UNCERTAIN`` turns on the rung and on nothing else"*.

    A rung-1 attempt whose only step is ``side_effecting`` with
    ``reversibility=REVERSIBLE``, empty ``discloses`` and no egress binding, standing
    ``FAILED``, is ``FAILED`` — identically to the same attempt whose only step is a
    failed read. **The pair that fails against any implementation deriving a possible
    effect from ``side_effecting`` and ``FAILED``**, which ADR-0032 §2 already ruled out.
    """
    failing = a_step("s-1", status=StepStatus.FAILED, output=None)
    writing = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        failing,
        decisions=(
            a_decision("d-1", definition=a_tool(side_effecting=True), ruling=an_unbound_ruling()),
        ),
    )
    reading = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        failing,
        decisions=(
            a_decision("d-1", definition=a_tool(side_effecting=False), ruling=an_unbound_ruling()),
        ),
    )

    assert writing.outcome is AttemptOutcome.FAILED
    assert reading.outcome is AttemptOutcome.FAILED


async def test_a_refused_criterion_is_failed_at_every_rung() -> None:
    """§4: *"a criterion is refused only by an answer"*, and that is ``FAILED`` at every rung.

    The arm that keeps *established not to hold* reachable — a rung-2 attempt with a
    criterion **unmet** and none met is ``FAILED`` whatever else stands.
    """
    refused = a_step("s-1", output=_REFUSES)
    for declaration in (
        a_tool(postconditions=_BOOKED),
        a_tool(postconditions=_BOOKED, reversibility=Reversibility.IRREVERSIBLE),
    ):
        comparison = await _compared(
            a_goal(a_criterion(RIVERSIDE)),
            refused,
            decisions=(a_decision("d-1", definition=declaration),),
        )
        assert comparison.outcome is AttemptOutcome.FAILED, declaration.reversibility


async def test_every_criterion_met_beside_an_unrelated_failure_is_verified() -> None:
    """§4: *"an attempt whose every criterion is met is ``VERIFIED`` though a step failed"*.

    Limbs 4 and 5 read the criteria alone, and no lane adds a ``failed`` conjunct to
    either — which is what keeps §6's ``PARTIAL`` statement true of every attempt that
    reaches it.
    """
    decisions = (
        a_decision("d-1", definition=_booking().tool, digest=DIGEST),
        a_decision(
            "d-2",
            definition=a_tool(side_effecting=False),
            digest=OTHER_DIGEST,
            ruling=an_unbound_ruling(),
        ),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", status=StepStatus.FAILED, output=None, approval_ref="d-2"),
        decisions=decisions,
    )

    assert comparison.outcome is AttemptOutcome.VERIFIED
    assert comparison.report.continues is False


async def test_a_satisfied_step_carries_the_rung_into_the_member() -> None:
    """§4: *"the satisfied step carries the rung"* — ``UNCERTAIN``, never ``ANSWERED``.

    An attempt whose only step is satisfied from an earlier effect at a rung-2 holder,
    with every criterion unestablished, no failure and no skip; **and the same where the
    holder cannot be read**. The pair that would otherwise let ADR-0249 §5's *"nothing
    was verified, no step failed"* be asserted of an attempt that borrowed a
    consequential act's own answer.
    """
    borrower = a_step(
        "s-2",
        output=_HOLDS,
        attempts=0,
        approval_ref=None,
        bound_tool=None,
        satisfied_by=("e-0", "held"),
    )
    holder = a_step("held", output=_HOLDS, approval_ref="d-1")
    readable = await compare(
        a_goal(a_criterion(SUNDAY)),
        an_attempt(EXECUTION),
        executions=Executions(an_execution(borrower), an_execution(holder, execution_id="e-0")),
        decisions=Decisions(_booking()),
        rows=Rows(),
    )
    lost = await _compared(a_goal(a_criterion(SUNDAY)), borrower, rows=Rows())

    assert readable.outcome is AttemptOutcome.UNCERTAIN
    assert lost.outcome is AttemptOutcome.UNCERTAIN


async def test_continues_is_false_on_a_closed_goal() -> None:
    """§6: ``continues`` needs the goal **open** as well (ADR-0250 §1).

    *"No lane … sets it on a closed goal."* The outcome is one of the three that offer
    something to continue, and the report still says ``False``.
    """
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE), status=GoalStatus.ABANDONED),
        a_step("s-1", output=_REFUSES),
        decisions=(a_decision("d-1", definition=a_tool(postconditions=_BOOKED)),),
    )

    assert comparison.outcome is AttemptOutcome.FAILED
    assert comparison.report.continues is False


async def test_only_a_route_d_allow_contributes_a_row() -> None:
    """ADR-0254 §7's discriminator is over an **ALLOW**, and the model keeps the rest out.

    A ``CONFIRM`` or a ``DENY`` that cited an authorisation is unconstructible —
    :class:`~ai_assistant.core.types.PermissionRuling` refuses it — so the only shapes
    a stored decision can carry beside a route-(d) ``ALLOW`` are the ones the arms above
    already walk. This arm records that the outcome is read all the same: what §2 names
    is *"a route-(d) ``ALLOW``"*, and a reader who dropped the outcome from the test
    would be relying on a validator in another module to keep it true.
    """
    with pytest.raises(ValueError, match="cites no authorisation"):
        a_ruling(outcome=PermissionOutcome.CONFIRM)
    with pytest.raises(ValueError, match="cites no authorisation"):
        a_ruling(outcome=PermissionOutcome.DENY)


async def test_continues_is_true_on_exactly_three_members_over_an_open_goal() -> None:
    """Arm 10's L4 half: §6's ``continues``, over every member and both goal states.

    *"``True`` **exactly** where the outcome is ``PARTIAL``, ``FAILED`` or ``UNCERTAIN``
    **and** the goal is open (ADR-0250 §1: ``ACTIVE`` or ``BLOCKED``)"*, and ``False`` on
    ``VERIFIED``, on ``ANSWERED`` and on ``CONDITION_PREVENTED`` — unconditionally, with
    no second fact consulted. **``CANCELLED`` is reached by no limb** (§4) and so is not
    a value this function is ever handed; it is walked here anyway, because what the
    rule says of it is the same thing it says of every member outside the three.
    """
    unfinished = {AttemptOutcome.PARTIAL, AttemptOutcome.FAILED, AttemptOutcome.UNCERTAIN}
    for outcome in AttemptOutcome:
        for status in (GoalStatus.ACTIVE, GoalStatus.BLOCKED):
            assert continues_on(outcome, status) is (outcome in unfinished), (outcome, status)
        for closed in (GoalStatus.ACHIEVED, GoalStatus.ABANDONED):
            assert continues_on(outcome, closed) is False, (outcome, closed)


async def test_every_criterion_met_beside_an_indeterminate_step_is_still_verified() -> None:
    """Arm 7's pair, at the seam that decides the member: limbs 4 and 5 gain no conjunct.

    An ``INDETERMINATE`` step is not decisive under §2 — it neither satisfies nor
    contradicts — so a criterion another step's own answer established stays **met**
    beside one, and §4's limbs yield **``VERIFIED``**. *"``VERIFIED`` is therefore
    unreachable beside a possible effect, and with it ``ACHIEVED`` — reached by the
    attempt **not ending** rather than by a conjunct on limbs 4 and 5"*, which is also
    what keeps ADR-0259 §4's acts 3 and 4 reachable.

    **This is the arm that fails against an implementation closing the gap in the wrong
    place** — one that quietly withheld ``VERIFIED`` here would take the ending rule's
    work into the limbs, and ADR-0259's reconciliation route with it. The engine's own
    half, that such an attempt ends nothing at all, is
    ``test_engine_verify_phase.py``'s.
    """
    decisions = (
        a_decision("d-1", definition=a_tool(postconditions=_BOOKED), digest=DIGEST),
        a_decision("d-2", definition=a_tool(postconditions=_BOOKED), digest=OTHER_DIGEST),
    )
    comparison = await _compared(
        a_goal(a_criterion(RIVERSIDE)),
        a_step("s-1", output=_HOLDS, approval_ref="d-1"),
        a_step("s-2", status=StepStatus.INDETERMINATE, output=None, approval_ref="d-2"),
        decisions=decisions,
    )

    assert _one(comparison) is CriterionResult.MET, "§2: an INDETERMINATE step is not decisive"
    assert comparison.outcome is AttemptOutcome.VERIFIED
