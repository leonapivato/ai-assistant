"""ADR-0253's plan-shape contract: which plans construct and which cannot.

The **type-level** half of §14's arms. What a store does with a plan is
``tests/planning/plan_store_contract.py``'s; the planner seam's extraction and the
loop's condition-label substitution are **L2's** (§12); and evaluating a condition,
resolving a reference, performing an interpretation and dispatching anything are
**A7's** — §12 rules in as many words that "no lane of this decision performs an
interpretation call, evaluates a condition, resolves a reference … dispatches a step
or writes a ``SkipReason``".

So §14's arms **25-35** are **not** here and are not this lane's. Each is stated over
eligibility, dependency disposal, reference resolution or a performed interpretation,
and asserting one here would mean writing a second statement of ADR-0252 §6's four
tests in test code and then asserting the test against it — which certifies nothing
about the system and would be the "two carriers for one fact" defect ADR-0251 §3 names,
arriving through a fixture. They are recorded against A7 on the PR rather than written
badly here. **Arms 15-24 are L2's**, but for arm 24, whose subject is the store: §10
puts ``save_plan``'s new conjunct in the contract, so the ``PlanStore`` conformance
suite carries it.

What is here is everything the types themselves decide.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_INTERPRETATION_STEPS,
    ActionPlan,
    EvidenceApplicability,
    EvidenceBasis,
    EvidenceStanding,
    GoalElement,
    GoalEvidence,
    GoalInterpretation,
    Ground,
    InterpretationVerdict,
    InterpretedOutput,
    PlanInterpretation,
    PlanStep,
    ReadKind,
    ReadOutcomeKind,
    ResultReference,
    StepCondition,
    StepOutputRef,
    StepVerification,
    TimeWindow,
    VerificationKind,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _step(step_id: str, **fields: object) -> PlanStep:
    """One step, with only what an arm cares about spelled out."""
    fields.setdefault("capability", "cap")
    return PlanStep(id=step_id, intent="do it", **fields)  # type: ignore[arg-type]


def _plan(**fields: object) -> ActionPlan:
    """One plan under goal ``g1``, with its steps supplied by the arm."""
    return ActionPlan(id="p1", goal_id="g1", created_at=_WHEN, **fields)  # type: ignore[arg-type]


def _settles(interpretation_id: str, element: str, **fields: object) -> PlanInterpretation:
    """One interpretation of ``element``, over whichever input the arm names."""
    return PlanInterpretation(id=interpretation_id, settles=element, **fields)  # type: ignore[arg-type]


def _revision(**tuples: object) -> GoalInterpretation:
    """One interpretation revision, with whichever element tuples an arm supplies."""
    return GoalInterpretation(
        revision=1,
        outcome="book a campsite",
        outcome_ground=Ground.INFERRED,
        recorded_at=_WHEN,
        **tuples,  # type: ignore[arg-type]
    )


_QUALIFIES = StepCondition(
    about="e1", basis=EvidenceBasis.INTERPRETATION, requires=InterpretationVerdict.QUALIFIES
)


# --- §14 arm 1: depends_on points strictly backwards ------------------------


def test_a_step_declaring_nothing_is_the_step_this_system_already_wrote() -> None:
    """§10: "every new field is defaulted, so every existing constructor call still
    builds a conforming value", and §1's empty ``depends_on`` "means the step waits on
    no other step".
    """
    step = _step("s1")
    assert (step.depends_on, step.resolves, step.when) == ((), (), ())
    assert (step.verifies, step.evidence_recency) == (None, None)
    assert _plan(steps=(step,)).interpretations == ()


def test_a_dependency_naming_a_later_step_is_not_constructible() -> None:
    """§1's third refusal, and the one that makes acyclicity a property of the type.

    "A tuple in which every reference points strictly earlier admits no cycle at all:
    any cycle needs at least one edge pointing forward or at itself, and both are
    refused one member at a time by a comparison of two positions." So the arm records
    that a cycle has no other spelling and is **unconstructible** rather than detected
    — there is no traversal here to get wrong.
    """
    with pytest.raises(ValidationError, match="strictly earlier"):
        _plan(steps=(_step("s1", depends_on=("s2",)), _step("s2")))


def test_a_dependency_naming_the_declaring_step_is_not_constructible() -> None:
    """§1's second refusal: a cycle of one, reported as its own state."""
    with pytest.raises(ValidationError, match="depends on itself"):
        _plan(steps=(_step("s1", depends_on=("s1",)),))


def test_a_dependency_naming_a_step_the_plan_does_not_carry_is_refused() -> None:
    """§1's first refusal: "a member naming a step the plan does not carry"."""
    with pytest.raises(ValidationError, match="not a step of this plan"):
        _plan(steps=(_step("s1"), _step("s2", depends_on=("sX",))))


def test_a_dependency_repeated_within_one_tuple_is_refused() -> None:
    """§1's fourth refusal: "repeating another member of the same tuple"."""
    with pytest.raises(ValidationError, match="twice in depends_on"):
        _plan(steps=(_step("s1"), _step("s2", depends_on=("s1", "s1"))))


def test_two_independent_steps_and_one_that_waits_on_both_construct() -> None:
    """§1: the shape is expressible "exactly as it is in any topological order".

    The positive half of the four refusals above, and the one that records that
    backwards-only costs nothing in expressiveness — which is §1's own answer to why
    forward references buy nothing a plan needs.
    """
    plan = _plan(steps=(_step("s1"), _step("s2"), _step("s3", depends_on=("s1", "s2"))))
    assert plan.steps[2].depends_on == ("s1", "s2")


# --- §14 arm 2: a reference is a dependency that fills a free argument -------


def test_a_reference_outside_the_declaring_steps_depends_on_is_refused() -> None:
    """§6: "a reference **is** a dependency and is not a second way of saying so"."""
    reference = ResultReference(parameter="ref", source=StepOutputRef(step="s1", field="booking"))
    with pytest.raises(ValidationError, match="not in its depends_on"):
        _plan(steps=(_step("s1"), _step("s2", resolves=(reference,))))
    ordered = _plan(steps=(_step("s1"), _step("s2", depends_on=("s1",), resolves=(reference,))))
    assert ordered.steps[1].resolves[0].source.field == "booking"


def test_a_reference_competing_with_a_literal_parameter_is_refused() -> None:
    """§6: "there is never a literal and a reference competing for one argument, so no
    precedence rule exists to get wrong".
    """
    reference = ResultReference(parameter="ref", source=StepOutputRef(step="s1"))
    with pytest.raises(ValidationError, match="already carries as a literal"):
        _plan(
            steps=(
                _step("s1"),
                _step("s2", depends_on=("s1",), parameters={"ref": 1}, resolves=(reference,)),
            )
        )


def test_two_references_of_one_step_never_name_one_parameter() -> None:
    """§6's third refusal."""
    first = ResultReference(parameter="ref", source=StepOutputRef(step="s1", field="a"))
    second = ResultReference(parameter="ref", source=StepOutputRef(step="s1", field="b"))
    with pytest.raises(ValidationError, match="resolves ref twice"):
        _plan(steps=(_step("s1"), _step("s2", depends_on=("s1",), resolves=(first, second))))


# --- §14 arm 3: StepVerification admits three shapes ------------------------


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (VerificationKind.OUTPUT_PRESENT, {}),
        (VerificationKind.FIELD_PRESENT, {"field": "reference"}),
        (VerificationKind.FIELD_EQUALS, {"field": "status", "equals": "confirmed"}),
    ],
)
def test_the_three_verification_shapes_construct(
    kind: VerificationKind, fields: dict[str, object]
) -> None:
    """§4's three shapes, each with exactly the arguments its kind takes."""
    assert StepVerification.model_validate({"kind": kind, **fields}).kind is kind


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (VerificationKind.OUTPUT_PRESENT, {"field": "reference"}),
        (VerificationKind.OUTPUT_PRESENT, {"equals": 1}),
        (VerificationKind.FIELD_PRESENT, {}),
        (VerificationKind.FIELD_PRESENT, {"field": "x", "equals": 1}),
        (VerificationKind.FIELD_EQUALS, {"equals": 1}),
        (VerificationKind.FIELD_EQUALS, {"field": "x"}),
    ],
)
def test_every_other_verification_shape_is_refused(
    kind: VerificationKind, fields: dict[str, object]
) -> None:
    """§4: "the kind and the arguments it takes travel together or the value does not
    construct", named by §14 arm 3 in both directions — ``FIELD_EQUALS`` with no
    ``field`` and ``OUTPUT_PRESENT`` with one.
    """
    with pytest.raises(ValidationError, match="ADR-0253 §4"):
        StepVerification.model_validate({"kind": kind, **fields})


def test_a_predicate_that_a_present_field_equals_null_is_not_constructible() -> None:
    """§4: an ``equals`` of JSON ``null`` "contradicts ``FIELD_PRESENT``'s own
    requirement and is refused" — and the absence is its one spelling, so the two
    states are one rather than two that could disagree.
    """
    with pytest.raises(ValidationError, match="ADR-0253 §4"):
        StepVerification(kind=VerificationKind.FIELD_EQUALS, field="x", equals=None)


def test_the_verification_vocabulary_is_closed_at_three_and_spelled_by_name() -> None:
    """§4: "a ``StrEnum`` valued by lower-cased member name and closed at exactly three"."""
    assert [member.value for member in VerificationKind] == [
        "output_present",
        "field_present",
        "field_equals",
    ]


# --- §14 arm 4: StepCondition's two shapes ----------------------------------


def test_a_condition_with_no_basis_is_not_constructible() -> None:
    """§5: ``basis`` is **required**, on ADR-0228 §2(a)'s fail-closed rule."""
    with pytest.raises(ValidationError):
        StepCondition(about="e1")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "fields",
    [
        {"basis": EvidenceBasis.INTERPRETATION},
        {"basis": EvidenceBasis.INTERPRETATION, "read_kind": ReadKind.SIGHTED_QUERY},
        {
            "basis": EvidenceBasis.INTERPRETATION,
            "requires": InterpretationVerdict.QUALIFIES,
            "read_kind": ReadKind.SIGHTED_QUERY,
        },
        {"basis": EvidenceBasis.READ_OUTCOME, "requires": InterpretationVerdict.QUALIFIES},
    ],
)
def test_every_condition_shape_the_two_bases_do_not_admit_is_refused(
    fields: dict[str, object],
) -> None:
    """§5's model validator: "a condition of the wrong shape is **not constructible**"."""
    with pytest.raises(ValidationError, match="ADR-0253 §5"):
        StepCondition.model_validate({"about": "e1", **fields})


def test_a_condition_may_never_require_the_does_not_settle_member() -> None:
    """§5, and ADR-0252 §6 test 2 behind it.

    A row carrying ``INCONCLUSIVE`` "satisfies nothing, refreshes nothing and conflicts
    with nothing", so a condition requiring it could be satisfied by no row that exists
    — a step that can never be dispatched, declared by a planner that had no way to
    know it. That is §5's own reason for refusing a required ``source`` too.
    """
    with pytest.raises(ValidationError, match="does-not-settle"):
        StepCondition(
            about="e1",
            basis=EvidenceBasis.INTERPRETATION,
            requires=InterpretationVerdict.INCONCLUSIVE,
        )


def test_the_two_admitted_condition_shapes_construct() -> None:
    """§5's positive half: the ``INTERPRETATION`` and ``READ_OUTCOME`` shapes.

    ``read_kind`` is admitted on the second and optional there — §5 admits it "because
    it is a member of a closed vocabulary present on every ``READ_OUTCOME`` row" — and
    a condition declaring none imposes no requirement of that axis.
    """
    assert _QUALIFIES.read_kind is None
    read = StepCondition(
        about="e1", basis=EvidenceBasis.READ_OUTCOME, read_kind=ReadKind.STRUCTURED_READ
    )
    assert (read.requires, read.read_kind) == (None, ReadKind.STRUCTURED_READ)
    assert StepCondition(about="e1", basis=EvidenceBasis.READ_OUTCOME).read_kind is None


def test_a_condition_carries_no_applicability_and_no_source_of_its_own() -> None:
    """§5: "one field carries the declaration and the coverage operand".

    A condition carrying an applicability beside a declaration naming an element would
    be ADR-0251 §3's "two carriers for one fact", and would leave ADR-0252 §9's
    invalidation predicate without operands, "because §9 compares what two
    **revisions** require and a value on a step is not on a revision". ``source`` is
    refused for its own reason (§5): ADR-0252 §1 rules that field absent on every row
    this system's producers write, so a condition requiring one could be satisfied by
    no row that exists.
    """
    assert set(StepCondition.model_fields) == {"about", "basis", "requires", "read_kind"}
    for absent in ("applicability", "source", "window", "supported", "recency"):
        with pytest.raises(ValidationError):
            StepCondition.model_validate(
                {"about": "e1", "basis": EvidenceBasis.READ_OUTCOME, absent: "x"}
            )


def test_recency_lives_on_the_step_and_is_strictly_positive() -> None:
    """§5: "recency is the plan's declaration and never the evidence's property. The
    figure lives on the step". A step declaring none imposes none (ADR-0252 §6).
    """
    assert _step("s1", evidence_recency=timedelta(minutes=15)).evidence_recency == timedelta(
        minutes=15
    )
    for refused in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValidationError):
            _step("s1", evidence_recency=refused)


# --- §14 arm 5: the interpretations of one plan -----------------------------


def test_a_plan_declaring_four_interpretations_constructs_and_five_is_refused() -> None:
    """§8's bound, "refused at construction rather than truncated".

    Dropping one "would silently delete a branch of a plan the rest of which is stated
    over it", which is §1's argument for refusing a malformed dependency arriving at a
    second field. The figure is :data:`MAX_INTERPRETATION_STEPS` and is read off the
    constant rather than restated, so a later change to it cannot leave this arm
    asserting a number nothing else believes.
    """
    four = tuple(_settles(f"i{n}", f"e{n}", record="m1") for n in range(MAX_INTERPRETATION_STEPS))
    assert len(_plan(steps=(_step("s1"),), interpretations=four).interpretations) == (
        MAX_INTERPRETATION_STEPS
    )
    over = (*four, _settles("iN", "eN", record="m1"))
    with pytest.raises(ValidationError, match="refused rather than truncated"):
        _plan(steps=(_step("s1"),), interpretations=over)


@pytest.mark.parametrize("shared", ["id", "settles"])
def test_two_interpretations_sharing_an_id_or_a_settles_are_refused(shared: str) -> None:
    """§8: "``ActionPlan`` refuses two interpretations sharing an ``id`` and two sharing
    a ``settles``, exactly as it already refuses two steps sharing an id".
    """
    second = ("i1", "e2") if shared == "id" else ("i2", "e1")
    with pytest.raises(ValidationError, match=f"share a {shared}"):
        _plan(
            steps=(_step("s1"),),
            interpretations=(_settles("i1", "e1", record="m1"), _settles(*second, record="m1")),
        )


@pytest.mark.parametrize(
    "inputs", [{}, {"record": "m1", "reads": StepOutputRef(step="s1")}], ids=["neither", "both"]
)
def test_an_interpretation_carries_exactly_one_input(inputs: dict[str, object]) -> None:
    """§8: "a model validator requires exactly one of ``record`` and ``reads``".

    Whether one may ever take more than one input is **refused here and not deferred**
    (§11): ADR-0252 §1 admits "exactly one member of ``records``", §8 gives the second
    shape exactly one ``interpreted_output``, and widening either is a decision of its
    own.
    """
    with pytest.raises(ValidationError, match="exactly one of record and reads"):
        PlanInterpretation.model_validate({"id": "i1", "settles": "e1", **inputs})


def test_an_interpretation_whose_reads_step_is_not_in_the_plan_is_refused() -> None:
    """§8: "it also refuses an interpretation whose ``reads.step`` is not a step of this
    plan".
    """
    with pytest.raises(ValidationError, match="not a step of this plan"):
        _plan(
            steps=(_step("s1"),),
            interpretations=(_settles("i1", "e1", reads=StepOutputRef(step="sX")),),
        )


def test_an_interpretation_carries_no_depends_on_when_or_verifies() -> None:
    """§8: "``reads.step`` is the interpretation's whole dependency and it carries no
    ``depends_on`` field", and it "carries no ``when`` and no ``verifies``" — "a second
    carrier for the same fact is the defect ADR-0251 §3 names".
    """
    assert set(PlanInterpretation.model_fields) == {"id", "settles", "record", "reads"}


# --- §14 arm 6: the order is fixed at construction ---------------------------


@pytest.mark.parametrize("producer_at", [0, 1], ids=["at-the-producer", "before-the-producer"])
def test_a_conditioned_step_at_or_before_its_producer_is_refused(producer_at: int) -> None:
    """§8: the ordering rule, in both directions §14 arm 6 names.

    "Together with §1's backwards-only rule this keeps the whole graph acyclic by
    position, so the driver A7 lands walks it in one pass and no cycle has a spelling."
    """
    steps = (_step("s1", when=(_QUALIFIES,)), _step("s2"))
    producer = StepOutputRef(step=steps[producer_at].id, field="summary")
    with pytest.raises(ValidationError, match="strictly after"):
        _plan(steps=steps, interpretations=(_settles("i1", "e1", reads=producer),))


def test_the_same_plan_with_the_steps_in_the_other_order_is_accepted() -> None:
    """§14 arm 6's second half — the dynamic plan of §8's worked example.

    *Refresh the forecast, read what came back, and book only if it qualifies* is one
    plan with one step, one interpretation and one conditioned step. That it
    **constructs** is this lane's half of arm 25; disposing of its steps, performing the
    interpretation and evaluating the condition are A7's (§12).
    """
    plan = _plan(
        steps=(
            _step("s1", capability="refresh_forecast"),
            _step("s2", capability="book_campsite", when=(_QUALIFIES,)),
        ),
        interpretations=(_settles("i1", "e1", reads=StepOutputRef(step="s1", field="summary")),),
    )
    assert plan.interpretations[0].reads == StepOutputRef(step="s1", field="summary")
    assert plan.steps[1].when[0].requires is InterpretationVerdict.QUALIFIES


def test_an_interpretation_over_a_record_imposes_no_ordering() -> None:
    """§8: an interpretation over a ``record`` "waits on nothing and is performed before
    the plan's first step is dispatched", so the ordering rule reaches only the
    output-backed shape.
    """
    plan = _plan(
        steps=(_step("s1", when=(_QUALIFIES,)),),
        interpretations=(_settles("i1", "e1", record="m1"),),
    )
    assert plan.interpretations[0].record == "m1"


def test_the_ordering_rule_reads_the_condition_about_the_settled_element_alone() -> None:
    """§8: the rule is over a condition "about an element that an interpretation of this
    plan settles **from a step's output**", and over nothing else.

    A condition about a *different* element, and one on the ``READ_OUTCOME`` basis about
    the settled element, are each unaffected — which matters because §5 makes ``about``
    required on both bases and only one of them reads an interpretation's verdict.
    """
    other = StepCondition(
        about="e2", basis=EvidenceBasis.INTERPRETATION, requires=InterpretationVerdict.QUALIFIES
    )
    read = StepCondition(about="e1", basis=EvidenceBasis.READ_OUTCOME)
    for condition in (other, read):
        plan = _plan(
            steps=(_step("s1", when=(condition,)), _step("s2")),
            interpretations=(_settles("i1", "e1", reads=StepOutputRef(step="s2")),),
        )
        assert plan.steps[0].when[0] is condition


# --- §14 arm 7: an element id is never a condition label ---------------------


@pytest.mark.parametrize("label", ["D1", "D2", "D0", "D007", "D12345"])
def test_an_element_whose_id_matches_the_condition_label_grammar_is_refused(label: str) -> None:
    """§7, and it is what makes §9's store refusal **exact**.

    "``Identifier`` admits any non-blank encodable string, so without this rule an
    unsubstituted label could equal some element's id and pass §9's store membership
    check **as a reference to a different element**, silently changing what a step
    requires instead of refusing." ``D0`` and ``D007`` are here deliberately: the
    renderer produces neither, and the guarantee the rule buys is disjointness from
    every string a plan could still be carrying, not from the resolvable ones alone.
    """
    with pytest.raises(ValidationError, match="never a condition label"):
        GoalElement(id=label, text="the weather permits it", ground=Ground.INFERRED)


@pytest.mark.parametrize("near", ["D", "DD1", "d1", "D1x", "1D", "E1", "D 1", "elem-D1"])
def test_a_near_miss_of_the_grammar_is_a_perfectly_good_element_id(near: str) -> None:
    """§7's rule is the grammar and nothing wider: a string that is not ``D`` followed
    by decimal digits and nothing else is an id like any other, and narrowing
    ``Identifier`` further would refuse ids ``orchestration`` is free to mint.
    """
    assert GoalElement(id=near, text="it holds", ground=Ground.INFERRED).id == near


def test_an_element_carries_an_identity_and_an_applicability_and_both_default_absent() -> None:
    """§7, and §10's "no migration and no stored-record version moves for this".

    An element carrying no ``id`` "is one recorded **before** this decision, and it
    decodes"; it is "named by no ``StepCondition`` and settled by no interpretation",
    which is the fail-closed direction and ADR-0249 §8's own construction for
    ``targets_revision``.
    """
    bare = GoalElement(text="it holds", ground=Ground.INFERRED)
    assert (bare.id, bare.applicability) == (None, None)
    sunday = EvidenceApplicability(window=TimeWindow(start=_WHEN, end=_WHEN + timedelta(days=1)))
    named = GoalElement(id="e1", text="it holds", ground=Ground.INFERRED, applicability=sunday)
    assert (named.id, named.applicability) == ("e1", sunday)


# --- §7: an element's identity, inside the revision that holds it -----------


def test_two_elements_of_one_revision_may_not_share_an_id() -> None:
    """§7's identity, refused by the container because an element cannot see its tuple.

    This corpus's standing shape for an identity inside a container, and ADR-0253 §8
    states it three times over for one plan: "``ActionPlan`` refuses two interpretations
    sharing an ``id`` and two sharing a ``settles``, exactly as it already refuses two
    steps sharing an id". Two elements under one id leave a ``StepCondition.about``, a
    ``PlanInterpretation.settles`` and a ``GoalEvidence.declaration`` each naming a
    proposition nobody can identify — and ADR-0252 §8 limb 3's
    ``L.declaration == E.declaration`` equating two readings of two propositions, which
    is what §7 of that decision exists to prevent.

    **One id space across the three tuples**, because the id is the durable name rather
    than a position and a ``declaration`` carries no tuple. §9's ``C``/``S``/``D``
    labels are per tuple and are a different space: minted per call, never persisted.
    """
    saturday = EvidenceApplicability(window=TimeWindow(start=_WHEN, end=_WHEN + timedelta(days=1)))
    sunday = EvidenceApplicability(
        window=TimeWindow(start=_WHEN + timedelta(days=1), end=_WHEN + timedelta(days=2))
    )
    first = GoalElement(id="e1", text="the weather permits it", ground=Ground.INFERRED)

    with pytest.raises(ValidationError, match="share an id"):
        _revision(
            conditions=(
                first.model_copy(update={"applicability": saturday}),
                first.model_copy(update={"applicability": sunday}),
            )
        )

    with pytest.raises(ValidationError, match="share an id"):
        _revision(constraints=(first,), conditions=(first,))

    distinct = _revision(
        constraints=(GoalElement(id="e0", text="under budget", ground=Ground.INFERRED),),
        conditions=(first,),
    )
    assert (distinct.constraints[0].id, distinct.conditions[0].id) == ("e0", "e1")


def test_elements_carrying_no_id_do_not_collide_with_each_other() -> None:
    """§7: ``None`` is the one value a row written before this decision carries.

    "An element carrying no ``id`` is one recorded **before** this decision … and it
    decodes." A revision migrated from such a row holds several, every one of them
    named by nothing, so refusing it for holding two would refuse rows already on disk
    — the opposite of §10's "no migration and no stored-record version moves for this".
    """
    bare = GoalElement(text="it holds", ground=Ground.INFERRED)
    revision = _revision(conditions=(bare, bare.model_copy(update={"text": "and so does this"})))
    assert [element.id for element in revision.conditions] == [None, None]


# --- §14 arm 12: an element round-trips its identity ------------------------


def test_an_element_round_trips_its_id_and_its_applicability() -> None:
    """§14 arm 12's first half. The retained/restated halves are the loop's (L2)."""
    sunday = EvidenceApplicability(topics=("weather",))
    element = GoalElement(id="e1", text="it holds", ground=Ground.INFERRED, applicability=sunday)
    assert GoalElement.model_validate(element.model_dump()) == element


# --- §14 arm 8: GoalEvidence admits both INTERPRETATION shapes ---------------


def _row(**fields: object) -> GoalEvidence:
    """One ``INTERPRETATION`` row, with the arm supplying the input half."""
    base: dict[str, object] = {
        "id": "ev1",
        "goal_id": "g1",
        "attempt_id": "a1",
        "basis": EvidenceBasis.INTERPRETATION,
        "declaration": "e1",
        "supported": (EvidenceApplicability(topics=("weather",)),),
        "supported_elided": 0,
        "read_at": _WHEN,
        "returned": 0,
        "admitted": 0,
        "verdict": InterpretationVerdict.QUALIFIES.value,
        "standing": EvidenceStanding.STANDING,
    }
    return GoalEvidence.model_validate(base | fields)


_OUTPUT = InterpretedOutput(execution_id="x1", step_id="s1", field="summary")


def test_both_interpretation_shapes_construct_and_neither_carries_a_count() -> None:
    """§8's second shape beside ADR-0252 §1's first, and ``returned``/``admitted`` 0 on
    both — "the call's whole input is one record, it reads no source and admits
    nothing".
    """
    records_backed = _row(records=("m1",))
    output_backed = _row(interpreted_output=_OUTPUT)
    assert (records_backed.records, records_backed.interpreted_output) == (("m1",), None)
    assert (output_backed.records, output_backed.interpreted_output) == ((), _OUTPUT)
    for row in (records_backed, output_backed):
        assert (row.returned, row.admitted) == (0, 0)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"records": ("m1",), "interpreted_output": _OUTPUT},
        {"records": ("m1", "m2")},
        {"records": ("m1",), "returned": 1},
        {"interpreted_output": _OUTPUT, "admitted": 1},
    ],
    ids=["neither", "both", "two-records", "a-count", "a-count-on-the-output-shape"],
)
def test_no_third_interpretation_shape_constructs(fields: dict[str, object]) -> None:
    """§8: "such a row carries **exactly one** of one member of ``records`` and an
    ``interpreted_output``, with ``records`` empty in the second and ``returned`` and
    ``admitted`` ``0`` in both".
    """
    with pytest.raises(ValidationError):
        _row(**fields)


@pytest.mark.parametrize(
    "verdict",
    ["free-form prose about what the record said", "", "QUALIFIES", "qualifie", "empty"],
    ids=["prose", "blank", "the-member-name-not-its-value", "a-near-miss", "the-other-vocabulary"],
)
def test_an_interpretation_rows_verdict_is_one_of_this_vocabularys_three(verdict: str) -> None:
    """§8 closes what ADR-0252 §5 could only half-check, and this is the closing.

    That section left the members "the one the interpretation step declares", "A5's and
    A7's to fix", so its validator could assert only that an interpretation verdict is
    **not** a ``ReadOutcomeKind``. §8 fixes them — "there is **no per-declaration
    vocabulary**: every interpretation row's ``verdict`` is a member of
    ``InterpretationVerdict``" — so the check is membership and the field stops
    admitting any sentence a model wrote on this basis.

    A vocabulary a model authored could not be compared, retained or audited: members
    invented per plan would be unprovenanced strings in a durable row, and two plans
    about one proposition would almost never agree on a spelling, so ADR-0252 §8's
    refresh could never hold.
    """
    for member in InterpretationVerdict:
        assert _row(records=("m1",), verdict=member.value).verdict == member.value

    with pytest.raises(ValidationError, match="InterpretationVerdict's three"):
        _row(records=("m1",), verdict=verdict)


def test_a_read_outcome_row_carries_no_interpreted_output() -> None:
    """§8's shapes are the ``INTERPRETATION`` limb's and reach no other basis.

    ADR-0252 §3's two sources are what ``basis`` exists to say, and "neither rule
    reaches the other's rows".
    """
    with pytest.raises(ValidationError, match="no interpreted_output"):
        GoalEvidence(
            id="ev1",
            goal_id="g1",
            attempt_id="a1",
            basis=EvidenceBasis.READ_OUTCOME,
            read_kind=ReadKind.WEB_SEARCH,
            supported_elided=0,
            read_at=_WHEN,
            returned=1,
            admitted=1,
            verdict=ReadOutcomeKind.RETURNED_RECORDS.value,
            standing=EvidenceStanding.STANDING,
            interpreted_output=_OUTPUT,
        )


def test_an_output_backed_row_names_the_execution_and_derives_the_plan() -> None:
    """§8: "the reference names the *execution* and not the plan, because one plan has
    many" — ``(plan_id, step_id)`` "names a *decision* and not a *value*". The plan is
    derived through ``ExecutionState.plan_id`` and never copied, "because a second
    carrier for the same fact is what ADR-0251 §3 calls the defect".
    """
    assert set(InterpretedOutput.model_fields) == {"execution_id", "step_id", "field"}
    with pytest.raises(ValidationError):
        InterpretedOutput(execution_id="x1", step_id="s1", plan_id="p1")  # type: ignore[call-arg]


# --- §14 arm 10 (the shape half): the two instants of an output-backed row ---


def test_an_output_backed_rows_instants_are_the_producing_steps_and_not_the_call() -> None:
    """§8's two instants, as far as the type decides them.

    "Its ``read_at`` is the producing step's ``finished_at`` … and never the
    interpretation call that read it. Its ``as_of`` is absent": a ``StepExecution``
    carries no declared source instant, so there is none to carry. Taking the
    interpretation call's own clock "would let a delayed reading rejuvenate a stale
    one", passing a recency requirement it should fail and superseding a genuinely
    newer reading under ADR-0252 §8 limb 6.

    **An ``as_of`` is refused outright rather than left to the composer**, because the
    absence is the whole of the protection: an output-backed row carrying one has an
    effective instant that is not the producing step's, which is exactly the state the
    two paragraphs above say must not exist. The type can decide it — the field is on
    the row — where the ``read_at == finished_at`` equality it cannot, holding no
    execution to compare against.

    **That equality is asserted by the lane that computes it.** Composing the row, and
    evaluating ADR-0252 §6 test 4 and §8's limbs over it, are A7's (§12), so arm 10's
    paired half is recorded against A7 rather than restated here over a second
    implementation of those rules; what this arm holds is that the row's effective
    instant **cannot** be the interpretation's.
    """
    finished_at = _WHEN
    interpreted_at = _WHEN + timedelta(hours=2)
    row = _row(interpreted_output=_OUTPUT, read_at=finished_at)
    assert (row.read_at, row.as_of) == (finished_at, None)
    assert (row.as_of or row.read_at) < interpreted_at

    with pytest.raises(ValidationError, match="carries no as_of"):
        _row(interpreted_output=_OUTPUT, read_at=finished_at, as_of=interpreted_at)

    # A records-backed row is untouched: its input is a MemoryRecord, which may well
    # carry an instant its source declared (ADR-0252 §4).
    assert _row(records=("m1",), read_at=finished_at, as_of=interpreted_at).as_of == (
        interpreted_at
    )


# --- §14 arm 11: the two verdict vocabularies are disjoint ------------------


def test_the_interpretation_vocabulary_is_closed_at_three_and_spelled_by_name() -> None:
    """§8: "a ``StrEnum`` valued by lower-cased member name and closed at exactly three
    members", with ``INCONCLUSIVE`` as ADR-0252 §5's does-not-settle member.
    """
    assert [member.value for member in InterpretationVerdict] == [
        "qualifies",
        "does_not_qualify",
        "inconclusive",
    ]


@pytest.mark.parametrize("verdict", list(InterpretationVerdict))
@pytest.mark.parametrize("kind", list(ReadOutcomeKind))
def test_the_two_verdict_vocabularies_are_disjoint_in_their_values(
    verdict: InterpretationVerdict, kind: ReadOutcomeKind
) -> None:
    """§8, and ADR-0252 §5's constraint "on the **later** vocabulary, which is the one
    not yet minted".

    A digest carries ``verdict`` and **not** ``basis``, so "a planner told ``'empty'``
    without being told of what would be told nothing". Parameterized over **both**
    vocabularies rather than asserting one intersection, so a later member of either
    cannot silently collide — which is §14 arm 11 in the shape it asks for.
    """
    assert verdict.value != kind.value
