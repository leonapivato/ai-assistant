"""ADR-0265's intended-action contract: which values construct and which cannot.

The **type-level** half of §10's arms, and L1's alone. What a store does with a
minting or a plan is ``tests/planning/plan_store_contract.py``'s; the loop's
recording, ``serves`` resolution and action-label substitution are **L2's** (§9);
the planner seam's ``A`` block and its strict extraction are **L3's**. So arms
**1(b), 2, 3, 4 and 8** are not here and are not this lane's — each is stated over a
``PlannerOutput`` the loop recorded or a request the seam rendered, and asserting one
here would mean writing a second statement of the loop's substitution in test code and
then asserting the test against it, which certifies nothing about the system.

**The brief's ``actions`` projection is L2's too** (§9), so what is asserted of it here
is its **shape** — the field, its bound and ``BriefAction``'s containment — and that
``GoalBrief.of`` fills none of it.

What is here is **arm 7** whole, **arm 6**'s round trip and its export limb, and the
type-level half of **arm 1(a)** — that two intended actions of one goal are two
distinct identities a plan's two steps can name apart while their capability and
parameters are byte-identical. Arm 5 and the stored half of arm 1(a) are the
``PlanStore`` conformance suite's, because their subject is the store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_GOAL_EVIDENCE,
    MAX_INTENDED_ACTIONS,
    ActionPlan,
    EvidenceHistory,
    Goal,
    GoalBrief,
    GoalInterpretation,
    GoalStatus,
    Ground,
    IntendedAction,
    IntendedActionMinting,
    MemorySource,
    PlanExport,
    PlannerOutput,
    PlanStep,
    ProposedAction,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _goal(*, actions: tuple[IntendedAction, ...] = (), **revision: object) -> Goal:
    """A goal at revision 1, optionally holding intended actions and elements."""
    return Goal(
        id="g1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a room for the trip",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a room",
                recorded_at=_WHEN,
                **revision,  # type: ignore[arg-type]
            ),
        ),
        intended_actions=actions,
        provenance=Provenance(
            source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN
        ),
        created_at=_WHEN,
    )


def _action(action_id: str = "ia1", *, serves: tuple[str, ...] = ()) -> IntendedAction:
    """One intended action, with ``serves`` as a tuple of element ids."""
    return IntendedAction(id=action_id, intent="book the room", serves=serves)


# --- §10 arm 7: the reservation, and it is wider than the canonical labels ----


@pytest.mark.parametrize("label", ["A1", "A12", "A0", "A01", "A007"])
def test_an_action_whose_id_matches_the_action_label_grammar_is_refused(label: str) -> None:
    """§1, and it is what makes §4's store membership check **exact**.

    "``Identifier`` admits any non-blank encodable string, so without the rule an
    unsubstituted label could equal some action's id and pass §4's membership check
    **as a reference to a different action**, silently scoping an effect claim to the
    wrong act instead of refusing."

    **``A0``, ``A01`` and ``A007`` are here deliberately**: §4's resolution accepts none
    of them as a label, and the reservation is still wider than the canonical
    spellings, because "a faulty caller passing ``A01`` past the loop would meet a goal
    that could legitimately hold ``A01`` as an id". That is ADR-0253 §7's construction
    for ``D`` reused unaltered.
    """
    with pytest.raises(ValidationError, match="never an action label"):
        IntendedAction(id=label, intent="book the room")


@pytest.mark.parametrize("near", ["A", "A+1", "a1", "A 1", "A\u0661", "AA1", "A1x", "1A"])
def test_a_near_miss_of_the_grammar_is_a_perfectly_good_action_id(near: str) -> None:
    """§1's rule is the grammar and nothing wider.

    A string that is not ``A`` followed by **ASCII** digits and nothing else is an id
    like any other, and narrowing ``Identifier`` further would refuse ids
    ``orchestration`` is free to mint. ``A\u0661`` — an Arabic-Indic digit — is the
    non-ASCII case, named
    because a Unicode-``\\d``-based reservation would refuse it while every other
    assertion here still passed — and §4's resolution produces only ASCII digits, so a
    label the renderer could not have produced is not one this side has to keep an id
    away from.
    """
    assert IntendedAction(id=near, intent="book the room").id == near


def test_an_id_that_strips_to_a_label_is_refused_through_the_strip() -> None:
    """The reservation holds through ``Identifier``'s own normalisation.

    :data:`~ai_assistant.core.types.Identifier` "is a non-blank, **stripped**
    identifier", so ``"A1 "`` is stored as ``"A1"`` — and the disjointness §1 buys would
    be worth nothing if the refusal ran against the value as supplied rather than the
    value as kept. ``"A 1"``, whose space is *inside* the string, is not a label under
    §4's grammar and survives as an id, which is the boundary this pins from the other
    side.
    """
    with pytest.raises(ValidationError, match="never an action label"):
        IntendedAction(id="A1 ", intent="book the room")

    assert IntendedAction(id=" A 1 ", intent="book the room").id == "A 1"


def test_the_id_reservation_is_the_one_save_plan_reads_against() -> None:
    """§10 arm 7's last limb: "the same boundary is refused by ``save_plan``".

    The two halves cannot drift, because there is only one boundary: a step naming
    ``"A1"`` resolves against ``Goal.intended_actions``, and no member of that tuple can
    carry ``"A1"`` at all. What is asserted here is the half that makes the store's
    membership check exact; the store's own refusal is the conformance suite's.
    """
    goal = _goal(actions=(_action("ia1"), _action("ia2")))

    assert {action.id for action in goal.intended_actions} == {"ia1", "ia2"}
    with pytest.raises(ValidationError, match="never an action label"):
        IntendedAction(id="A1", intent="book the room")


def test_a_minting_carrying_no_action_is_not_constructible() -> None:
    """§10 arm 7: "an ``IntendedActionMinting`` carrying an empty ``actions`` is not
    constructible".

    A command that mints nothing is not a minting, and §2's empty
    ``PlannerOutput.actions`` "records none, raises nothing and re-plans nothing" — so
    a caller with nothing to record makes no call rather than an empty one.
    """
    with pytest.raises(ValidationError, match="at least one intended action"):
        IntendedActionMinting(goal_id="g1", actions=(), expected_version=0)


def test_a_minting_naming_one_id_twice_is_not_constructible() -> None:
    """§5: "a model validator refuses a command two of whose ``actions`` carry one
    ``id``", so §1's one-id-per-member invariant "cannot be breached *inside* a single
    append" — "a case the store's refusal of an id the goal **already holds** does not
    reach, because neither id is stored when the command is built".
    """
    with pytest.raises(ValidationError, match="twice"):
        IntendedActionMinting(
            goal_id="g1",
            actions=(_action("ia1"), _action("ia1", serves=("e1",))),
            expected_version=0,
        )


def test_a_proposed_action_states_an_intent_and_names_no_identifier() -> None:
    """§10 arm 7's tail: "nor is a ``ProposedAction`` carrying no ``intent``, nor one
    carrying an ``id`` of any spelling — that field being one ``extra="forbid"``
    refuses rather than one a planner may name" (§2).

    "A planner names no identifier and mints none, which is ADR-0228 §8's namer rule
    binding this field as it binds every other."
    """
    assert set(ProposedAction.model_fields) == {"intent", "serves"}
    assert ProposedAction(intent="book the room").serves == ()

    with pytest.raises(ValidationError):
        ProposedAction(intent="")
    with pytest.raises(ValidationError):
        ProposedAction(id="ia1", intent="book the room")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ProposedAction(intent="book the room", id="A1")  # type: ignore[call-arg]


def test_an_intended_action_carries_three_fields_and_no_fourth() -> None:
    """§1: "**It carries no fourth field**: no capability, no tool, no parameters, no
    step id, no plan id, no attempt, no instant, no status and no count."

    The containment is a property of the type: "an identity is a minted record and is
    never derived", and the record carries "no capability" because ADR-0253 §8 has
    already ruled that a plan's own spellings are not durable declarations.
    """
    assert set(IntendedAction.model_fields) == {"id", "intent", "serves"}
    for forbidden in ("capability", "parameters", "step_id", "plan_id", "status", "performed_at"):
        with pytest.raises(ValidationError):
            IntendedAction(id="ia1", intent="book it", **{forbidden: "x"})  # type: ignore[arg-type]


def test_the_bound_is_max_goal_evidences_figure_for_a_record_of_the_same_goal() -> None:
    """§1: 64, "``MAX_GOAL_EVIDENCE``'s figure, for a record of the same goal with the
    same durability".

    Read off the constant it is stated as rather than restated as a literal, so the two
    cannot drift silently — and asserted as a figure too, because "a knob that raises
    the ceiling is a knob that re-opens it" (ADR-0086 §1) and a bound nobody pins is a
    bound a lane can move without noticing.
    """
    assert MAX_INTENDED_ACTIONS == MAX_GOAL_EVIDENCE == 64


# --- §10 arm 1(a), the type-level half: two acts, one key -------------------


def test_two_intended_actions_of_one_goal_are_two_identities_a_plan_names_apart() -> None:
    """§10 arm 1(a), over the types: "two identical rooms are two intended actions".

    A plan whose two steps carry the **same** capability and byte-identical
    ``parameters`` but **different** ``intended_action`` values constructs, "so the
    triple §6's first clause requires is **distinct for the two steps** while the
    argument key is equal — which is the fact an at-most-once claim scoped to the goal
    alone cannot see". That the store **saves** such a plan is the conformance suite's
    half of this arm.
    """
    goal = _goal(actions=(_action("ia1"), _action("ia2")))
    parameters: Mapping[str, Any] = {"hotel": "the one by the station", "nights": 1}
    plan = ActionPlan(
        id="p1",
        goal_id="g1",
        steps=(
            PlanStep(
                id="s1",
                intent="book the first room",
                capability="book_room",
                parameters=parameters,
                intended_action="ia1",
            ),
            PlanStep(
                id="s2",
                intent="book the second room",
                capability="book_room",
                parameters=parameters,
                intended_action="ia2",
            ),
        ),
        created_at=_WHEN,
        targets_revision=1,
    )

    first, second = plan.steps
    assert (first.capability, first.parameters) == (second.capability, second.parameters)
    assert first.intended_action != second.intended_action
    assert {action.id for action in goal.intended_actions} == {"ia1", "ia2"}


def test_a_step_naming_no_intended_action_carries_none() -> None:
    """§4: "A read step, a composition step and every step of every plan written before
    this decision carry ``None``, and that is a conforming plan rather than a degraded
    one." **Whether an effect-bearing dispatch must name one is §6's**, and no clause
    of this decision refuses a step for naming none.
    """
    step = PlanStep(id="s1", intent="read the calendar", capability="read_calendar")

    assert step.intended_action is None


def test_two_intended_actions_of_one_goal_may_not_share_an_id() -> None:
    """§1's append-only rule, refused by the container because an action cannot see the
    tuple it sits in — ADR-0253 §1's own reason, and this corpus's standing shape for an
    identity inside a container.

    Two actions under one id leave §6's ``(goal, intended action, effect key)`` triple
    naming an act nobody can identify, which is what the whole decision exists to
    prevent.
    """
    with pytest.raises(ValidationError, match="share an id"):
        _goal(actions=(_action("ia1"), _action("ia1", serves=("e1",))))


# --- §10 arm 6: the record round-trips and the export closes ----------------


def test_a_goal_carrying_two_intended_actions_round_trips_through_its_own_dump() -> None:
    """§10 arm 6, and ADR-0249 §1's round-trip rule reaching one more field.

    A goal "round-trips through construction from its own dump", which under
    ``extra="forbid"`` is what a field that serialised but could not be constructed from
    would break.
    """
    goal = _goal(actions=(_action("ia1", serves=("e1",)), _action("ia2")))

    restored = Goal.model_validate(goal.model_dump())

    assert restored == goal
    assert restored.intended_actions[0].serves == ("e1",)
    assert restored.intended_actions[1].serves == ()


def test_the_export_carries_the_actions_inside_the_goal_and_gains_no_member() -> None:
    """§5: "``PlanExport`` gains no member and ``schema_version`` moves for the record's
    shape alone."

    "An ``IntendedAction`` rides **inside ``Goal``**, which ``PlanExport.goals`` already
    carries, so ADR-0014 §5's closure rule … is satisfied by construction and is
    **extended by nothing**."
    """
    goal = _goal(actions=(_action("ia1"), _action("ia2")))

    export = PlanExport(exported_at=_WHEN, goals=(goal,), evidence=(EvidenceHistory(goal_id="g1"),))
    restored = PlanExport.model_validate_json(export.model_dump_json())

    assert restored.schema_version == 16
    assert restored.goals[0].intended_actions == goal.intended_actions
    assert "intended_actions" not in set(PlanExport.model_fields)


def test_a_goal_written_before_this_decision_decodes_with_no_intended_actions() -> None:
    """§5: "a ``Goal`` written before this decision decodes with ``intended_actions``
    empty and a ``PlanStep`` with ``intended_action`` absent".

    **No lane invents one for such a row**: "an act nothing declared is an act no claim
    was ever scoped to, and minting one would state a history the row does not hold."
    """
    stored = _goal().model_dump()
    del stored["intended_actions"]

    assert Goal.model_validate(stored).intended_actions == ()

    step = PlanStep(id="s1", intent="book it", capability="book_room").model_dump()
    del step["intended_action"]

    assert PlanStep.model_validate(step).intended_action is None


# --- §4: what the brief renders, and what it does not -----------------------


def test_the_projection_renders_no_action_and_filling_it_is_l2s() -> None:
    """§9 puts "the ``GoalBrief.actions`` projection with its live-link rendering" in
    "L2 — the loop, in ``orchestration`` alone", and names L1's list without it.

    So what L1 lands is the **shape** — the field, its bound and ``BriefAction``'s
    containment — and :meth:`GoalBrief.of` fills none of it, exactly as it fills no
    ``open_questions``. An action-free brief is well-formed rather than degraded
    (§1: "the goal's opening write mints none"), which is ADR-0249 §9's own posture
    toward an element-free one, so nothing here is a degraded rendering waiting to be
    repaired — it is the rendering until L2 lands.
    """
    intending = _goal(actions=(_action("ia1", serves=("e1",)),))

    brief = GoalBrief.of(intending)

    assert brief.actions == ()
    assert brief.status is GoalStatus.ACTIVE
    assert intending.intended_actions[0].serves == ("e1",), "and the record is untouched"


def test_a_planner_output_proposing_actions_carries_them_beside_the_plan() -> None:
    """§2: ``actions`` "rides on ``PlannerOutput`` and never inside
    ``ProposedUnderstanding``", because ADR-0249 §7 makes omission removal there and
    "an intended action must survive every revision that does not mention it".

    So minting is **independent of revising**: this envelope proposes two actions and no
    understanding at all, which is a well-formed output rather than a degraded one.
    """
    output = PlannerOutput(
        plan=ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_WHEN),
        actions=(ProposedAction(intent="book the first room", serves=("C1",)),),
    )

    assert output.understanding is None
    assert output.actions[0].serves == ("C1",)
    assert "actions" not in set(type(output.plan).model_fields)
