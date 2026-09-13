"""ADR-0253 §9 at the loop: the condition label becomes an element id, or the plan is refused.

**"The loop resolves the label, once, and the planner never does."** §9 gives the loop
each :attr:`~ai_assistant.core.types.StepCondition.about` and each
:attr:`~ai_assistant.core.types.PlanInterpretation.settles` for its own, taken once per
plan, *"after this same call's ``understanding`` — if any — has been recorded and its
element ids minted, and **after** ADR-0249 §8's ``targets_revision`` stamp, and before
any other component observes the plan"*. What lives here is §14's L2 loop-side arms — 20,
21, 22, 23 — plus one arm per way a label resolves to nothing, and §12's pin that a plan
declaring **none** of the new keys is the value the planner returned.

**Two altitudes, because §9 states two facts.** The first section drives
:func:`~ai_assistant.orchestration.interpretation.substituted_plan` directly, which is
the only way to reach the *minted-record* refusal (#2345) without standing a search
servicing up. The second drives whole turns through the production
:class:`~ai_assistant.orchestration.loop.LearningLoop`, because §9's clause about *which
sequence is in force* is a fact about the call rather than about the function — arms 21
and 22 differ in nothing but whether the envelope carried an understanding.

The element-minting half of ADR-0253 §7 is ``test_interpretation.py``; the store's own
refusal of an unsubstituted label is L1's conformance suite; the round trip through a
real ``PlanStore`` is ``test_engine_plan_labels.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from test_loop_reads import _NOW, _belief, _bounded, _hop, _loop
from test_loop_revision import _seeded

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    EvidenceBasis,
    Goal,
    GoalElement,
    GoalInterpretation,
    Ground,
    InterpretationVerdict,
    MemorySource,
    PlanInterpretation,
    PlanStep,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
    StepCondition,
    StepOutputRef,
)
from ai_assistant.orchestration.interpretation import substituted_plan
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.testing import FakeMemoryStore, FakePlanner

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.orchestration.loop import RespondedTurn

#: This turn's own request. Nothing here grounds an element on a span of it — every
#: proposed element below is ``INFERRED``, which takes no argument — so the words matter
#: only in that they are not blank.
_ASKED: Final = "book the campsite"

#: The goal the loop mints on a turn that opens one (``_goal_ids("goal")``), and the one
#: a scripted plan must therefore name.
_GOAL: Final = "goal-1"


def _element(element_id: str | None, text: str) -> GoalElement:
    """One condition element of a revision an earlier turn recorded."""
    return GoalElement(text=text, ground=Ground.INFERRED, id=element_id)


def _continuing(*conditions: GoalElement) -> Goal:
    """A goal an earlier turn opened, whose current revision holds ``conditions``.

    ADR-0249 §9's ``D`` labels are rendered over exactly this tuple, in this order, by
    :meth:`~ai_assistant.core.types.GoalBrief.of` — which is what makes a label of the
    **brief** resolvable against the revision without a second projection.
    """
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book a campsite",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book a campsite",
                conditions=conditions,
                recorded_at=_NOW,
                raised_by="turn-earlier",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
        created_at=_NOW,
        last_engaged_at=_NOW,
        version=4,
    )


def _condition(label: str) -> StepCondition:
    """One ``when`` condition naming ``label``, on the basis that requires a verdict."""
    return StepCondition(
        about=label,
        basis=EvidenceBasis.INTERPRETATION,
        requires=InterpretationVerdict.QUALIFIES,
    )


def _plan(
    *,
    goal_id: str = _GOAL,
    when: Sequence[StepCondition] = (),
    interpretations: Sequence[PlanInterpretation] = (),
    steps: Sequence[PlanStep] | None = None,
) -> ActionPlan:
    """A plan for ``goal_id``, carrying whatever this case is about."""
    declared = (
        steps
        if steps is not None
        else ((PlanStep(id="step-1", intent="book it", capability="book", when=tuple(when)),))
    )
    return ActionPlan(
        id=f"{goal_id}-plan",
        goal_id=goal_id,
        steps=tuple(declared),
        interpretations=tuple(interpretations),
        created_at=_NOW,
        rationale="scripted",
    )


async def _turn(
    plan: ActionPlan,
    *,
    understanding: ProposedUnderstanding | None = None,
    continuing: Goal | None = None,
    supply: Sequence[MemoryRecord] = (),
) -> RespondedTurn:
    """One ``converse`` turn whose planner returns ``plan`` and ``understanding``."""
    memory = FakeMemoryStore(now=lambda: _NOW)
    for record in supply:
        await memory.add(record)
    return await _loop(
        memory, planner=FakePlanner(plan, now=lambda: _NOW, understanding=understanding)
    ).respond(
        _ASKED,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
        continuing=continuing,
    )


# --------------------------------------------------------------------------- #
# §9's refusals, at the function — including the one #2345 has no other reach  #
# --------------------------------------------------------------------------- #


def _substituted(plan: ActionPlan, goal: Goal, **rest: object) -> ActionPlan:
    """Resolve ``plan``'s labels against ``goal``'s current revision, no understanding."""
    return substituted_plan(
        plan,
        goal=goal,
        understanding=None,
        positions={},
        supply=rest.get("supply", ()),  # type: ignore[arg-type]  # one keyword per case
        minted=rest.get("minted", ()),  # type: ignore[arg-type]
    )


def test_a_plan_naming_no_label_is_returned_by_identity() -> None:
    """§12: "It changes no behaviour of a plan that declares none of the new keys".

    Returned **by identity** and not by a copy, which is what makes that clause a
    property of the function rather than a claim about it: a plan with no condition and
    no interpretation has no label to substitute and no record to check.
    """
    plan = _plan()

    assert _substituted(plan, _continuing()) is plan


def test_a_label_outside_the_range_refuses_the_plan() -> None:
    """§9: "An ordinal outside the range … resolves to nothing", and the plan is refused.

    Refused rather than dropped: "a step whose condition was dropped is a step with fewer
    requirements than the plan declared — the fail-open direction".
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))

    with pytest.raises(PlanningError, match="D2"):
        _substituted(_plan(when=(_condition("D2"),)), goal)


@pytest.mark.parametrize("label", ["C1", "S1", "D01", "D0", "1", "Da", "d1", "D1x"])
def test_a_value_that_is_not_a_condition_label_refuses_the_plan(label: str) -> None:
    """§9: "a value that is not such a label" resolves to nothing.

    One refusal for one scheme — the letter, then a 1-based ordinal in decimal **with no
    padding** — read by the one parser ADR-0249 §9's three labels and ADR-0252 §10's
    fourth already go through. A label of another tuple's letter is outside this space
    exactly as a malformed one is: "the label space is per tuple".

    The **blank** string is absent from the table because ``Identifier`` refuses one at
    construction, so no such condition exists to resolve — a refusal one level lower and
    not this one.
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))

    with pytest.raises(PlanningError):
        _substituted(_plan(when=(_condition(label),)), goal)


def test_a_label_naming_an_element_carrying_no_id_refuses_the_plan() -> None:
    """§9's fourth case, and ADR-0253 §7's fail-closed direction.

    ``None`` is what an element recorded **before** this decision carries, and such an
    element "is named by no ``StepCondition`` and settled by no interpretation" — so a
    plan naming one is refused rather than saved to sit unsatisfiable.
    """
    goal = _continuing(_element(None, "the forecast is dry"))

    with pytest.raises(PlanningError, match="D1"):
        _substituted(_plan(when=(_condition("D1"),)), goal)


def test_an_interpretation_naming_a_record_this_call_did_not_pass_refuses_the_plan() -> None:
    """§14 arm 20's first half, which is §9's second refusal (§8).

    "For each interpretation that carries a ``record``, the loop verifies it is the
    ``id`` of a record of the ``memories`` sequence **it** passed on that call", and a
    plan failing it "is refused before it is saved — not persisted, not driven, and not
    interpreted".
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))
    plan = _plan(
        interpretations=(PlanInterpretation(id="i-1", settles="D1", record="m-elsewhere"),)
    )

    with pytest.raises(PlanningError, match="m-elsewhere"):
        _substituted(plan, goal, supply=(_belief("m-1", "the site takes bookings"),))


def test_an_interpretation_over_a_minted_record_refuses_the_plan() -> None:
    """#2345: §8's minted-record refusal, given the producer the planning seam cannot be.

    §8 forbids "a label naming a record ADR-0231 §1's search or ADR-0230 §5's fetch
    **minted**", on ADR-0252 §1's ground that such a record "resolves in no store" — so a
    durable row naming one "would state a warrant it cannot show". §8 spells the disposal
    as an extraction failure, which is the planning seam's; the planner is handed **no**
    minted set and can produce no such refusal, so the check runs here and takes §9's
    disposal instead. The wording is FLAGged for a §8 amendment.
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))
    plan = _plan(interpretations=(PlanInterpretation(id="i-1", settles="D1", record="m-search"),))

    with pytest.raises(PlanningError, match="m-search"):
        _substituted(
            plan, goal, supply=(_belief("m-search", "a search result"),), minted=("m-search",)
        )


def test_an_interpretation_over_a_step_output_is_checked_by_neither() -> None:
    """§14 arm 20's paired half — "the one that matters" — at the function.

    §9: "An interpretation carrying a ``reads`` is checked by neither — its input is a
    value this plan will itself produce, and §8's construction rules are the whole of
    what it owes." So it passes the record check on an **empty** supply and its
    ``settles`` is still substituted.
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))
    plan = _plan(
        steps=(PlanStep(id="step-1", intent="read it", capability="refresh_forecast"),),
        interpretations=(
            PlanInterpretation(
                id="i-1", settles="D1", reads=StepOutputRef(step="step-1", field="summary")
            ),
        ),
    )

    substituted = _substituted(plan, goal)

    assert substituted.interpretations[0].settles == "cond-1"
    assert substituted.interpretations[0].record is None


# --------------------------------------------------------------------------- #
# §14 arms 21-23 — which sequence is in force, through whole turns             #
# --------------------------------------------------------------------------- #


async def test_a_plan_declaring_none_of_the_new_keys_is_driven_as_it_was_returned() -> None:
    """§12's pin: a plan with no condition and no interpretation is untouched.

    Every field but ADR-0249 §8's stamp — which is the loop's and was the loop's before
    this decision — is byte for byte what the planner returned.
    """
    scripted = _plan()

    responded = await _turn(scripted)

    assert responded.turn.plan == scripted.model_copy(update={"targets_revision": 1})


async def test_a_condition_label_resolves_against_the_brief_where_no_understanding_comes_back() -> (
    None
):
    """§14 arm 21: "the condition label resolves against the brief".

    "Where the envelope does not [carry an ``understanding``], it indexes the
    ``GoalBrief.conditions`` the call received" — a brief carrying two conditions renders
    ``D1`` and ``D2``, and an envelope naming ``D2`` produces a plan whose ``about`` is
    the **second** element's id.
    """
    goal = _continuing(
        _element("cond-1", "the forecast is dry"), _element("cond-2", "the site has a pitch free")
    )

    responded = await _turn(_plan(goal_id=goal.id, when=(_condition("D2"),)), continuing=goal)

    assert responded.turn.plan.steps[0].when[0].about == "cond-2"
    assert responded.turn.plan.targets_revision == 1, "the revision the brief described"


async def test_a_label_past_the_briefs_own_conditions_refuses_the_turns_plan() -> None:
    """§14 arm 21's third clause: ``D3`` over a two-condition brief resolves to nothing.

    The refusal reaches the turn, which is the whole of what this lane decides about it:
    "What that refusal then causes — a report, a replan, a turn that composes without
    acting — is recovery policy and is **A7's and A9's**."
    """
    goal = _continuing(
        _element("cond-1", "the forecast is dry"), _element("cond-2", "the site has a pitch free")
    )

    with pytest.raises(PlanningError, match="D3"):
        await _turn(_plan(goal_id=goal.id, when=(_condition("D3"),)), continuing=goal)


async def test_a_condition_label_resolves_against_the_understanding_that_call_returned() -> None:
    """§14 arm 22, the first-turn case, "and the ordering is asserted, not inferred".

    A goal at revision 1 carries "no elements", and a planner decides the understanding
    and the plan "in one pass" — so on the turn a condition first exists, it exists only
    in the ``ProposedUnderstanding`` that same call returned and its ``GoalElement.id``
    is minted by ``orchestration`` a moment later. A loop that resolved **before**
    recording could never let a plan condition on a condition that call proposed.
    """
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        conditions=(
            ProposedElement(text="the forecast over the trip is dry", ground=Ground.INFERRED),
        ),
    )

    responded = await _turn(_plan(when=(_condition("D1"),)), understanding=understanding)

    record = responded.goal
    assert record is not None
    assert record.goal.interpretation[0].conditions == (), (
        "revision 1 carried no elements, so D1 named nothing that existed at the call"
    )
    minted = record.goal.interpretation[-1].conditions[0]
    assert responded.turn.plan.targets_revision == 2, "ADR-0249 §8's stamp, taken first"
    assert responded.turn.plan.steps[0].when[0].about == minted.id
    assert minted.id is not None
    assert minted.id != "D1", "§7's grammar rule makes an id and a label disjoint"


async def test_the_correspondence_is_to_the_proposals_positions_not_the_recorded_tuple() -> None:
    """§14 arm 23: a proposed element ADR-0249 §7 dropped "resolves to nothing".

    An envelope proposing two conditions ``[A, B]`` of which **``A`` is dropped** for an
    unresolvable ground: a step naming ``D2`` resolves to **``B``'s** id, "because
    indexing the recorded tuple instead would silently point ``D2`` at nothing and ``D1``
    at ``B``".
    """
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        conditions=(
            ProposedElement(text="A", ground=Ground.FROM_EVIDENCE, evidence_label="M9"),
            ProposedElement(text="B", ground=Ground.INFERRED),
        ),
    )

    responded = await _turn(_plan(when=(_condition("D2"),)), understanding=understanding)

    record = responded.goal
    assert record is not None
    [survivor] = record.goal.interpretation[-1].conditions
    assert survivor.text == "B", "A's FROM_EVIDENCE label named no record of an empty supply"
    assert responded.turn.plan.steps[0].when[0].about == survivor.id


async def test_a_label_naming_a_dropped_proposed_element_refuses_the_plan() -> None:
    """§14 arm 23's other half, which is the one a length comparison would get wrong.

    ``D1`` names the element whose ground did not resolve. It resolves to nothing "rather
    than to its neighbour", so the plan is refused — where indexing the **recorded**
    tuple would have pointed it at ``B`` and silently changed what the step requires.
    """
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        conditions=(
            ProposedElement(text="A", ground=Ground.FROM_EVIDENCE, evidence_label="M9"),
            ProposedElement(text="B", ground=Ground.INFERRED),
        ),
    )

    with pytest.raises(PlanningError, match="D1"):
        await _turn(_plan(when=(_condition("D1"),)), understanding=understanding)


async def test_an_understanding_that_drops_every_condition_leaves_no_label_resolvable() -> None:
    """§9, through ADR-0249 §7's completeness rule rather than a rule of its own.

    A revision "is a complete statement of an understanding", so an element the proposal
    neither retains nor replaces "is **not** in the new revision" — and the label space in
    force is the *proposal's*. A planner that revised away the condition its own step
    names has written a plan nobody can read, and it is refused rather than saved.
    """
    goal = _continuing(_element("cond-1", "the forecast is dry"))

    with pytest.raises(PlanningError, match="D1"):
        await _turn(
            _plan(goal_id=goal.id, when=(_condition("D1"),)),
            understanding=ProposedUnderstanding(retains_outcome=True),
            continuing=goal,
        )


# --------------------------------------------------------------------------- #
# §9 on a turn's *second* call, over the supply that call was handed           #
# --------------------------------------------------------------------------- #


async def test_the_revision_after_a_servicing_resolves_against_that_calls_own_values() -> None:
    """§9 at the second planner call, which is a different call with different values.

    ADR-0228 §8 binds ADR-0226 §3's label space **per call**, and ADR-0228 §1 makes a
    revision "the model's judgement over a wider supply" — so a turn that serviced a read
    hands its second call a supply the first did not have, and an understanding recorded
    off that call mints elements the first call's did not.

    Both halves are asserted over one turn, because both are ways the second site could
    be wrong while every other arm here stayed green: the interpretation's ``record``
    names the record **the servicing added**, which the first call's supply does not
    hold, and the step's condition label resolves against the **second** call's
    understanding, whose element the first call's revision does not carry.
    """
    memory = await _seeded()
    revision = _plan(
        when=(_condition("D1"),),
        interpretations=(PlanInterpretation(id="i-1", settles="D1", record="episode-1"),),
    ).model_copy(update={"id": "plan-2"})
    planner = FakePlanner(
        now=lambda: _NOW,
        read_request=_hop("M1"),
        revision=revision,
        understanding=ProposedUnderstanding(
            retains_outcome=True,
            conditions=(ProposedElement(text="the forecast is dry", ground=Ground.INFERRED),),
        ),
    )

    responded = await _loop(memory, planner=planner).respond(
        _ASKED, narrow=_bounded(), operation=ConversationalOperation.CONVERSE
    )

    first_supply = [record.id for record in planner.calls[0][3]]
    assert "episode-1" not in first_supply, (
        "the hop is what put it in front of the planner, so the first call's supply "
        "could not have satisfied §8's record check"
    )
    record = responded.goal
    assert record is not None
    assert responded.turn.plan.id == "plan-2", "the plan the second call returned"
    assert responded.turn.plan.targets_revision == 3, "both calls revised (ADR-0249 §8)"
    [element] = record.goal.interpretation[-1].conditions
    assert responded.turn.plan.steps[0].when[0].about == element.id, (
        "resolved against the *second* call's understanding, not the first's revision"
    )
    assert responded.turn.plan.interpretations[0].record == "episode-1"
