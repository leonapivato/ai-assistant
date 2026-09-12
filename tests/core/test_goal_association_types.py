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
    AssociationVerdict,
    CandidateGoal,
    Clarification,
    ClarificationWithdrawal,
    Disposition,
    EngagementDisposition,
    ExecutionState,
    Goal,
    GoalAbandonment,
    GoalAssociation,
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
    StepExecution,
    StepOutcome,
    TurnOutcome,
    TurnReference,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_LATER = _WHEN + timedelta(hours=1)
_PROV = Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_WHEN)

#: The repository root, for the one case that reads the shipped tree rather than a
#: value (§20 arm 23's half this lane can decide).
_SRC: Final = Path(__file__).resolve().parents[2] / "src"

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
    """
    assert set(GoalSummary.model_fields) == {
        "id",
        "outcome",
        "status",
        "paused",
        "last_engaged_at",
        "clarification",
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


def test_neither_achieved_nor_blocked_is_named_in_code_anywhere_under_src() -> None:
    """§20 arm 23's permanent half, asserted over the shipped tree.

    The arm reads in full: "the only assignment of ``GoalStatus.ABANDONED`` under
    ``src/`` is ``abandon_goal``'s, the only ``ACTIVE`` one is the reopen path's, both
    go through ``set_goal_status``, and **no** assignment of ``GoalStatus.ACHIEVED`` or
    ``GoalStatus.BLOCKED`` exists anywhere — asserted as a test over the tree, not as a
    review convention, so that a later lane cannot supply one without the ADR that
    decides it."

    This case is the half that holds **forever**: ``ACHIEVED`` is A10's, ``BLOCKED``
    is A3's, and §12 rules that neither "gains a producer here". The first two limbs
    are narrowed to their one caller each by ADR-0250 §19's M3 — in this lane they have
    **no** caller, which the case below pins instead.

    Read from the **abstract syntax tree** rather than by grepping lines, which is what
    keeps it honest: the two members are named in this decision's own prose in
    ``core/protocols.py``, and a line-based scan would either flag that or would need a
    docstring heuristic that a later paragraph could slip past. An attribute access is
    a fact about the code.
    """
    named = sorted(
        f"{path.relative_to(_SRC)}:{node.lineno} — GoalStatus.{node.attr}"
        for path in _SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "GoalStatus"
        and node.attr in {"ACHIEVED", "BLOCKED"}
    )
    assert named == [], (
        "ADR-0250 §12: GoalStatus.ACHIEVED gains no producer here (A10's, and the "
        "owner's correction 2) and GoalStatus.BLOCKED gains none either (A3's, by "
        f"ADR-0249 §4's own words). Found: {named}"
    )


def test_this_lane_writes_no_status_at_all() -> None:
    """§19: "**No behaviour changes in M1**", read over the one write §9 adds.

    ``set_goal_status`` is "the goal's **only** status-mutation route", and this lane
    supplies the route without calling it: the two acts that do are the reopen (§13)
    and ``abandon_goal`` (§12), both ADR-0250 §19's M3. So no ``status=GoalStatus.…``
    argument and no ``"status": GoalStatus.…`` entry exists under ``src/`` — a *write*
    form, deliberately distinct from the **declaration** ``Goal.status`` and
    ``CandidateGoal.status`` each carry as a field default, which is not one.

    **M3 replaces this case rather than deleting it**, narrowing it to the two callers
    §20 arm 23 names, and until then it is what stops a status write arriving in a lane
    whose ADR did not decide one.
    """
    writes = sorted(
        f"{path.relative_to(_SRC)}:{number}"
        for path in _SRC.rglob("*.py")
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if re.search(r'(?:\bstatus=|"status":\s*)GoalStatus\.', line)
    )
    assert writes == [], (
        "ADR-0250 §19's M1 changes no behaviour, so it writes no GoalStatus: the reopen "
        f"path and abandon_goal are M3's. Found: {writes}"
    )
