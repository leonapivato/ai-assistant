"""The types ADR-0250 §19's M1 lands, and what each of them refuses.

Every validator here exists to make an illegal shape unrepresentable, so these tests
are mostly about what the types *refuse* — ``tests/core/test_planning_types.py``'s own
posture, applied to the goal-association contract.

**What is here and what is not.** M1 lands the contract "at unchanged behaviour": no
association is run, no focus is stamped, no question is raised and no reference is
resolved. So the arms ADR-0250 §20 states over a *turn* are not reachable in this lane
and are M2's, M3's and M4's; what is reachable is every clause the types themselves
decide, and the structural half of §20's arm 22. Each case below names the arm it
discharges or the clause it pins.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    MAX_ASSOCIATION_CANDIDATES,
    ActionPlan,
    AssociationVerdict,
    CandidateGoal,
    Clarification,
    ClarificationWithdrawal,
    CurrentContext,
    Disposition,
    EngagementDisposition,
    ExecutionState,
    Goal,
    GoalAbandonment,
    GoalAssociation,
    GoalBrief,
    GoalCandidacy,
    GoalCandidates,
    GoalDisambiguation,
    GoalEngagement,
    GoalInterpretation,
    GoalQuestion,
    GoalQuestionDisposition,
    GoalStatus,
    GoalSummary,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedQuestion,
    ProposedUnderstanding,
    Provenance,
    ReferenceOutcome,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    StepExecution,
    StepOutcome,
    TimeOfDay,
    TurnOutcome,
    TurnReference,
    TurnResult,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _WHEN + timedelta(hours=1)
_PROV = Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)

#: The repository root, for the one case that reads the shipped tree rather than a
#: value (§20 arm 23's half this lane can decide).
_SRC: Final = Path(__file__).resolve().parents[2] / "src"

#: A real turn result, for the one case that needs a pass which actually planned —
#: every other case here is about a pass that did not, where ``turn`` is ``None``.
_PLANNED = TurnResult(
    utterance="book it",
    goal=GoalBrief(
        goal_id="g1",
        outcome="book a campsite",
        outcome_ground=Ground.USER_STATED,
        status=GoalStatus.ACTIVE,
    ),
    context=CurrentContext(
        now=_WHEN, time_of_day=TimeOfDay.MORNING, within_working_hours=True, is_weekend=False
    ),
    memories=(),
    plan=ActionPlan(id="p1", goal_id="g1", steps=(), created_at=_WHEN, targets_revision=1),
)

#: A driven step, for the one case that asserts an undecided turn carries none.
_DROVE = StepOutcome(
    step_id="s1",
    disposition=Disposition.EXECUTED,
    state=ExecutionState(
        id="e1", plan_id="p1", steps=(StepExecution(step_id="s1"),), updated_at=_WHEN
    ),
)


def _goal(goal_id: str = "g1", *, outcome: str = "book a campsite", **overrides: object) -> Goal:
    """A goal opened at revision 1 (ADR-0249 §3)."""
    fields: dict[str, object] = {
        "id": goal_id,
        "conversation_id": "c1",
        "interpretation": (
            GoalInterpretation(
                revision=1,
                outcome=outcome,
                outcome_ground=Ground.USER_STATED,
                outcome_span=outcome,
                recorded_at=_WHEN,
                raised_by="t-1",
            ),
        ),
        "provenance": _PROV,
        "created_at": _WHEN,
    }
    return Goal(**(fields | overrides))  # type: ignore[arg-type]


def _question(**overrides: object) -> GoalQuestion:
    """An ``OPEN`` question carrying both content fields (ADR-0250 §8)."""
    fields: dict[str, object] = {
        "id": "q1",
        "goal_id": "g1",
        "attempt_id": "a1",
        "text": "which campsite did you mean?",
        "about": "the usual campsite",
        "asked_at": _WHEN,
        "expires_at": _WHEN + timedelta(hours=72),
    }
    return GoalQuestion(**(fields | overrides))  # type: ignore[arg-type]


# --- §1: the fifth absence ------------------------------------------------


def test_a_goal_carries_the_conversation_of_its_most_recent_engagement() -> None:
    """§1: ``last_engaged_in`` is an ``Identifier | None`` beside ``last_engaged_at``.

    ADR-0249 §1's four-absences clause is **extended and not weakened**: ``None`` has
    the same one route — a row written before ADR-0250 — and no lane writes ``None``
    into it. So the field defaults to absent and a goal that carries one round-trips.
    """
    assert _goal().last_engaged_in is None
    engaged = _goal(last_engaged_at=_LATER, last_engaged_in="c2")
    assert (engaged.last_engaged_at, engaged.last_engaged_in) == (_LATER, "c2")
    assert Goal.model_validate(engaged.model_dump()) == engaged


def test_conversation_id_is_provenance_and_last_engaged_in_is_not_it() -> None:
    """§1, §13: two fields with two meanings, and the first is never rewritten.

    "``Goal.conversation_id`` keeps its provenance meaning while a second conversation
    engages the goal" — so the record still answers *where did this objective come
    from* truthfully after any number of cross-conversation resumptions, which is the
    question ADR-0249 §1 put the field there to answer. Asserted as two distinct
    fields rather than as a behaviour, because the behaviour is M3's.
    """
    goal = _goal(last_engaged_in="c2")
    assert goal.conversation_id == "c1"
    assert goal.last_engaged_in == "c2"


# --- §2: the cap, and the count that discloses it -------------------------


def test_the_cap_is_a_fixed_constant_and_not_a_setting() -> None:
    """§2, §20 arm 21's constant half: ``MAX_ASSOCIATION_CANDIDATES`` is 8.

    "It is not a ``Settings`` field, not a constructor knob and not a per-deployment
    value", on ADR-0086 §1's ground: "a knob that raises the ceiling is a knob that
    re-opens it".
    """
    from ai_assistant.core.config import Settings  # noqa: PLC0415 — asserted about

    assert MAX_ASSOCIATION_CANDIDATES == 8
    assert not [name for name in Settings.model_fields if "candidate" in name]


def test_a_candidate_set_is_held_to_the_cap_and_counts_what_it_dropped() -> None:
    """§2: at most the cap, and ``elided`` is a count and never an identifier.

    "A count and not a flag", on ADR-0086's own test: the writer here is the store
    answering ``candidates_for``, which holds the whole set and can count what it did
    not return, so a flag "would discard a magnitude the writer holds".
    """
    goals = tuple(_goal(f"g{n}") for n in range(1, MAX_ASSOCIATION_CANDIDATES + 1))
    full = GoalCandidates(goals=goals, elided=3)
    assert len(full.goals) == MAX_ASSOCIATION_CANDIDATES
    assert full.elided == 3

    assert GoalCandidates().goals == ()
    assert GoalCandidates().elided == 0

    with pytest.raises(ValidationError, match="carries at most"):
        GoalCandidates(goals=(*goals, _goal("g9")))
    with pytest.raises(ValidationError):
        GoalCandidates(elided=-1)


# --- §4: the candidacy, the verdict and the namer rule --------------------


def test_a_candidacy_carries_no_field_an_identifier_could_sit_in() -> None:
    """§20 arm 22(a), the structural half, over the two types' declared field sets.

    §4: "A ``GoalCandidacy`` carries **no identifier of any kind** — no ``goal_id``, no
    ``conversation_id``, no attempt id, no evidence id, no record id — and no instant,
    no revision number, no element, no ground, no plan, no effort figure and no
    authority. The containment is a property of the type: an implementation that
    rendered every field of every value it was handed, logged them all, or returned
    them, discloses none of those, because there is none on the value to disclose."

    Asserted over the **field sets** rather than over a rendering, which is what makes
    it a statement a later lane cannot quietly falsify: adding a field here fails this
    case before any prompt is written. The behavioural half — that the production
    associator's prompt contains neither string — is ADR-0250 §19's M2.
    """
    assert set(GoalCandidacy.model_fields) == {"request", "candidates", "elided", "focused"}
    assert set(CandidateGoal.model_fields) == {"outcome", "status"}

    for model in (GoalCandidacy, CandidateGoal):
        offending = [
            name
            for name in model.model_fields
            if re.search(r"(^|_)(id|ids|identifier)$", name) or name.endswith("_at")
        ]
        assert offending == [], f"{model.__name__} carries {offending}"


def test_a_candidacy_is_non_empty_and_within_the_cap() -> None:
    """§3, §4: no call is made over an empty set, and none exceeds the cap.

    "§3 makes no ``associate`` call over an empty candidate set", because a
    conversation with nothing to associate to opens a goal and costs no model call —
    so the value that would assert one is refused by the type rather than left for
    every caller to guard.
    """
    one = (CandidateGoal(outcome="book a campsite", status=GoalStatus.ACTIVE),)
    assert GoalCandidacy(request="make it Sunday", candidates=one).focused is None

    with pytest.raises(ValidationError, match="at least one candidate"):
        GoalCandidacy(request="make it Sunday", candidates=())
    with pytest.raises(ValidationError, match="at most"):
        GoalCandidacy(
            request="make it Sunday",
            candidates=one * (MAX_ASSOCIATION_CANDIDATES + 1),
        )


@pytest.mark.parametrize(
    ("verdict", "labels"),
    [
        (AssociationVerdict.ASSOCIATES, ("G1",)),
        (AssociationVerdict.FRESH, ()),
        (AssociationVerdict.CONTINUES, ()),
        (AssociationVerdict.UNDECIDED, ()),
        (AssociationVerdict.UNDECIDED, ("G1",)),
        (AssociationVerdict.UNDECIDED, ("G1", "G2", "G3")),
    ],
)
def test_the_association_admits_exactly_the_four_shapes(
    verdict: AssociationVerdict, labels: tuple[str, ...]
) -> None:
    """§4: ``ASSOCIATES`` with one label, ``FRESH`` and ``CONTINUES`` with none, and
    ``UNDECIDED`` with any number including none.
    """
    assert GoalAssociation(verdict=verdict, labels=labels).labels == labels


@pytest.mark.parametrize(
    ("verdict", "labels"),
    [
        (AssociationVerdict.ASSOCIATES, ()),
        (AssociationVerdict.ASSOCIATES, ("G1", "G2")),
        (AssociationVerdict.FRESH, ("G1",)),
        (AssociationVerdict.CONTINUES, ("G1",)),
    ],
)
def test_the_association_refuses_every_other_shape(
    verdict: AssociationVerdict, labels: tuple[str, ...]
) -> None:
    """§3, §4: "an ``ASSOCIATES`` carrying other than exactly one label" is undecided.

    A caller reads such an answer as ``UNDECIDED`` and asks, so the value that would
    *assert* the pick is refused here rather than normalised by every caller — "no
    implementation falls back to the focused goal, to the first candidate, to the most
    recent one, or to any tie-break at all".
    """
    with pytest.raises(ValidationError):
        GoalAssociation(verdict=verdict, labels=labels)


def test_the_verdict_vocabulary_is_closed_at_four() -> None:
    """§4: four members, each valued by its lower-cased name."""
    assert {one.value for one in AssociationVerdict} == {
        "associates",
        "fresh",
        "continues",
        "undecided",
    }


# --- §7: a raised question names what it is about -------------------------


def test_a_proposed_question_carries_its_text_and_optionally_its_subject() -> None:
    """§7: ``text`` and ``about``, and **no id, deadline, disposition or instant**.

    Every one of those is ``orchestration``'s (§6), and a planner envelope that comes
    back carrying one has it discarded silently — which the type makes structural.
    """
    assert set(ProposedQuestion.model_fields) == {"text", "about"}
    assert ProposedQuestion(text="which weekend?").about is None
    assert ProposedQuestion(text="which weekend?", about="C1").about == "C1"
    with pytest.raises(ValidationError):
        ProposedQuestion(text="  ")


def test_an_understanding_carries_proposed_questions_and_no_longer_bare_texts() -> None:
    """§7: the element type moves, and nothing else about the field does.

    "It is still carried, still the planner's, still unread by any ADR-0249 lane". A
    reader holding only ADR-0249 §7 builds bare strings, which after this decision does
    not construct — ADR-0070 §1's test on the supersession side.
    """
    understanding = ProposedUnderstanding(
        retains_outcome=True,
        criteria=(ProposedElement(retains="S1"),),
        questions=(ProposedQuestion(text="which weekend?", about="S1"),),
    )
    assert understanding.questions[0].about == "S1"
    assert ProposedUnderstanding(retains_outcome=True).questions == ()

    with pytest.raises(ValidationError):
        ProposedUnderstanding(retains_outcome=True, questions=("which weekend?",))  # type: ignore[arg-type]


# --- §8: the record, and the content that lives as long as the question ---


def test_an_open_question_carries_both_content_fields_and_no_settled_at() -> None:
    """§8: the first of exactly two shapes the validator admits."""
    question = _question()
    assert question.disposition is GoalQuestionDisposition.OPEN
    assert (question.text, question.about) == ("which campsite did you mean?", "the usual campsite")
    assert question.settled_at is None


@pytest.mark.parametrize("missing", ["text", "about"])
def test_an_open_question_missing_either_content_field_is_refused(missing: str) -> None:
    """§8: "an ``OPEN`` question carrying **both** content fields".

    ``about`` is "never absent on an ``OPEN`` question" because it is resolved from the
    recorded revision rather than from the proposal — "a statement in words in every
    case".
    """
    with pytest.raises(ValidationError, match="carries its text and its subject"):
        _question(**{missing: None})


@pytest.mark.parametrize(
    "disposition",
    [
        GoalQuestionDisposition.ANSWERED,
        GoalQuestionDisposition.WITHDRAWN,
        GoalQuestionDisposition.EXPIRED,
        GoalQuestionDisposition.SUPERSEDED,
    ],
)
def test_a_settled_question_keeps_its_facts_and_loses_its_content(
    disposition: GoalQuestionDisposition,
) -> None:
    """§8: the second shape, over each of the four terminal members.

    "A settled question keeps its facts and loses its content", and ``goal_id``
    **survives settlement** so that a late answer still reaches the goal (§11). The
    four are distinct acts with distinct meanings and no implementation treats any as a
    weaker form of another — so each is asserted rather than one standing for all.
    """
    settled = _question(text=None, about=None, disposition=disposition, settled_at=_LATER)
    assert (settled.text, settled.about) == (None, None)
    assert (settled.goal_id, settled.attempt_id) == ("g1", "a1")
    assert settled.settled_at == _LATER
    assert settled.expires_at == _WHEN + timedelta(hours=72), "the deadline is a fact, not content"

    with pytest.raises(ValidationError, match="loses its content"):
        _question(disposition=disposition, settled_at=_LATER)
    with pytest.raises(ValidationError, match="records when it was settled"):
        _question(text=None, about=None, disposition=disposition)


def test_an_open_question_carrying_a_settled_at_is_refused() -> None:
    """§8: nothing has settled it, so there is no instant to carry."""
    with pytest.raises(ValidationError, match="carries no settled_at"):
        _question(settled_at=_LATER)


def test_the_disposition_vocabulary_is_closed_at_five() -> None:
    """§8: ``OPEN`` and four terminal members, each lower-cased."""
    assert {one.value for one in GoalQuestionDisposition} == {
        "open",
        "answered",
        "withdrawn",
        "expired",
        "superseded",
    }


# --- §5: the four outcome members and the widened validator ---------------


def test_the_outcome_gains_four_none_defaulting_members() -> None:
    """§5: "one ``None``-defaulting member per fact", on ADR-0244 §9's own rule.

    "No member is derived from another and a client renders each on its own." The
    four come apart in the cases that actually occur, which is why collapsing any two
    is refused.
    """
    outcome = TurnOutcome(turn=None, step=None)
    for member in ("goal_engagement", "clarification", "reference", "disambiguation"):
        assert getattr(outcome, member) is None


def test_the_undecided_shape_is_admitted_and_is_the_only_one_carrying_a_disambiguation() -> None:
    """§5, §20 arm 11's type half: the one outcome shape this decision adds.

    "An ``UNDECIDED`` turn returns ``turn`` ``None``, a **non-``None`` ``reply``**,
    ``reply_degraded`` ``False`` and ``disambiguation`` set" — ADR-0170 §4's
    ``turn``-``None`` enumeration superseded in its count alone, which is ADR-0197 §8's
    move exactly. ``reply``'s three-shape enumeration does not move at all, because
    this turn carries one: a spoken request would otherwise be answered with silence
    (ADR-0200 §4).
    """
    asking = TurnOutcome(
        turn=None,
        step=None,
        reply="Did you mean the campsite booking, or is this something new?",
        disambiguation=GoalDisambiguation(candidates=("book a campsite",)),
    )
    assert asking.turn is None
    assert asking.reply_degraded is False
    assert asking.goal_engagement is None


@pytest.mark.parametrize(
    ("overrides", "refusal"),
    [
        ({"reply": None}, "must carry a reply"),
        ({"reply_degraded": True}, "cannot have degraded"),
        (
            {
                "clarification": Clarification(
                    question_id="q1", text="which campsite?", expires_at=_LATER
                )
            },
            "raised no question",  # the cross-cutting rule, not the undecided branch
        ),
        ({"reference": ReferenceOutcome.ANSWERED}, "unreachable here"),
        ({"reference": ReferenceOutcome.EXPIRED}, "unreachable here"),
        ({"reference": ReferenceOutcome.ALREADY_SETTLED}, "unreachable here"),
        (
            {
                "goal_engagement": GoalEngagement(
                    disposition=EngagementDisposition.OPENED, outcome="book a campsite"
                )
            },
            "engaged no goal",
        ),
        ({"step": _DROVE}, "drove no step"),
    ],
)
def test_the_undecided_shape_refuses_every_incoherent_variant(
    overrides: dict[str, object], refusal: str
) -> None:
    """§3, §5: what an undecided turn did not do, refused in both directions.

    It "opens no goal, records no revision, engages nothing, takes **no** relevance
    read, no episodic supplement and no ``Planner.plan`` call, drives no plan and
    produces no effect" — and **no implementation constructs a** ``GoalEngagement``
    **in order to carry a reference outcome**, because that value asserts a goal was
    engaged (§11).
    """
    fields: dict[str, object] = {
        "turn": None,
        "step": None,
        "reply": "Did you mean the campsite booking, or is this something new?",
        "disambiguation": GoalDisambiguation(candidates=("book a campsite",)),
    }
    with pytest.raises(ValidationError, match=refusal):
        TurnOutcome(**(fields | overrides))  # type: ignore[arg-type]


def test_an_undecided_turn_may_report_that_the_handle_it_was_given_resolved_to_nothing() -> None:
    """§11, §20 arm 32: ``UNKNOWN`` is the one reference outcome this shape admits.

    "**An ``UNKNOWN`` reference is reported whatever the association then does.** The
    turn falls through to §3 and is associated like any other, so it may come back
    ``UNDECIDED`` — an outcome carrying **no** ``goal_engagement`` (§5) — and
    ``reference`` is a member of its own precisely so that the user is still told the
    handle they gave resolved to nothing."

    This is the anti-vacuity half of the refusals above: without it, a validator that
    banned ``reference`` outright would pass every one of them and would forbid the one
    combination §11 exists to make expressible.
    """
    asking = TurnOutcome(
        turn=None,
        step=None,
        reply="I could not tell which goal that was about.",
        disambiguation=GoalDisambiguation(candidates=("book a campsite",)),
        reference=ReferenceOutcome.UNKNOWN,
    )

    assert asking.reference is ReferenceOutcome.UNKNOWN
    assert asking.goal_engagement is None, "and no engagement was constructed to hold it"


def test_no_pass_that_made_no_plan_can_carry_a_clarification() -> None:
    """§10, over **all three** shapes on which ``turn`` is ``None``.

    The ground is one fact rather than three: §6's first condition for putting a
    question is that the planner reported the ambiguity "on this call", and none of the
    three passes below makes a ``Planner.plan`` call at all — a recovered park persisted
    nothing to plan from, a routed pass ends the pipeline before planning, and an
    undecided turn takes no planner call because association precedes it.

    Driven as one case over the three because the rule is stated once. Fixing this
    shape by shape is what let the same class of gap survive two earlier rounds: the
    validator excluded the combination that had been pointed at and admitted the next
    one along.
    """
    clarification = Clarification(question_id="q1", text="which campsite?", expires_at=_LATER)
    routed = RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED)

    shapes: list[dict[str, object]] = [
        {"turn": None, "step": None},  # a recovered park
        {"turn": None, "routed": routed, "reply": "I forgot it."},  # a routed pass
        {
            "turn": None,
            "step": None,
            "reply": "Which of those did you mean?",
            "disambiguation": GoalDisambiguation(candidates=("book a campsite",)),
        },  # an undecided turn
    ]
    for shape in shapes:
        with pytest.raises(ValidationError, match="raised no question"):
            TurnOutcome(**(shape | {"clarification": clarification}))  # type: ignore[arg-type]
        assert TurnOutcome(**shape).clarification is None, (  # type: ignore[arg-type]
            "and the same shape without one is admitted exactly as before"
        )


def test_a_turn_that_raised_a_question_drove_no_step() -> None:
    """§10's other half: "drives no step of its plan and produces no effect".

    "The plan is persisted exactly as ADR-0228 §5 and ADR-0249 §11 already have it
    persisted; it is not driven, no execution is started, and no ``ToolCall`` is
    constructed." So an outcome carrying both a clarification and a driven step is
    describing a turn that declined to act and acted.
    """
    clarification = Clarification(question_id="q1", text="which campsite?", expires_at=_LATER)
    engagement = GoalEngagement(
        disposition=EngagementDisposition.CONTINUED, outcome="book a campsite"
    )

    with pytest.raises(ValidationError, match="never both"):
        TurnOutcome(
            turn=_PLANNED,
            step=_DROVE,
            reply="Booked it.",
            clarification=clarification,
            goal_engagement=engagement,
        )

    assert (
        TurnOutcome(
            turn=_PLANNED,
            step=None,
            reply="Which campsite did you mean?",
            clarification=clarification,
            goal_engagement=engagement,
        ).clarification
        is clarification
    ), "and a turn that planned and drove nothing carries one"


def test_a_clarification_is_about_the_goal_the_outcome_names() -> None:
    """§10: a :class:`Clarification` "carries no goal id, no attempt id, no subject and
    no disposition … and the goal is what ``goal_engagement`` names".

    So the one member that was to name the question's goal saying nothing leaves the
    question unattributable — a durable pause on a goal no reader of the outcome can
    identify — and the type refuses it rather than documenting it, which is
    :meth:`StepOutcome._confirmation_matches_disposition`'s own posture.

    **``revised`` is deliberately not tested**, and the anti-vacuity half below is what
    pins that. §5 rules that "no member is derived from another and a client renders
    each on its own", and that "``revised`` says a revision was recorded, and nothing
    more"; a validator computing this member's admissibility from that flag would be
    exactly the derivation the clause forbids. That a raising turn will in practice
    also have recorded a revision is a property of the loop §19's M3 writes, not a
    shape this type closes.
    """
    clarification = Clarification(question_id="q1", text="which campsite?", expires_at=_LATER)

    with pytest.raises(ValidationError, match="unattributable"):
        TurnOutcome(
            turn=_PLANNED,
            step=None,
            reply="Which campsite did you mean?",
            clarification=clarification,
        )

    unrevised = TurnOutcome(
        turn=_PLANNED,
        step=None,
        reply="Which campsite did you mean?",
        clarification=clarification,
        goal_engagement=GoalEngagement(
            disposition=EngagementDisposition.CONTINUED, outcome="book a campsite", revised=False
        ),
    )
    assert unrevised.clarification is clarification, (
        "and an engagement that recorded no revision is admitted beside one: §5 forbids "
        "deriving this member from that flag"
    )


def test_a_routed_pass_carries_no_engagement_either() -> None:
    """§5: ``goal_engagement`` is ``None`` "on an outcome that engaged none".

    That clause names three shapes and the type can see two of them. A **routed
    operation** is the first, and it is structural rather than a convention: ADR-0197
    §7 ends the pipeline where it routed, before any association runs, so there is no
    goal to engage — an outcome claiming both that a route ended the pass *and* that a
    goal was opened is describing two passes, which is the same thing §8 already
    refuses of a route beside a driven step.

    The third shape §5 names, ADR-0198 §1's restated settled binding, is **not**
    asserted here and cannot be: a restatement is not distinguishable from this type's
    members, so it stays a rule about the site that builds one.
    """
    engagement = GoalEngagement(disposition=EngagementDisposition.OPENED, outcome="book a campsite")

    with pytest.raises(ValidationError, match="routed pass engaged no goal"):
        TurnOutcome(
            turn=None,
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED
            ),
            reply="I forgot it.",
            goal_engagement=engagement,
        )

    assert (
        TurnOutcome(
            turn=None,
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED
            ),
            reply="I forgot it.",
        ).goal_engagement
        is None
    ), "and the same outcome without one is exactly what ADR-0197 §8 admits"


def test_a_disambiguation_names_at_least_one_goal() -> None:
    """§5: "the tuple is therefore non-empty on every ``UNDECIDED`` turn".

    "It may hold exactly **one**, which is a well-formed question — *is this about
    that, or is it something new?* — and not a degraded one."
    """
    assert GoalDisambiguation(candidates=("book a campsite",)).elided == 0
    assert set(GoalDisambiguation.model_fields) == {"candidates", "elided"}
    with pytest.raises(ValidationError, match="at least one goal"):
        GoalDisambiguation(candidates=())


# --- §5: the engagement, and what it says moved ---------------------------


def test_a_turn_that_recorded_no_revision_moved_no_word() -> None:
    """§5: the invariant's first half, over every combination.

    "Where ``revised`` is ``False``, ``outcome_changed`` is ``False`` and ``added`` and
    ``removed`` are both empty."
    """
    engagement = GoalEngagement(
        disposition=EngagementDisposition.CONTINUED, outcome="book a campsite"
    )
    assert (engagement.revised, engagement.outcome_changed) == (False, False)
    assert (engagement.added, engagement.removed) == ((), ())

    for moved in ({"outcome_changed": True}, {"added": ("a budget",)}, {"removed": ("Saturday",)}):
        with pytest.raises(ValidationError, match="moved no word"):
            GoalEngagement(
                disposition=EngagementDisposition.CONTINUED,
                outcome="book a campsite",
                **moved,
            )


def test_a_grounding_only_revision_constructs() -> None:
    """§5, §20 arm 16's type half: ``revised`` ``True`` with all three empty.

    "That shape is a revision that changed no words at all, and it is **reachable and
    legitimate** — a planner that restates the same constraint text with a
    ``USER_STATED`` ground where the previous revision held an ``INFERRED`` one has
    changed the interpretation's **grounding** and nothing a reader would read.
    ADR-0249 §7 permits that revision in terms, and no clause here declares it
    invalid." The arm fails if the revision is refused, which is what this pins.
    """
    engagement = GoalEngagement(
        disposition=EngagementDisposition.CONTINUED, outcome="book a campsite", revised=True
    )
    assert engagement.revised is True
    assert (engagement.outcome_changed, engagement.added, engagement.removed) == (False, (), ())


def test_a_revision_that_moved_a_word_says_which() -> None:
    """§5: ``added`` and ``removed`` are the trace of a change, and ``removed`` is
    what keeps an omission from being silent.

    ADR-0249 §7 makes omission the whole of the removal mechanism, "so a revision whose
    only effect is to drop the user's stated budget is a revision whose only trace is
    an absence" — this member is that trace.
    """
    engagement = GoalEngagement(
        disposition=EngagementDisposition.RESUMED,
        outcome="book a campsite on Monday",
        revised=True,
        outcome_changed=True,
        added=("on Monday",),
        removed=("on Saturday",),
    )
    assert engagement.added == ("on Monday",)
    assert engagement.removed == ("on Saturday",)
    assert set(GoalEngagement.model_fields) == {
        "disposition",
        "outcome",
        "revised",
        "outcome_changed",
        "added",
        "removed",
    }, "no goal id, no attempt id, no revision number, no label, no ground and no instant"


def test_the_engagement_vocabularies_are_closed() -> None:
    """§5, §11, §12: four dispositions, four reference outcomes, and the two acts'."""
    assert {one.value for one in EngagementDisposition} == {
        "opened",
        "continued",
        "resumed",
        "reopened",
    }
    assert {one.value for one in ReferenceOutcome} == {
        "unknown",
        "answered",
        "expired",
        "already_settled",
    }
    assert {one.value for one in ClarificationWithdrawal} == {"withdrawn", "nothing_to_withdraw"}
    assert {one.value for one in GoalAbandonment} == {
        "abandoned",
        # ADR-0261 §6's fourth member, closing the vocabulary there: the act reports
        # which of the two things it did — gave the goal up, or gave it up with an
        # action of it already claimed — on ADR-0244 §11's own construction, so the
        # discrimination sits where the atomicity already is.
        "abandoned_effect_in_flight",
        "already_closed",
        "no_such_goal",
    }


# --- §§10-11: the clarification and the reference -------------------------


def test_a_clarification_carries_the_id_the_text_and_the_deadline_and_nothing_else() -> None:
    """§10: "no goal id, no attempt id, no subject and no disposition".

    "The subject is what the question text is about and the user reads it there, and
    the goal is what ``goal_engagement`` names."
    """
    assert set(Clarification.model_fields) == {"question_id", "text", "expires_at"}
    clarification = Clarification(question_id="q1", text="which campsite?", expires_at=_LATER)
    assert clarification.question_id == "q1"


@pytest.mark.parametrize("fields", [{"question_id": "q1"}, {"goal_id": "g1"}])
def test_a_reference_names_exactly_one_record(fields: dict[str, str]) -> None:
    """§11: "a ``question_id`` and no ``goal_id``, or a ``goal_id`` and no
    ``question_id``".

    "A shape a caller cannot reach is better refused by the type than documented",
    which is ADR-0244 §9's own reason for refusing its two members together.
    """
    reference = TurnReference(**fields)
    assert [name for name, value in reference.model_dump().items() if value is not None] == list(
        fields
    )


@pytest.mark.parametrize("fields", [{}, {"question_id": "q1", "goal_id": "g1"}])
def test_a_reference_naming_both_records_or_neither_is_refused(fields: dict[str, str]) -> None:
    """§11: exactly two shapes, and these are the two that are not them."""
    with pytest.raises(ValidationError, match="names one record"):
        TurnReference(**fields)


# --- §15: the listing the user learns a reference from --------------------


def test_a_goal_summary_carries_no_attempt_and_no_element() -> None:
    """§15: "no attempt id, no revision number, no element, no ground, no evidence
    reference and no plan", and ``paused`` is computed by the engine and never stored.

    **``effect_in_flight`` is the one addition and it is added *under* that rule**
    (ADR-0261 §6): a ``bool`` is none of the six things §15 refuses, and it takes
    ``paused``'s own clause one fact over — computed per read, never stored, computed
    by the engine so two surfaces cannot render it differently, and derived by no
    adapter.
    """
    assert set(GoalSummary.model_fields) == {
        "id",
        "outcome",
        "status",
        "paused",
        "last_engaged_at",
        "clarification",
        "effect_in_flight",
    }
    summary = GoalSummary(
        id="g1",
        outcome="book a campsite",
        status=GoalStatus.ACTIVE,
        paused=True,
        last_engaged_at=_LATER,
        clarification=Clarification(question_id="q1", text="which campsite?", expires_at=_LATER),
    )
    assert summary.paused is True
    assert summary.clarification is not None
    assert (
        GoalSummary(id="g2", outcome="file the tax return", status=GoalStatus.ACHIEVED).paused
        is False
    )


# --- §§9, 12, 13: what this lane deliberately writes nowhere --------------


def test_achieved_has_one_producer_and_blocked_still_has_none() -> None:
    """§20 arm 23's permanent half, asserted over the shipped tree.

    The arm reads in full: "the only assignment of ``GoalStatus.ABANDONED`` under
    ``src/`` is ``abandon_goal``'s, the only ``ACTIVE`` one is the reopen path's, both
    go through ``set_goal_status``, and **no** assignment of ``GoalStatus.ACHIEVED`` or
    ``GoalStatus.BLOCKED`` exists anywhere — asserted as a test over the tree, not as a
    review convention, so that a later lane cannot supply one without the ADR that
    decides it."

    ``ACHIEVED`` is A10's and ``BLOCKED`` is A3's, and §12 rules that neither "gains a
    producer here" — *here* being ADR-0250's own lane. **A10 has now landed, so the arm
    narrows rather than being dropped**, which is what its own closing clause asks for:
    a later lane may not supply a producer *"without the ADR that decides it"*, and
    ADR-0262 §5 is that ADR. It rules that ``GoalStatus.ACHIEVED`` has **exactly one**
    producer — ``orchestration``'s ``VERIFY`` phase, on §4's limb 5 alone, immediately
    after the ``commit_attempt`` that ended the attempt — and that *"no expiry, no
    silence, no timeout, no sweep, no reclaim, no model output, no inference and no
    other member of any Protocol writes ``ACHIEVED``"*. So the assertion becomes **that
    one site and no other**, on the same narrowing the two cases below already took for
    ``ACTIVE`` and ``ABANDONED``.

    **``BLOCKED`` is untouched and stays at zero**: it is A3's, no lane has landed it,
    and §5 binds on ``ACHIEVED`` alone.

    **What it is stated over narrowed when ADR-0250 §19's M3 landed.** M1 could assert
    the two members were not *named* anywhere, because nothing read them; §1's own
    definition of an open goal — "a goal is **open** where its ``GoalStatus`` is
    ``ACTIVE`` or ``BLOCKED``" — puts ``BLOCKED`` in a membership test that M3 must
    build, and a mention is not a producer. So the test is over the **write** form, the
    same one :func:`test_status_has_two_writers_and_they_are_the_two_acts_arm_23_names`
    counts, and an ``ACHIEVED`` or ``BLOCKED`` status reaching a record is what it
    refuses.
    """
    achieved = sorted(
        f"{path.relative_to(_SRC)}"
        for path in _SRC.rglob("*.py")
        for line in path.read_text().splitlines()
        if re.search(r'(?:\bstatus=|"status":\s*)GoalStatus\.ACHIEVED\b', line)
    )
    blocked = sorted(
        f"{path.relative_to(_SRC)}:{number}"
        for path in _SRC.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if re.search(r'(?:\bstatus=|"status":\s*)GoalStatus\.BLOCKED\b', line)
    )
    assert achieved == ["ai_assistant/orchestration/engine.py"], (
        "ADR-0262 §5: GoalStatus.ACHIEVED has exactly one producer — the VERIFY "
        f"phase's own act, on §4's limb 5 alone. Found: {achieved}"
    )
    assert blocked == [], (
        "ADR-0250 §12: GoalStatus.BLOCKED gains no producer here (A3's, by ADR-0249 "
        f"§4's own words). Found: {blocked}"
    )


def test_status_has_two_callers_and_one_store_member_that_writes_abandoned() -> None:
    """§20 arm 23's first two limbs, over the shipped tree, as ADR-0261 §2 leaves them.

    **This case replaces M1's, which pinned the same fact at zero.** That lane changed
    no behaviour and so had no caller at all; ADR-0250 §19's M3 supplied exactly the two
    §12 and §13 name — the reopen writes ``ACTIVE``, ``abandon_goal`` writes
    ``ABANDONED`` — and the assertion narrowed from "none" to "these two and no others"
    rather than being dropped.

    **ADR-0261 §2 moves the abandonment's write and the arm narrows again rather than
    widening loosely.** ``PlanStore.close_goal_abandoned`` "**ends a goal's live
    attempts, writes ``ABANDONED`` and returns that same predicate, all in one
    indivisible step**", which is that decision partially superseding ADR-0250 §9's
    sole-route phrase **in the ``ABANDONED`` member alone**; ``ACHIEVED``, ``BLOCKED``
    and ``ACTIVE`` keep ``set_goal_status`` as their only route. So each conforming
    ``PlanStore`` writes the member once, **inside that member's own body and nowhere
    else** — which is what this arm pins, rather than merely counting three more lines
    — and the **engine writes it no longer**: ``_abandon_goal`` takes the new member,
    so ``orchestration`` keeps exactly one literal status write, §13's reopen.

    **The count of *acts* is unchanged and that is the point**: ``abandon_goal`` is
    still the only thing in this system that writes ``ABANDONED``, and what moved is
    which member it takes to write it.

    The **write** form is what is counted — a ``status=GoalStatus.…`` argument or a
    ``"status": GoalStatus.…`` entry — deliberately distinct from the **declaration**
    ``Goal.status`` and ``CandidateGoal.status`` each carry as a field default, and from
    the membership test §1's "open" definition needs.
    """
    writes = sorted(
        (str(path.relative_to(_SRC)), line.strip())
        for path in _SRC.rglob("*.py")
        for line in path.read_text().splitlines()
        if re.search(r'(?:\bstatus=|"status":\s*)GoalStatus\.', line)
    )
    assert [where for where, _ in writes] == [
        "ai_assistant/orchestration/engine.py",
        "ai_assistant/orchestration/engine.py",
        "ai_assistant/planning/sqlite_store.py",
        "ai_assistant/planning/store.py",
        "ai_assistant/testing/planning.py",
    ], (
        "ADR-0250 §20 arm 23 with ADR-0261 §2 and ADR-0262 §5: the reopen and the "
        "`ACHIEVED` write are `orchestration`'s and each conforming store writes "
        f"ABANDONED once of its own. Found: {writes}"
    )
    assert sorted(what for _, what in writes) == [
        "status=GoalStatus.ACHIEVED,",
        "status=GoalStatus.ACTIVE,",
        'update={"status": GoalStatus.ABANDONED, "version": stored.version + 1}',
        "updated = _with_status(stored, status=GoalStatus.ABANDONED)",
        "updated = _with_status(stored, status=GoalStatus.ABANDONED)",
    ], (
        "and they are the reopen (§13), ADR-0262 §5's one producer, and the three "
        f"stores' one closing write each (ADR-0261 §2). Found: {writes}"
    )
    assert _enclosing_functions_writing_the_status() == {
        # ADR-0262 §5's one producer sits beside the reopen and in its own act, which
        # is what "`GoalStatus.ACHIEVED` has exactly one producer and it is the act
        # below" is asserted as here: one function, named for what it writes.
        "ai_assistant/orchestration/engine.py": {"_engaged", "_achieved"},
        "ai_assistant/planning/sqlite_store.py": {"_close_goal_abandoned_sync"},
        "ai_assistant/planning/store.py": {"close_goal_abandoned"},
        "ai_assistant/testing/planning.py": {"close_goal_abandoned"},
    }, "and each store's write sits inside `close_goal_abandoned` and nowhere else"


def _enclosing_functions_writing_the_status() -> dict[str, set[str]]:
    """Which function each ``GoalStatus`` status write under ``src/`` sits in.

    Read from the syntax tree, so "inside ``close_goal_abandoned``" is a fact about
    where the write is rather than about which lines happen to be near it.

    Returns:
        One entry per file holding such a write, naming the enclosing functions.
    """
    found: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for enclosing in ast.walk(tree):
            if not isinstance(enclosing, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if any(_writes_a_status(node) for node in ast.walk(enclosing)):
                found.setdefault(str(path.relative_to(_SRC)), set()).add(enclosing.name)
    return found


def _writes_a_status(node: ast.AST) -> bool:
    """Whether ``node`` is a ``status=GoalStatus.…`` keyword or mapping entry."""
    if isinstance(node, ast.keyword):
        return node.arg == "status" and _is_a_goal_status(node.value)
    if isinstance(node, ast.Dict):
        return any(
            isinstance(key, ast.Constant) and key.value == "status" and _is_a_goal_status(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    return False


def _is_a_goal_status(node: ast.expr) -> bool:
    """Whether ``node`` is a literal ``GoalStatus`` member access."""
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "GoalStatus"
    )


def test_the_two_closing_acts_have_exactly_one_caller_each() -> None:
    """§20 arm 23 counted from the **callers**, not from the literals they pass.

    The two cases above count occurrences of ``status=GoalStatus.…``. That is the right
    subject for "which statuses are written", and the wrong one for "how many writers
    there are": a call passing a *name* — ``set_goal_status(..., status=chosen)`` —
    carries no literal to count and would satisfy both. §12 and §13 name exactly two
    acts, so the population this arm is really about is the **call sites**.

    **Since ADR-0261 §2 the two acts take two different members**, and the arm counts
    both rather than one: the reopen (§13) takes ``set_goal_status``, and the
    abandonment (§12) takes ``close_goal_abandoned``, which writes ``ABANDONED`` and
    ends the goal's live attempts in one indivisible step. **Exactly one caller each,
    both in ``orchestration/engine.py``** — a second caller of either would be a second
    act writing a closed status, which is what arm 23 exists to refuse.

    Counted from the syntax tree: every call under ``src/`` whose callee is either
    member. The reopen's must carry a literal ``GoalStatus`` attribute as its
    ``status``; the abandonment's carries none, the member naming its own.
    """
    callers = sorted(
        (str(path.relative_to(_SRC)), _status_argument(node))
        for path in _SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "set_goal_status"
    )
    closers = sorted(
        str(path.relative_to(_SRC))
        for path in _SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close_goal_abandoned"
    )
    assert closers == ["ai_assistant/orchestration/engine.py"], (
        f"ADR-0261 §2: the abandoning act is the one caller of the closing member. Found: {closers}"
    )
    assert [where for where, _ in callers] == [
        "ai_assistant/orchestration/engine.py",
        "ai_assistant/orchestration/engine.py",
    ], (
        "ADR-0250 §20 arm 23 with ADR-0262 §5: two callers of the status route, the "
        f"reopen and `ACHIEVED`'s one producer. Found: {callers}"
    )
    assert sorted(what for _, what in callers) == ["ACHIEVED", "ACTIVE"], (
        "and each names its member outright, so that no call can carry a status decided "
        f"somewhere this test cannot read. Found: {callers}"
    )


def _status_argument(call: ast.Call) -> str:
    """The ``GoalStatus`` member a ``set_goal_status`` call names, or why it names none."""
    for keyword in call.keywords:
        if keyword.arg != "status":
            continue
        value = keyword.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id == "GoalStatus"
        ):
            return value.attr
        return f"not a GoalStatus literal: {ast.dump(value)}"
    return "no status keyword at all"


def test_no_forbidden_status_is_carried_anywhere_a_write_could_reach() -> None:
    """§20 arm 23's permanent half, closed against propagation as well as assignment.

    ``GoalStatus.ACHIEVED`` is A10's and ``GoalStatus.BLOCKED`` is A3's, and §12 rules
    that neither *"gains a producer here"*. A test over the ``status=GoalStatus.…`` write
    form alone leaves one route open: bind the member to a name, then pass the name.

    So the two members may appear under ``src/`` **only** in a position that reads them
    — a comparison, a membership test, a ``match`` — and never as a call argument or as
    the value of an assignment, which are the two ways a value travels to a writer. §1's
    own definition of an open goal (*"``ACTIVE`` or ``BLOCKED``"*) is a read and is
    untouched by this.

    **A10 has landed, so the propagation half narrows with the assignment half.**
    ADR-0262 §5 gives ``ACHIEVED`` exactly one producer, and the ``status=`` keyword of
    that one ``set_goal_status`` call is the one position the member may travel
    through — asserted as that exact site rather than as a count, so a second route
    still fails here. **``BLOCKED`` stays at zero**, §5 binding on ``ACHIEVED`` alone.
    """
    # The **member** rather than the line, so the assertion pins which of the two
    # travelled and where, and survives an edit that moves the site by a line.
    carried = sorted(
        f"{path.relative_to(_SRC)}:{value.attr}"
        for path in _SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        for value in _values_that_travel(node)
        if isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "GoalStatus"
        and value.attr in {"ACHIEVED", "BLOCKED"}
    )
    assert carried == ["ai_assistant/orchestration/engine.py:ACHIEVED"], (
        "ADR-0262 §5: ACHIEVED travels exactly once, into the `set_goal_status` call of "
        "its one producer; ADR-0250 §12: BLOCKED is A3's and may not travel at all — a "
        f"member that can travel can reach a writer. Found: {carried}"
    )


def _values_that_travel(node: ast.AST) -> tuple[ast.expr, ...]:
    """The expressions of ``node`` that hand a value somewhere else."""
    if isinstance(node, ast.Call):
        return (*node.args, *(keyword.value for keyword in node.keywords))
    if isinstance(node, ast.Assign):
        return (node.value,)
    if isinstance(node, ast.AnnAssign | ast.AugAssign) and node.value is not None:
        return (node.value,)
    return ()


def test_every_status_write_a_caller_takes_goes_through_set_goal_status() -> None:
    """§20 arm 23's third limb: "**both go through ``set_goal_status``**".

    Read from the syntax tree rather than by proximity, so a later lane cannot satisfy
    it by putting the argument near a call it is not an argument to: every
    ``status=GoalStatus.…`` keyword **a caller** writes under ``src/`` must sit on a
    call whose callee is ``set_goal_status``, which §9 makes "the goal's **only**
    status-mutation route".

    **The stores' own closing write is excluded by name and not by a widened rule**
    (ADR-0261 §2). ``close_goal_abandoned`` is a ``PlanStore`` member, so it *is* the
    route rather than a caller taking one, and it writes ``ABANDONED`` **because**
    ``set_goal_status`` cannot return R78's outstanding-effect answer computed in the
    same step and a read beside it cannot do so correctly. The arm above pins those
    three writes to that one member's body; anything else, in any file, is still a
    second writer and fails here.
    """
    inside_the_closing_member = {
        "ai_assistant/planning/sqlite_store.py",
        "ai_assistant/planning/store.py",
        "ai_assistant/testing/planning.py",
    }
    astray = sorted(
        f"{path.relative_to(_SRC)}:{node.lineno}"
        for path in _SRC.rglob("*.py")
        if str(path.relative_to(_SRC)) not in inside_the_closing_member
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and any(
            keyword.arg == "status"
            and isinstance(keyword.value, ast.Attribute)
            and isinstance(keyword.value.value, ast.Name)
            and keyword.value.value.id == "GoalStatus"
            for keyword in node.keywords
        )
        and not (isinstance(node.func, ast.Attribute) and node.func.attr == "set_goal_status")
    )
    assert astray == [], (
        "ADR-0250 §9: `set_goal_status` is the goal's only status-mutation route for a "
        f"caller, so a status written through any other call is a second writer. Found: {astray}"
    )
