"""ADR-0259 §2's reuse conditions, evaluated where the effect claim is taken.

`claim_effect` establishes the **first** of §2's three conditions itself — *"the
intended action is the same and the keys are equal, which ``claim_effect``
establishes together"* — and answers `COMPLETED` only where both hold. The other
two are about the **claiming step** rather than about the row, so the stage that
took the claim checks them: *"every member of the step's own ``when`` is satisfied
for the goal at that instant, on ADR-0252 §6's four tests as ADR-0253 §5 requires
of a dispatch"*, and *"the step's ``verifies`` predicate holds over the borrowed
``output``"* (ADR-0253 §4).

**This is the tree's first evaluation of either**, and that is why they are here
rather than reused. :mod:`ai_assistant.orchestration.evidence` records in terms
that §6's tests *"have no caller on any tree this lane can reach"*, and
:mod:`ai_assistant.orchestration.validating` leaves the ``verifies`` half of
ADR-0253 §2's dependency rule to A7's driver. ADR-0255's own L2 lands that driver
and will evaluate both **at dispatch**; this module is the one statement of each,
so the driver reads it rather than restating it.

**Nothing here holds a store and nothing here is async.** Every function is pure
over values the caller has already read, which is what lets the executor take its
three reads in one place and decide in another.

**And none of it establishes that the reuse was *right*** (§2). ADR-0265 §6 rules
the three conditions **necessary and not sufficient**: none of them asks whether
the completed act satisfies the current interpretation, which is verification
against the goal's criteria and is A10's by name.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    EvidenceBasis,
    EvidenceStanding,
    VerificationKind,
    support_covers,
)
from ai_assistant.orchestration.evidence import affirmative, effective_instant

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime, timedelta

    from ai_assistant.core.types import (
        FrozenJson,
        Goal,
        GoalElement,
        GoalEvidence,
        PlanStep,
        StepCondition,
        StepVerification,
    )

#: The JSON scalars a byte-exact comparison may never cross between (ADR-0253 §4).
#: ``bool`` is a subclass of ``int`` in Python and ``1 == 1.0`` is true, so a plain
#: ``==`` would treat ``1`` as ``true`` and an integer as a float — two of the three
#: coercions ``FIELD_EQUALS`` names by name.
_NUMERIC: tuple[type, ...] = (bool, int, float)

#: A JSON array is held as a ``tuple`` once ``FrozenJsonValue`` has frozen it and as a
#: ``list`` before that, so :func:`_identical` tests both — and tests them by name
#: rather than through ``Sequence``, because ``str`` is a ``Sequence`` and a string is a
#: JSON **scalar**, compared whole.


def condition_elements(goal: Goal, *, revision: int | None) -> Mapping[str, GoalElement]:
    """The condition elements of the revision a plan targets, by ``id`` (ADR-0253 §5).

    ``StepCondition.about`` names *"the ``GoalElement.id`` of a **condition element**
    of the interpretation the plan's ``targets_revision`` names"*, so the lookup is
    scoped to that one revision's ``conditions`` and to no other group and no other
    revision. An element carrying no ``id`` is named by no condition (ADR-0253 §7) and
    is left out.

    Args:
        goal: The goal the plan belongs to.
        revision: The revision the plan targets. ``None`` is a plan ``save_plan``
            would refuse, and resolves nothing.

    Returns:
        The condition elements of that revision, keyed by id; empty where the goal
        holds no such revision.
    """
    if revision is None:
        return {}
    for held in goal.interpretation:
        if held.revision == revision:
            return {element.id: element for element in held.conditions if element.id is not None}
    return {}


def conditions_hold(
    step: PlanStep,
    *,
    elements: Mapping[str, GoalElement],
    rows: Sequence[GoalEvidence],
    at: datetime,
) -> bool:
    """Whether every member of ``step``'s ``when`` is satisfied at ``at`` (ADR-0252 §6).

    ``when`` is *"a conjunction of positive requirements and nothing else"*, so a step
    declaring none is satisfied and one declaring several needs all of them. The
    step's ``evidence_recency`` *"applies to **every** condition of that step"*.

    Args:
        step: The step whose conditions these are.
        elements: The condition elements of the revision its plan targets
            (:func:`condition_elements`).
        rows: The goal's evidence history.
        at: The moment of dispatch, which test 4 is evaluated at.

    Returns:
        Whether every condition is satisfied.
    """
    return all(
        _condition_holds(
            condition, elements=elements, rows=rows, recency=step.evidence_recency, at=at
        )
        for condition in step.when
    )


def _condition_holds(
    condition: StepCondition,
    *,
    elements: Mapping[str, GoalElement],
    rows: Sequence[GoalEvidence],
    recency: timedelta | None,
    at: datetime,
) -> bool:
    """Whether one row of ``rows`` satisfies ``condition`` on all four tests (§6).

    **One row and never several.** *"The four tests are evaluated over a single row,
    and no lane satisfies a condition by combining two"* — which is why the four
    conjuncts sit inside the ``any`` rather than beside it.

    **An ``about`` that resolves to no element of the targeted revision satisfies
    nothing.** ``save_plan`` refuses a plan whose condition names no element of the
    revision it targets, so the case is unreachable through that door; where it is
    reached anyway the direction is ADR-0228 §2(a)'s, since a condition nobody can
    read is a requirement nobody can show was met.
    """
    element = elements.get(condition.about)
    if element is None:
        return False
    return any(
        _covers(element, row)
        and _is_the_evidence_declared(condition, row)
        and row.standing is EvidenceStanding.STANDING
        and _recent_enough(row, recency=recency, at=at)
        for row in rows
    )


def _covers(element: GoalElement, row: GoalEvidence) -> bool:
    """Test 1, coverage, over the applicability the condition's element declares.

    *"An empty ``supported`` covers nothing, so a row with none fails here first. A
    condition that declares no applicability imposes no coverage requirement, and
    this test is then satisfied by any row whose ``supported`` is **non-empty** — a
    condition about no axis this decision can compare is not thereby a condition any
    row satisfies for free."*
    """
    if element.applicability is None:
        return bool(row.supported)
    return support_covers(row.supported, required=element.applicability)


def _is_the_evidence_declared(condition: StepCondition, row: GoalEvidence) -> bool:
    """Test 2, the evidence the condition declared, per basis (§6).

    On ``INTERPRETATION`` the row's ``declaration`` equals the element the condition
    is about and its ``verdict`` **is** the member the condition requires — a
    comparison against a value of a closed enumeration, which is what stops *"an
    affirmative interpretation of a **different** proposition"* satisfying it. On
    ``READ_OUTCOME`` the row's verdict is **answering** in §5's sense
    (:func:`~ai_assistant.orchestration.evidence.affirmative`), and where the
    condition declares a ``read_kind`` the row's equals it.
    """
    if row.basis is not condition.basis:
        return False
    if condition.basis is EvidenceBasis.INTERPRETATION:
        required = condition.requires
        # Non-`None` by `StepCondition`'s own validator on this basis; read rather
        # than asserted, because a validator is not a type narrowing.
        return (
            required is not None
            and row.declaration == condition.about
            and row.verdict == required.value
        )
    if condition.read_kind is not None and row.read_kind is not condition.read_kind:
        return False
    return affirmative(row)


def _recent_enough(row: GoalEvidence, *, recency: timedelta | None, at: datetime) -> bool:
    """Test 4, recency, against the row's effective instant (§6).

    *"A step that declares no recency requirement imposes none: its condition is
    satisfied by a row that passes the first three tests however old it is."* The
    instant is ``as_of`` where the source declared one and ``read_at`` otherwise,
    which is the one :mod:`~ai_assistant.orchestration.evidence` already keys §8's
    sixth limb on.

    A row whose effective instant is **ahead** of ``at`` is inside any window: the
    comparison is on the elapsed duration, and a source declaring a future ``as_of``
    is not a staleness this test has anything to say about.
    """
    if recency is None:
        return True
    return at - effective_instant(row) <= recency


def verification_holds(verifies: StepVerification | None, output: FrozenJson) -> bool:
    """Whether ``output`` satisfies ``verifies`` (ADR-0253 §4).

    *"A step declaring no ``verifies`` imposes none"*, and the three members are
    mechanical: the output is not ``None``; it is a JSON **object** carrying
    ``field`` at a value that is not JSON ``null``; or that **and** the value equals
    ``equals`` byte-exactly.

    **It is evaluated in code and never by a model**, and it is never verification
    against the goal's criteria, which is A10's.

    Args:
        verifies: The predicate, or ``None`` where the step declares none.
        output: The output it is read over — here the **borrowed** one, which is the
            whole of what ADR-0259 §2's third reuse condition asks about.

    Returns:
        Whether the predicate holds.
    """
    if verifies is None:
        return True
    if verifies.kind is VerificationKind.OUTPUT_PRESENT:
        return output is not None
    # `field` is non-`None` on the other two kinds by `StepVerification`'s validator.
    if not isinstance(output, Mapping) or verifies.field is None:
        return False
    # An output that is not an object, an absent key and a key whose value is JSON
    # ``null`` each fail ``FIELD_PRESENT``, so the absent and the null case are one
    # here rather than two.
    value = output.get(verifies.field)
    if value is None:
        return False
    return verifies.kind is VerificationKind.FIELD_PRESENT or _identical(value, verifies.equals)


def _identical(left: FrozenJson, right: FrozenJson) -> bool:
    """Byte-exact equality for ``FIELD_EQUALS``, with no numeric coercion (§4).

    *"No lane folds case, coerces a number to a string, compares a float by
    tolerance, or treats ``1`` as ``true``."* Python's own ``==`` does two of those
    on its own — ``True == 1`` and ``1 == 1.0`` are both true — so a number or a
    boolean on either side additionally has to be the **same** JSON type.

    **And it walks the value rather than checking its top level**, because ``equals``
    is a ``FrozenJsonValue`` and a JSON object or array is one: ``{"count": true}``
    equals ``{"count": 1}`` under a top-level ``==``, and ``[1]`` equals ``[1.0]``,
    which is the same coercion §4 names one level down. A container compares to a
    container of the **same kind** with the same keys, or the same length, and every
    member compared this way; a container never compares equal to a scalar.
    Adversarial review, round 1, ``blocker``.
    """
    if isinstance(left, Mapping) or isinstance(right, Mapping):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            return False
        return left.keys() == right.keys() and all(
            _identical(left[key], right[key]) for key in left
        )
    if isinstance(left, tuple | list) or isinstance(right, tuple | list):
        if not isinstance(left, tuple | list) or not isinstance(right, tuple | list):
            return False
        return len(left) == len(right) and all(
            _identical(mine, theirs) for mine, theirs in zip(left, right, strict=True)
        )
    if isinstance(left, _NUMERIC) or isinstance(right, _NUMERIC):
        return type(left) is type(right) and left == right
    return left == right


def told_once(step_ids: Sequence[str]) -> tuple[str, ...] | None:
    """``TurnOutcome.satisfied_from_earlier`` for one turn's satisfactions (§2).

    *"``None`` on every turn that satisfied no step this way, otherwise the ids of
    the steps this turn satisfied, **in walk order**"*, and a model validator refuses
    an empty non-``None`` tuple — so ``None`` is the one spelling of *nothing was
    satisfied* and ``()`` is unconstructable.

    **The order is the walk's and the sequence is not reduced.** No sort, no set, no
    reversal and no de-duplication: a step is satisfied at most once, so two equal
    ids would be a defect to surface rather than a repetition to collapse, and arm 1
    fails an implementation that collapsed them.

    Args:
        step_ids: The steps this turn satisfied, in the order it satisfied them.

    Returns:
        The tuple, or ``None`` where nothing was satisfied.
    """
    return tuple(step_ids) or None
