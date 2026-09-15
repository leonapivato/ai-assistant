"""ADR-0265 §10's L2 arms at the loop: minting, the links, and the action label.

**"Recording ``PlannerOutput.actions`` in §2's order, the ``serves`` resolution and its
drops (§3) … and the resolution and refusal of a step's action label (§4)"** — §9's L2
bullet, driven through the production
:class:`~ai_assistant.orchestration.loop.LearningLoop` over the canonical fakes. Arms
**1(b)**, **2**, **3** and **4** live here; the store's own refusals are L1's
conformance suite, the ``A`` block a request renders is L3's, and the write that reaches
a real ``PlanStore`` is ``test_engine_intended_actions.py``'s.

**Every correction is a subsequent turn** (§10), which is the owner's sequencing ruling
of 2026-09-13: arms 2 and 3 drive a second turn over the goal the first one left, with
``continuing`` carrying it, and no arm drives a message into a running turn.

**Nothing here claims an effect, checks a reuse or retries one** (§6, §7). An intended
action is "a record of an intent and never an instruction to act", and what these arms
read is the record and the plan's reference to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pytest
from test_loop_reads import _NOW, _bounded, _loop

from ai_assistant.core.errors import PlanningError
from ai_assistant.core.types import (
    ActionPlan,
    Goal,
    GoalBrief,
    GoalElement,
    GoalInterpretation,
    Ground,
    IntendedAction,
    MemorySource,
    PlannerOutput,
    PlanStep,
    ProposedAction,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
)
from ai_assistant.orchestration.loop import ConversationalOperation
from ai_assistant.testing import FakeMemoryStore

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import (
        CurrentContext,
        EvidenceDigest,
        MemoryRecord,
        ReadAskOutcome,
        ShownFile,
    )
    from ai_assistant.orchestration.loop import LearningLoop, RecordedGoal, RespondedTurn

#: This turn's own request. Nothing here grounds an element on a span of it — every
#: proposed element below is ``INFERRED`` — so the words matter only in that they are
#: not blank.
_ASKED: Final = "book two rooms for the trip"

#: The goal the loop mints on a turn that opens one, and the one a scripted plan must
#: therefore name (``_goal_ids("goal")``).
_GOAL: Final = "goal-1"

#: The owner's first case, in the system's own words: two identical rooms are two
#: intended actions, because the user asked for two.
_FIRST_ROOM: Final = "book the first room"
_SECOND_ROOM: Final = "book the second room"


def _step(step_id: str, *, action: str | None = None) -> PlanStep:
    """One step, optionally selecting an intended action by ``A`` label (§4).

    The capability and the parameters are **byte-identical** across every step this
    module builds, which is §6's point: at the argument key nothing distinguishes two
    rooms asked for from one room asked for twice, and the only thing that separates
    them is the identity this decision mints.
    """
    return PlanStep(
        id=step_id,
        intent="book it",
        capability="book_room",
        parameters={"nights": 2},
        intended_action=action,
    )


class _Proposing:
    """A planner whose envelope a case rewrites **between** its turns.

    One instance across a case's turns, driven by one loop, because ADR-0265 §10 states
    every correction as a *subsequent turn* and a second loop would restart the id
    factory — minting a second turn's elements under ids the first turn already spent.
    That is a property of the harness and not of the system, and it is exactly what
    arms 2 and 3 would misread as "the id did not change".

    It records the :class:`~ai_assistant.core.types.GoalBrief` of every call, which is
    what a rendering arm reads: ADR-0265 §4's projection is what the *planner* is shown,
    and no return value carries it.
    """

    def __init__(self) -> None:
        self.calls: list[GoalBrief] = []
        self.understanding: ProposedUnderstanding | None = None
        self.actions: tuple[ProposedAction, ...] = ()
        self.steps: tuple[PlanStep, ...] = ()

    async def plan(  # noqa: PLR0913 — the Planner Protocol's own parameter list
        self,
        goal: GoalBrief,
        *,
        utterance: str,
        context: CurrentContext,
        memories: Sequence[MemoryRecord] = (),
        capabilities: Sequence[str],
        files: Sequence[ShownFile] = (),
        read_outcomes: Sequence[ReadAskOutcome] = (),
        evidence: Sequence[EvidenceDigest] = (),
    ) -> PlannerOutput:
        """Answer with this planner's current envelope, over a plan id per call."""
        self.calls.append(goal)
        return PlannerOutput(
            plan=ActionPlan(
                id=f"plan-{len(self.calls)}",
                goal_id=goal.goal_id,
                steps=self.steps,
                created_at=_NOW,
                rationale="scripted",
            ),
            understanding=self.understanding,
            actions=self.actions,
        )


def _driver() -> tuple[LearningLoop, _Proposing]:
    """One loop and the planner behind it, for a case that drives one turn or two."""
    planner = _Proposing()
    return _loop(FakeMemoryStore(now=lambda: _NOW), planner=planner), planner


async def _turn(  # noqa: PLR0913 — the loop, its planner, and one keyword per thing a case scripts about the turn's envelope
    loop: LearningLoop,
    planner: _Proposing,
    *,
    understanding: ProposedUnderstanding | None = None,
    actions: tuple[ProposedAction, ...] = (),
    steps: tuple[PlanStep, ...] = (),
    continuing: Goal | None = None,
) -> RespondedTurn:
    """One ``converse`` turn, with the planner scripted to this turn's envelope.

    Args:
        loop: The loop to drive, shared across a case's turns.
        planner: The planner behind it, whose envelope this call sets.
        understanding: What it proposes the system now understands, or ``None``.
        actions: What it proposes the goal now intends (ADR-0265 §2).
        steps: The steps of the plan it proposes.
        continuing: The goal an earlier turn left, or ``None`` to open one.

    Returns:
        The turn.
    """
    planner.understanding = understanding
    planner.actions = actions
    planner.steps = steps
    return await loop.respond(
        _ASKED,
        narrow=_bounded(),
        operation=ConversationalOperation.CONVERSE,
        conversation_id="c-1",
        continuing=continuing,
    )


def _recorded(responded: RespondedTurn) -> RecordedGoal:
    """The goal record this turn built, asserted present rather than narrowed silently."""
    record = responded.goal
    assert record is not None
    return record


def _goal_holding(*actions: IntendedAction, constraints: Sequence[GoalElement] = ()) -> Goal:
    """A goal an earlier turn opened, holding ``actions`` and one revision's elements."""
    return Goal(
        id="goal-earlier",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome="book two rooms",
                outcome_ground=Ground.USER_STATED,
                outcome_span="book two rooms",
                constraints=tuple(constraints),
                recorded_at=_NOW,
                raised_by="turn-earlier",
            ),
        ),
        intended_actions=tuple(actions),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
        created_at=_NOW,
        last_engaged_at=_NOW,
        version=4,
    )


def _element(element_id: str, text: str) -> GoalElement:
    """One constraint of a revision an earlier turn recorded."""
    return GoalElement(id=element_id, text=text, ground=Ground.INFERRED)


def _intended(action_id: str, *, serves: tuple[str, ...] = ()) -> IntendedAction:
    """One intended action an earlier turn minted, as the store holds it."""
    return IntendedAction(id=action_id, intent=_FIRST_ROOM, serves=serves)


# --------------------------------------------------------------------------- #
# Arm 1(b): two rooms are two identities, and the loop resolves both labels    #
# --------------------------------------------------------------------------- #


async def test_two_proposed_actions_become_two_identities_a_plan_names_apart() -> None:
    """§10 arm 1(b): the loop "records two actions and resolves **both** labels".

    The owner's case, end to end at the loop: a ``PlannerOutput`` carrying two
    ``ProposedAction``s and a plan whose two steps name ``A1`` and ``A2``. The steps'
    capability and ``parameters`` are **byte-identical**, so §6's ``(goal, intended
    action, effect key)`` triple is distinct for the two steps while the argument key is
    equal — "which is the fact an at-most-once claim scoped to the goal alone cannot
    see", and "an earlier booking must not count as fulfilling *book another one*".

    **In §2's order, before the plan is saved.** The goal is opened this turn and holds
    no action at the call, so ``A1`` and ``A2`` name nothing that existed when the
    planner returned: a loop that resolved before recording could not produce this plan
    at all, which is what makes the ordering asserted rather than inferred.
    """
    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        steps=(_step("step-1", action="A1"), _step("step-2", action="A2")),
        actions=(ProposedAction(intent=_FIRST_ROOM), ProposedAction(intent=_SECOND_ROOM)),
    )

    first, second = _recorded(responded).goal.intended_actions
    assert (first.intent, second.intent) == (_FIRST_ROOM, _SECOND_ROOM), "the proposed order"
    assert first.id != second.id, "§1: two members of one goal, two identities"
    steps = responded.turn.plan.steps
    assert (steps[0].intended_action, steps[1].intended_action) == (first.id, second.id)
    assert steps[0].capability == steps[1].capability
    assert steps[0].parameters == steps[1].parameters, "and the argument key is equal"


async def test_a_minted_id_is_never_the_label_the_planner_named() -> None:
    """§1, §4: an ``IntendedAction.id`` "is never an action label, and the type refuses one".

    So the substitution is observable as a substitution: a loop that left the label
    standing would leave ``A1`` on the step, and the store's membership check would find
    no member carrying it "on any goal, ever".
    """
    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        steps=(_step("step-1", action="A1"),),
        actions=(ProposedAction(intent=_FIRST_ROOM),),
    )

    [action] = _recorded(responded).goal.intended_actions
    assert action.id != "A1"
    assert responded.turn.plan.steps[0].intended_action == action.id


async def test_a_link_that_resolves_to_nothing_is_dropped_and_the_action_recorded() -> None:
    """§10 arm 1(b)'s drop limb, which §3 states and no other arm reaches.

    A ``ProposedAction`` whose ``serves`` is ``("C1", "C99")`` over a brief holding one
    constraint is **recorded**, with ``serves`` naming the element ``C1`` resolved to
    "and **nothing else** — the surviving links in their proposed order, the
    unresolvable one gone, and the action neither refused nor held".

    The asymmetry against §4 is exact and is asserted beside it: "``serves`` gates
    nothing, so losing an entry costs legibility; a step's action label scopes an effect
    claim, so losing one would cost a dispatch nothing could recognise".
    """
    goal = _goal_holding(constraints=(_element("e-c1", "two rooms on the same floor"),))
    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C1", "C99")),),
        continuing=goal,
    )

    [action] = _recorded(responded).goal.intended_actions
    assert action.serves == ("e-c1",), (
        "the link that resolved, and nothing for the one that did not"
    )
    assert action.intent == _FIRST_ROOM, "and the action itself is recorded, not refused"


async def test_an_action_whose_every_link_drops_is_recorded_with_no_link_at_all() -> None:
    """§3: such an action "is recorded with ``serves`` **empty**".

    Which "§3 makes a well-formed intended action rather than a degraded one" — there is
    no repair, no refusal and no standing that says a link was lost.
    """
    goal = _goal_holding(constraints=(_element("e-c1", "two rooms on the same floor"),))
    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C9", "S1", "banana")),),
        continuing=goal,
    )

    [action] = _recorded(responded).goal.intended_actions
    assert action.serves == ()
    assert action.intent == _FIRST_ROOM


async def test_an_envelope_proposing_no_action_records_none_and_raises_nothing() -> None:
    """§2: empty ``actions`` "records none, raises nothing and re-plans nothing".

    This is the clause that lets L2 land before L3 (§9): "L2 tolerates an envelope
    carrying no ``action`` key", which is every envelope a planner that knows nothing of
    this decision returns — and "no implementation reads an empty ``actions`` as an
    error, a degradation or an instruction to re-plan".
    """
    loop, planner = _driver()

    responded = await _turn(loop, planner)

    assert _recorded(responded).goal.intended_actions == ()
    assert _recorded(responded).mintings == (), "nothing to write, so no write is carried"
    assert len(planner.calls) == 1, "and nothing re-planned"


async def test_a_combined_first_turn_links_the_action_to_the_element_it_just_minted() -> None:
    """§10 arm 1(b)'s combined limb: one call proposes the element, the action and the plan.

    "One ``PlannerOutput`` whose ``understanding`` proposes one new constraint, whose
    single ``ProposedAction`` names that constraint's label in the **understanding's
    own** sequence, and whose plan step names ``A1`` records the revision and mints that
    element's ``id`` first — so the action's stored ``serves`` holds **that** id and not
    nothing … and ``targets_revision`` and the resolved ``intended_action`` both name
    records this same call wrote."

    It is §2's steps (a), (b), (c) and (d) in one assertion, and the whole of why they
    are ordered: at the moment the planner returned, the element did not exist, the
    action did not exist, and neither label could have resolved.
    """
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text="two rooms on the same floor", ground=Ground.INFERRED),),
    )

    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        steps=(_step("step-1", action="A1"),),
        understanding=understanding,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),),
    )

    record = _recorded(responded)
    assert record.goal.interpretation[0].constraints == (), "revision 1 carried no element"
    [element] = record.goal.interpretation[-1].constraints
    [action] = record.goal.intended_actions
    assert action.serves == (element.id,), "the id step (a) minted a line before step (b)"
    assert responded.turn.plan.targets_revision == 2, "ADR-0249 §8's stamp, taken between them"
    assert responded.turn.plan.steps[0].intended_action == action.id


async def test_a_link_resolves_against_the_understanding_that_call_returned() -> None:
    """§3: the resolution is "ADR-0253 §9's and ADR-0249 §7's, unchanged".

    "Where the call returned an ``understanding``, the label indexes **that
    understanding's own** tuple" — so a ``C1`` on a call that proposed a constraint names
    the **proposal's** first constraint and never the brief's, and the two are different
    elements on a goal that already held one.
    """
    goal = _goal_holding(constraints=(_element("e-held", "an earlier constraint"),))
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text="two rooms on the same floor", ground=Ground.INFERRED),),
    )

    loop, planner = _driver()

    responded = await _turn(
        loop,
        planner,
        understanding=understanding,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),),
        continuing=goal,
    )

    record = _recorded(responded)
    [element] = record.goal.interpretation[-1].constraints
    [action] = record.goal.intended_actions
    assert element.text == "two rooms on the same floor", "omission is removal (ADR-0249 §7)"
    assert action.serves == (element.id,)
    assert action.serves != ("e-held",), "the proposal's C1 and not the brief's"


# --------------------------------------------------------------------------- #
# Arm 2: "change our booking to Sunday" mints no second action                 #
# --------------------------------------------------------------------------- #


async def test_restating_an_element_mints_no_action_and_repoints_nothing() -> None:
    """§10 arm 2, over two turns: the rewording requirement, whole.

    Turn 1 opens the goal at a revision whose element reads **Saturday** and mints one
    intended action serving it. Turn 2 records a revision restating it **Sunday**.
    Asserted: the element's ``id`` is **new** (ADR-0253 §7, which mints a new id for a
    restated element); ``Goal.intended_actions`` is **byte-identical** before and after;
    the action's ``serves`` still names the **old** element id and is unchanged; and the
    action resolves from an ``A`` label on the next plan exactly as before.

    "A duplicate booking after a rewording needs a mechanism that treats a reworded
    element as a *new* act; since nothing here derives an act from an element, no
    rewording and no split can produce one" (§3).
    """
    saturday = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text="the booking is for Saturday", ground=Ground.INFERRED),),
    )
    loop, planner = _driver()
    first = await _turn(
        loop,
        planner,
        steps=(_step("step-1", action="A1"),),
        understanding=saturday,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),),
    )
    opened = _recorded(first).goal
    [saturday_element] = opened.interpretation[-1].constraints

    sunday = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(ProposedElement(text="the booking is for Sunday", ground=Ground.INFERRED),),
    )
    second = await _turn(
        loop,
        planner,
        steps=(_step("step-1", action="A1"),),
        understanding=sunday,
        continuing=opened,
    )

    revised = _recorded(second).goal
    [sunday_element] = revised.interpretation[-1].constraints
    assert sunday_element.text == "the booking is for Sunday"
    assert sunday_element.id != saturday_element.id, "ADR-0253 §7 mints a new id for a restatement"
    assert revised.intended_actions == opened.intended_actions, "byte-identical, §1's append-only"
    assert revised.intended_actions[0].serves == (saturday_element.id,), (
        "§3: not rewritten, not recomputed, not dropped and not refreshed"
    )
    assert second.turn.plan.steps[0].intended_action == revised.intended_actions[0].id, (
        "and the action resolves from an A label exactly as before"
    )


async def test_the_brief_of_a_restated_goal_shows_the_action_with_no_live_link() -> None:
    """§10 arm 2's rendering limb, read off the brief the **planner** was handed.

    "The brief renders the action with its ``serves`` **empty**, because the element it
    names is not in the current revision" (§4) — and the action itself is still rendered,
    still labelled ``A1``, and still selectable. That is what makes the staleness cost
    legibility and nothing else.
    """
    stale = _goal_holding(
        # An action minted against an element a later revision restated: §3's state,
        # reached here as a stored goal rather than by re-driving the two turns above.
        _intended("ia-1", serves=("e-saturday",)),
        constraints=(_element("e-sunday", "the booking is for Sunday"),),
    )

    loop, planner = _driver()

    await _turn(loop, planner, continuing=stale)

    [brief] = planner.calls
    [rendered] = brief.actions
    assert rendered.serves == (), "the stale link is shown nowhere"
    assert rendered.intent == _FIRST_ROOM, "and the action is rendered, under A1, as before"
    assert brief.constraints[0].text == "the booking is for Sunday"


# --------------------------------------------------------------------------- #
# Arm 3: a split element leaves the identity alone                             #
# --------------------------------------------------------------------------- #


async def test_splitting_an_element_in_two_leaves_the_intended_action_untouched() -> None:
    """§10 arm 3: "replace one element with two that between them say what it said".

    Asserted: two new element ids, ``intended_actions`` unchanged, and ``serves`` naming
    **neither** of the two new ids — "and that no clause of the implementation reads that
    as a reason to mint, withdraw or re-point anything".

    A split is where a derived identity would break loudest: one element becoming two
    would become one act becoming two, and the second booking would exist because a model
    reworded a sentence.
    """
    whole = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(
            ProposedElement(
                text="two rooms, on the same floor, for Saturday", ground=Ground.INFERRED
            ),
        ),
    )
    loop, planner = _driver()
    first = await _turn(
        loop,
        planner,
        understanding=whole,
        actions=(ProposedAction(intent=_FIRST_ROOM, serves=("C1",)),),
    )
    opened = _recorded(first).goal
    [before] = opened.interpretation[-1].constraints

    split = ProposedUnderstanding(
        retains_outcome=True,
        constraints=(
            ProposedElement(text="two rooms on the same floor", ground=Ground.INFERRED),
            ProposedElement(text="the booking is for Saturday", ground=Ground.INFERRED),
        ),
    )
    second = await _turn(loop, planner, understanding=split, continuing=opened)

    revised = _recorded(second).goal
    halves = revised.interpretation[-1].constraints
    assert [one.text for one in halves] == [
        "two rooms on the same floor",
        "the booking is for Saturday",
    ]
    assert {one.id for one in halves}.isdisjoint({before.id}), "two new ids (ADR-0253 §7)"
    assert revised.intended_actions == opened.intended_actions, "unchanged, member for member"
    assert revised.intended_actions[0].serves == (before.id,), (
        "§3: naming neither of the two new ids, and nothing re-points it"
    )
    assert _recorded(second).mintings == (), "and the split minted no action"


# --------------------------------------------------------------------------- #
# Arm 4: selection and refusal, over the grammar's own boundary                #
# --------------------------------------------------------------------------- #


async def test_a_label_naming_the_goals_one_action_resolves_to_its_id() -> None:
    """§10 arm 4's first clause: "a plan naming ``A1`` where the goal holds one action
    resolves to that action's id".

    Over a goal an earlier turn left, so the sequence the label indexes is the brief's
    own ``actions`` — one entry per member of ``Goal.intended_actions``, in that tuple's
    order — with no proposal on this call extending it.
    """
    goal = _goal_holding(_intended("ia-1"))
    loop, planner = _driver()

    responded = await _turn(loop, planner, steps=(_step("step-1", action="A1"),), continuing=goal)

    assert responded.turn.plan.steps[0].intended_action == "ia-1"


async def test_a_label_past_the_goals_own_actions_refuses_the_plan() -> None:
    """§4: "an ordinal outside the range" resolves to nothing, and refuses the plan.

    Refused and never dropped: "a step whose action was dropped is a step whose effect
    claim would be scoped to nothing — the fail-open direction". The plan is not handed
    to ``save_plan``, no step of it is dispatched and no interpretation is performed,
    which is what the raised :class:`PlanningError` leaving the turn is.
    """
    goal = _goal_holding(_intended("ia-1"))
    loop, planner = _driver()

    with pytest.raises(PlanningError, match="A2"):
        await _turn(loop, planner, steps=(_step("step-1", action="A2"),), continuing=goal)


@pytest.mark.parametrize("label", ["A0", "A01", "A+1", "a1", "A 1", "A\uff11", "banana", "A"])
async def test_a_value_that_is_not_an_action_label_refuses_the_plan(label: str) -> None:
    """§10 arm 4's table: every spelling the grammar excludes, refused rather than parsed.

    "The padded, signed, lower-cased, whitespace-bearing and non-ASCII-digit spellings
    are named because an ``int()``-based or Unicode-``\\d``-based parse accepts them
    while every other arm still passes" — and each of them "resolves to nothing and is
    refused … rather than parsed, repaired or case-folded".

    ``A1 `` is **absent from this table and is asserted separately**
    (:func:`test_a_trailing_space_never_reaches_the_loop_as_its_own_spelling`): the field
    is an ``Identifier``, which strips at construction, so the loop is never handed that
    spelling and cannot refuse it. Refusing it is the **seam's**, under §9's L3 — "the
    strict extraction of the step's ``action`` key".
    """
    goal = _goal_holding(_intended("ia-1"))
    loop, planner = _driver()

    with pytest.raises(PlanningError):
        await _turn(loop, planner, steps=(_step("step-1", action=label),), continuing=goal)


def test_a_trailing_space_never_reaches_the_loop_as_its_own_spelling() -> None:
    """Why ``A1 `` is not in the table above, stated rather than left as a gap.

    :data:`~ai_assistant.core.types.Identifier` is "non-blank **and stripped**"
    (ADR-0018 §2), so ``PlanStep`` normalises ``"A1 "`` to ``"A1"`` before any loop sees
    it: there is no value here for §4's refusal to act on, and a loop that "refused the
    trailing-space spelling" would be refusing a string it can never be handed. §10 arm
    4 names it among L2's refusals; the mechanism that can take it is L3's strict
    extraction, which reads the planner's JSON before a ``PlanStep`` exists.
    """
    assert PlanStep(id="s", intent="book it", capability="book_room", intended_action="A1 ") == (
        PlanStep(id="s", intent="book it", capability="book_room", intended_action="A1")
    )


async def test_a_step_naming_no_action_is_driven_carrying_none() -> None:
    """§4: "a plan whose step names no action is saved and carries ``None``".

    "A step naming no intended action is held to nothing by this decision", and every
    plan written before it carries ``None`` — "a conforming plan rather than a degraded
    one". The plan is returned **by identity** where it names no label of either space,
    which is ADR-0253 §12's clause holding over one more key.
    """
    goal = _goal_holding(_intended("ia-1"))
    loop, planner = _driver()

    responded = await _turn(loop, planner, steps=(_step("step-1"),), continuing=goal)

    assert responded.turn.plan.steps[0].intended_action is None
    assert responded.turn.plan.steps == (_step("step-1"),), (
        "byte for byte what the planner returned, which is ADR-0253 §12 over one more key"
    )
