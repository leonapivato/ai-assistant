"""ADR-0252 §6's four tests and ADR-0253 §4's predicate, over the module that states them.

:mod:`ai_assistant.orchestration.effects` is this tree's first evaluation of either, and
it is reached from exactly one caller — ADR-0259 §2's reuse conditions, checked where the
effect claim is taken. ``test_effect_claim.py`` drives that caller and asserts one row per
condition; what is asserted **here** is the predicate itself, whose operands are members
of closed vocabularies and whose failure modes a driven arm cannot enumerate without
building a plan per row.

**The four tests are evaluated over a single row and never two** (§6), so every case that
supplies more than one row supplies them to find out which one the answer came from.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    Goal,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    Ground,
    InterpretationVerdict,
    MemorySource,
    PlanStep,
    Provenance,
    ReadKind,
    ReadOutcomeKind,
    StepCondition,
    StepVerification,
    TimeWindow,
    VerificationKind,
)
from ai_assistant.orchestration.effects import (
    condition_elements,
    conditions_hold,
    verification_holds,
)

if TYPE_CHECKING:
    from ai_assistant.core.types import FrozenJson

AT: Final = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)
ELEMENT: Final = "e-1"
SUNDAY: Final = EvidenceApplicability(topics=("sunday",))
SATURDAY: Final = EvidenceApplicability(topics=("saturday",))


# --- builders -----------------------------------------------------------


def element(*, applicability: EvidenceApplicability | None = SUNDAY) -> GoalElement:
    """The condition element a ``StepCondition.about`` names."""
    return GoalElement(
        id=ELEMENT,
        text="the trip is on Sunday",
        ground=Ground.USER_STATED,
        span="on Sunday",
        applicability=applicability,
    )


def a_read_row(  # noqa: PLR0913 — one keyword per axis a row of §6's table varies
    row_id: str = "ev-1",
    *,
    supported: tuple[EvidenceApplicability, ...] = (SUNDAY,),
    verdict: ReadOutcomeKind = ReadOutcomeKind.RETURNED_RECORDS,
    standing: EvidenceStanding = EvidenceStanding.STANDING,
    read_kind: ReadKind = ReadKind.FORECAST_READ,
    read_at: datetime = AT,
    as_of: datetime | None = None,
) -> GoalEvidence:
    """A ``READ_OUTCOME`` row, varied one axis at a time."""
    return GoalEvidence(
        id=row_id,
        goal_id="g-1",
        attempt_id="a-1",
        basis=EvidenceBasis.READ_OUTCOME,
        read_kind=read_kind,
        supported=supported,
        supported_elided=0,
        read_at=read_at,
        as_of=as_of,
        # A `WEB_SEARCH` row names no record — "its records are minted for one turn and
        # resolve in no store" (ADR-0252 §1) — so the axis this builder varies decides it.
        records=() if read_kind is ReadKind.WEB_SEARCH else ("r-1",),
        returned=1,
        admitted=1,
        verdict=verdict.value,
        standing=standing,
        superseded_by="ev-later" if standing is EvidenceStanding.SUPERSEDED else None,
        inapplicable_at_revision=2 if standing is EvidenceStanding.INAPPLICABLE else None,
    )


def an_interpretation_row(
    *,
    declaration: str = ELEMENT,
    verdict: InterpretationVerdict = InterpretationVerdict.QUALIFIES,
) -> GoalEvidence:
    """An ``INTERPRETATION`` row, which test 2 compares by declaration **and** member."""
    return GoalEvidence(
        id="ev-i",
        goal_id="g-1",
        attempt_id="a-1",
        basis=EvidenceBasis.INTERPRETATION,
        declaration=declaration,
        supported=(SUNDAY,),
        supported_elided=0,
        read_at=AT,
        records=("r-1",),
        returned=0,
        admitted=0,
        verdict=verdict.value,
        standing=EvidenceStanding.STANDING,
    )


def conditioned(*conditions: StepCondition, recency: timedelta | None = None) -> PlanStep:
    """A step declaring ``conditions``, and the recency that applies to every one."""
    return PlanStep(
        id="s-1",
        intent="book it",
        capability="book_room",
        when=conditions,
        evidence_recency=recency,
    )


def reads_the_element(
    *, basis: EvidenceBasis = EvidenceBasis.READ_OUTCOME, **fields: object
) -> StepCondition:
    """A condition about :data:`ELEMENT` on ``basis``."""
    return StepCondition(about=ELEMENT, basis=basis, **fields)  # type: ignore[arg-type]


# --- condition_elements: the targeted revision's conditions, by id ------


def test_only_the_targeted_revisions_condition_elements_are_resolvable() -> None:
    """``about`` names a condition element *of the revision the plan targets* (§5, §7)."""
    goal = Goal(
        id="g-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room",
                conditions=(element(),),
                recorded_at=AT,
                raised_by="t-1",
            ),
            GoalInterpretation(
                revision=2,
                outcome="book a room",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room",
                constraints=(element(),),
                recorded_at=AT,
                raised_by="t-2",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )

    assert set(condition_elements(goal, revision=1)) == {ELEMENT}
    assert condition_elements(goal, revision=2) == {}, "a constraint is not a condition element"
    assert condition_elements(goal, revision=3) == {}, "a revision the goal does not hold"
    assert condition_elements(goal, revision=None) == {}, "a plan save_plan would refuse"


def test_a_condition_naming_no_element_of_that_revision_satisfies_nothing() -> None:
    """Fail closed: a requirement nobody can read is not one anybody showed was met."""
    assert not conditions_hold(
        conditioned(reads_the_element()), elements={}, rows=[a_read_row()], at=AT
    )


def test_a_step_declaring_no_condition_is_satisfied_by_an_empty_history() -> None:
    """``when`` is a conjunction, and the empty conjunction holds (ADR-0253 §5)."""
    assert conditions_hold(conditioned(), elements={}, rows=[], at=AT)


# --- test 1: coverage ---------------------------------------------------


@pytest.mark.parametrize(
    ("applicability", "supported", "holds"),
    [
        pytest.param(SUNDAY, (SUNDAY,), True, id="covered"),
        pytest.param(SUNDAY, (SATURDAY,), False, id="a-different-region-covers-nothing"),
        pytest.param(SUNDAY, (), False, id="an-empty-supported-covers-nothing"),
        pytest.param(None, (SATURDAY,), True, id="no-applicability-imposes-no-coverage"),
        pytest.param(None, (), False, id="but-still-never-an-empty-supported"),
    ],
)
def test_coverage_is_test_ones_whole_content(
    applicability: EvidenceApplicability | None,
    supported: tuple[EvidenceApplicability, ...],
    *,
    holds: bool,
) -> None:
    """§6 test 1, including the two directions its absent-declaration clause takes."""
    assert (
        conditions_hold(
            conditioned(reads_the_element()),
            elements={ELEMENT: element(applicability=applicability)},
            rows=[a_read_row(supported=supported)],
            at=AT,
        )
        is holds
    )


def test_no_condition_is_satisfied_by_combining_two_rows() -> None:
    """*"A condition covered by neither of two rows alone is not satisfied by their union."*"""
    both = EvidenceApplicability(topics=("saturday", "sunday"))

    assert not conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element(applicability=both)},
        rows=[a_read_row("ev-1", supported=(SATURDAY,)), a_read_row("ev-2", supported=(SUNDAY,))],
        at=AT,
    )
    assert conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element(applicability=both)},
        rows=[a_read_row("ev-3", supported=(both,))],
        at=AT,
    )


# --- test 2: the evidence the condition declared ------------------------


def test_a_read_outcome_condition_is_satisfied_by_an_answering_row_alone() -> None:
    """§5's partition: the three answering members, and the four that state nothing came back."""
    answering = (
        ReadOutcomeKind.RETURNED_RECORDS,
        ReadOutcomeKind.DUPLICATE,
        ReadOutcomeKind.TRUNCATED,
    )
    silent = (
        ReadOutcomeKind.EMPTY,
        ReadOutcomeKind.REFUSED,
        ReadOutcomeKind.FAILED,
        ReadOutcomeKind.EXPIRED,
    )
    for verdict in answering:
        assert conditions_hold(
            conditioned(reads_the_element()),
            elements={ELEMENT: element()},
            rows=[a_read_row(verdict=verdict)],
            at=AT,
        ), verdict
    for verdict in silent:
        assert not conditions_hold(
            conditioned(reads_the_element()),
            elements={ELEMENT: element()},
            rows=[a_read_row(verdict=verdict)],
            at=AT,
        ), verdict


def test_a_row_of_the_wrong_basis_satisfies_nothing() -> None:
    """*"A row of the wrong basis, the wrong proposition or the wrong member satisfies nothing."*"""
    assert not conditions_hold(
        conditioned(
            reads_the_element(
                basis=EvidenceBasis.INTERPRETATION, requires=InterpretationVerdict.QUALIFIES
            )
        ),
        elements={ELEMENT: element()},
        rows=[a_read_row()],
        at=AT,
    )
    assert not conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element()},
        rows=[an_interpretation_row()],
        at=AT,
    )


@pytest.mark.parametrize(
    ("declaration", "verdict", "holds"),
    [
        pytest.param(ELEMENT, InterpretationVerdict.QUALIFIES, True, id="the-declared-member"),
        pytest.param(ELEMENT, InterpretationVerdict.DOES_NOT_QUALIFY, False, id="another-member"),
        pytest.param(
            ELEMENT, InterpretationVerdict.INCONCLUSIVE, False, id="the-does-not-settle-member"
        ),
        pytest.param("e-other", InterpretationVerdict.QUALIFIES, False, id="another-proposition"),
    ],
)
def test_an_interpretation_row_is_matched_to_the_declaration_and_the_member(
    declaration: str, verdict: InterpretationVerdict, *, holds: bool
) -> None:
    """Round 2's two findings: *"and it says the trip is safe"*, about **this** proposition."""
    assert (
        conditions_hold(
            conditioned(
                reads_the_element(
                    basis=EvidenceBasis.INTERPRETATION,
                    requires=InterpretationVerdict.QUALIFIES,
                )
            ),
            elements={ELEMENT: element()},
            rows=[an_interpretation_row(declaration=declaration, verdict=verdict)],
            at=AT,
        )
        is holds
    )


def test_a_declared_read_kind_is_compared_and_an_undeclared_one_is_not() -> None:
    """``StepCondition.read_kind`` narrows a ``READ_OUTCOME`` condition (ADR-0253 §5)."""
    assert conditions_hold(
        conditioned(reads_the_element(read_kind=ReadKind.FORECAST_READ)),
        elements={ELEMENT: element()},
        rows=[a_read_row(read_kind=ReadKind.FORECAST_READ)],
        at=AT,
    )
    assert not conditions_hold(
        conditioned(reads_the_element(read_kind=ReadKind.WEB_SEARCH)),
        elements={ELEMENT: element()},
        rows=[a_read_row(read_kind=ReadKind.FORECAST_READ)],
        at=AT,
    )
    assert conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element()},
        rows=[a_read_row(read_kind=ReadKind.WEB_SEARCH)],
        at=AT,
    )


# --- test 3: standing ---------------------------------------------------


@pytest.mark.parametrize(
    "standing",
    [EvidenceStanding.INAPPLICABLE, EvidenceStanding.SUPERSEDED],
)
def test_only_a_standing_row_satisfies_anything(standing: EvidenceStanding) -> None:
    """*"An ``INAPPLICABLE`` row and a ``SUPERSEDED`` row each satisfy nothing."*"""
    assert not conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element()},
        rows=[a_read_row(standing=standing)],
        at=AT,
    )


# --- test 4: recency ----------------------------------------------------


def test_a_step_declaring_no_recency_is_satisfied_however_old_the_row_is() -> None:
    """*"Evidence never expires by itself"*, and no figure supplies a default."""
    ancient = a_read_row(read_at=AT - timedelta(days=4000))

    assert conditions_hold(
        conditioned(reads_the_element()), elements={ELEMENT: element()}, rows=[ancient], at=AT
    )


@pytest.mark.parametrize(
    ("read_at", "as_of", "holds"),
    [
        pytest.param(AT - timedelta(minutes=5), None, True, id="inside-on-read_at"),
        pytest.param(AT - timedelta(minutes=30), None, False, id="outside-on-read_at"),
        pytest.param(
            AT - timedelta(minutes=5), AT - timedelta(hours=3), False, id="as_of-outranks-read_at"
        ),
        pytest.param(
            AT - timedelta(hours=3), AT - timedelta(minutes=1), True, id="and-the-other-way"
        ),
        pytest.param(AT, AT + timedelta(hours=1), True, id="a-future-as_of-is-not-staleness"),
    ],
)
def test_recency_is_measured_against_the_rows_effective_instant(
    read_at: datetime, as_of: datetime | None, *, holds: bool
) -> None:
    """*"Against ``as_of`` where the source declared one and against ``read_at`` otherwise."*"""
    assert (
        conditions_hold(
            conditioned(reads_the_element(), recency=timedelta(minutes=15)),
            elements={ELEMENT: element()},
            rows=[a_read_row(read_at=read_at, as_of=as_of)],
            at=AT,
        )
        is holds
    )


def test_the_recency_applies_to_every_condition_of_the_step() -> None:
    """One figure on the step, not one per condition (ADR-0253 §5)."""
    other = GoalElement(
        id="e-2",
        text="the site is open",
        ground=Ground.USER_STATED,
        span="open",
        applicability=SATURDAY,
    )
    step = conditioned(
        reads_the_element(),
        StepCondition(about="e-2", basis=EvidenceBasis.READ_OUTCOME),
        recency=timedelta(minutes=15),
    )
    elements = {ELEMENT: element(), "e-2": other}
    fresh = a_read_row("ev-1", read_at=AT - timedelta(minutes=5))
    stale = a_read_row("ev-2", supported=(SATURDAY,), read_at=AT - timedelta(hours=2))

    assert not conditions_hold(step, elements=elements, rows=[fresh, stale], at=AT)
    assert conditions_hold(
        step,
        elements=elements,
        rows=[fresh, a_read_row("ev-3", supported=(SATURDAY,), read_at=AT - timedelta(minutes=1))],
        at=AT,
    )


def test_a_window_axis_is_covered_by_containment_and_not_by_overlap() -> None:
    """§2's relation, borrowed whole: coverage is containment on every axis ``other`` applies."""
    needed = EvidenceApplicability(
        window=TimeWindow(start=AT, end=AT + timedelta(hours=2)), topics=("sunday",)
    )
    contains = EvidenceApplicability(
        window=TimeWindow(start=AT - timedelta(hours=1), end=AT + timedelta(hours=3)),
        topics=("sunday",),
    )
    overlaps = EvidenceApplicability(
        window=TimeWindow(start=AT + timedelta(hours=1), end=AT + timedelta(hours=9)),
        topics=("sunday",),
    )

    assert conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element(applicability=needed)},
        rows=[a_read_row(supported=(contains,))],
        at=AT,
    )
    assert not conditions_hold(
        conditioned(reads_the_element()),
        elements={ELEMENT: element(applicability=needed)},
        rows=[a_read_row(supported=(overlaps,))],
        at=AT,
    )


# --- ADR-0253 §4's predicate -------------------------------------------


def test_a_step_declaring_no_verification_imposes_none() -> None:
    """*"A step declaring no ``verifies`` imposes none"* — over any output at all."""
    assert verification_holds(None, None)
    assert verification_holds(None, {"anything": 1})


@pytest.mark.parametrize(
    ("output", "holds"),
    [
        pytest.param(None, False, id="null"),
        pytest.param(0, True, id="a-falsey-value-is-still-present"),
        pytest.param("", True, id="and-so-is-an-empty-string"),
        pytest.param({"a": 1}, True, id="an-object"),
    ],
)
def test_output_present_reads_the_output_and_nothing_in_it(
    output: FrozenJson, *, holds: bool
) -> None:
    """``OUTPUT_PRESENT``: *"the producing step's ``output`` is not ``None``"*."""
    assert (
        verification_holds(StepVerification(kind=VerificationKind.OUTPUT_PRESENT), output) is holds
    )


@pytest.mark.parametrize(
    ("output", "holds"),
    [
        pytest.param({"booking": "bk-9"}, True, id="present"),
        pytest.param({"booking": None}, False, id="a-null-value-fails-it"),
        pytest.param({"other": 1}, False, id="an-absent-key-fails-it"),
        pytest.param("bk-9", False, id="an-output-that-is-not-an-object-fails-it"),
        pytest.param(None, False, id="and-so-does-no-output-at-all"),
    ],
)
def test_field_present_reads_one_key_of_an_object(output: FrozenJson, *, holds: bool) -> None:
    """``FIELD_PRESENT``'s three named failures, and the depth is one (ADR-0253 §4)."""
    predicate = StepVerification(kind=VerificationKind.FIELD_PRESENT, field="booking")

    assert verification_holds(predicate, output) is holds


@pytest.mark.parametrize(
    ("equals", "value", "holds"),
    [
        pytest.param("bk-9", "bk-9", True, id="equal"),
        pytest.param("bk-9", "BK-9", False, id="no-case-is-folded"),
        pytest.param(1, 1, True, id="two-integers"),
        pytest.param(1, True, False, id="one-is-never-true"),
        pytest.param(True, 1, False, id="nor-the-other-way"),
        pytest.param(1, 1.0, False, id="an-integer-is-not-a-float"),
        pytest.param(1, "1", False, id="no-number-is-coerced-to-a-string"),
        pytest.param(True, True, True, id="two-booleans"),
    ],
)
def test_field_equals_compares_byte_exactly_and_coerces_nothing(
    equals: FrozenJson, value: FrozenJson, *, holds: bool
) -> None:
    """*"No lane folds case, coerces a number to a string … or treats ``1`` as ``true``."*

    Python's own ``==`` says ``True == 1`` and ``1 == 1.0``, so the two rows that assert
    otherwise are the whole reason this comparison is not a bare ``==``.
    """
    predicate = StepVerification(kind=VerificationKind.FIELD_EQUALS, field="booking", equals=equals)

    assert verification_holds(predicate, {"booking": value}) is holds
