"""ADR-0249 §7's ground resolution and its refusals, at the one place they live.

``orchestration`` **refuses a ground it cannot resolve**, and
:func:`~ai_assistant.orchestration.interpretation.recorded_revision` is where that
refusal is taken. What lives here is every arm of §16 that is a statement about the
resolution itself — item 5's four refusals, item 21's minted record, item 23's retained
constraint, item 24's omission and invented label, and item 27's retained outcome over
both an authored and a migrated revision 1. The turn-shaped arms are
``test_loop_understanding.py`` and the attempt-shaped ones ``test_engine_attempts.py``.

**Driven against a ``Goal`` a case builds rather than against a turn**, because the
question each arm asks is "what does this proposal resolve to against *this* current
interpretation and *this* supply" — and a turn is one particular answer to that, not the
rule. §16 item 23's *"the current brief the next call receives still shows the budget"*
is asserted through :meth:`~ai_assistant.core.types.GoalBrief.of`, which is the one
projection site in the system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from test_loop_reads import _belief

from ai_assistant.core.types import (
    Goal,
    GoalBrief,
    GoalElement,
    GoalInterpretation,
    Ground,
    MemorySource,
    ProposedElement,
    ProposedUnderstanding,
    Provenance,
)
from ai_assistant.orchestration.interpretation import recorded_revision

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord

_NOW: Final = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
_LATER: Final = datetime(2026, 9, 2, 11, 0, tzinfo=UTC)

#: The turn ADR-0249 §16 items 23 and 27 both run over. The correction's own words are
#: what a ``USER_STATED`` span must be a span of; the *first* turn's words are not.
_ASKED: Final = "actually, make it Sunday"
_FIRST_ASKED: Final = "book a campsite, under $100"


def _goal(current: GoalInterpretation, *, earlier: Sequence[GoalInterpretation] = ()) -> Goal:
    """A goal whose history ends at ``current``."""
    return Goal(
        id="goal-1",
        conversation_id="c-1",
        interpretation=(*earlier, current),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_NOW),
        created_at=_NOW,
        last_engaged_at=_NOW,
    )


def _opened(**fields: object) -> GoalInterpretation:
    """Revision 1 as ADR-0249 §3 mints one: the request, grounded on itself."""
    return GoalInterpretation(
        revision=1,
        outcome=_FIRST_ASKED,
        outcome_ground=Ground.USER_STATED,
        outcome_span=_FIRST_ASKED,
        recorded_at=_NOW,
        raised_by="turn-1",
        **fields,  # type: ignore[arg-type]  # one keyword per field a case varies
    )


def _budget() -> GoalElement:
    """The constraint §16 item 23 asks be carried forward byte for byte."""
    return GoalElement(text="under $100", ground=Ground.USER_STATED, span="under $100")


def _revised(
    understanding: ProposedUnderstanding,
    *,
    goal: Goal | None = None,
    utterance: str = _ASKED,
    supply: Sequence[MemoryRecord] = (),
    minted: Sequence[str] = (),
) -> GoalInterpretation:
    """Resolve ``understanding`` against ``goal``, with this lane's own stamps."""
    return recorded_revision(
        goal if goal is not None else _goal(_opened()),
        understanding,
        utterance=utterance,
        supply=supply,
        minted=minted,
        recorded_at=_LATER,
        raised_by="turn-2",
    )


# --------------------------------------------------------------------------- #
# §16 item 5 — ground resolution and its refusals, element and outcome         #
# --------------------------------------------------------------------------- #


def test_an_element_whose_evidence_label_is_outside_the_shown_set_is_dropped() -> None:
    """§7: dropped, silently, with the revision's outcome still recorded.

    "An element whose ground does not resolve — a label outside the shown set … — is
    **dropped from the recorded revision**, silently and without failing the turn,
    exactly as ADR-0226 §3 drops a label outside the shown set."
    """
    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(
                ProposedElement(
                    text="the site must allow dogs",
                    ground=Ground.FROM_EVIDENCE,
                    evidence_label="M4",
                ),
            ),
        ),
        supply=[_belief("m-1", "the user has a dog")],
    )

    assert revision.constraints == (), "M4 names no record of a one-record supply"
    assert revision.outcome == _FIRST_ASKED, "§7: an outcome is never dropped with its elements"
    assert revision.revision == 2


def test_an_element_whose_span_is_not_a_span_of_this_turns_request_is_dropped() -> None:
    """§7, §16 item 5's second refusal, and the reason retention exists.

    The budget's own span is in the **first** turn's request, so a planner restating it
    as ``USER_STATED`` on this turn is naming a span this turn does not contain.
    """
    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(
                ProposedElement(text="under $100", ground=Ground.USER_STATED, span="under $100"),
            ),
        )
    )

    assert revision.constraints == ()
    assert revision.outcome == _FIRST_ASKED


def test_an_outcome_whose_ground_does_not_resolve_is_recorded_inferred() -> None:
    """§7: recorded ``INFERRED`` with neither argument **rather than dropped**.

    "A revision without an outcome is not a revision at all", so the outcome takes the
    one refusal its elements do not.
    """
    by_label = _revised(
        ProposedUnderstanding(
            outcome="find a dog-friendly campsite",
            outcome_ground=Ground.FROM_EVIDENCE,
            outcome_evidence_label="M9",
        ),
        supply=[_belief("m-1", "the user has a dog")],
    )
    by_span = _revised(
        ProposedUnderstanding(
            outcome="find a dog-friendly campsite",
            outcome_ground=Ground.USER_STATED,
            outcome_span="a dog-friendly campsite",
        )
    )

    for revision in (by_label, by_span):
        assert revision.outcome == "find a dog-friendly campsite", "the statement is kept"
        assert revision.outcome_ground is Ground.INFERRED
        assert revision.outcome_evidence_id is None
        assert revision.outcome_span is None


def test_a_resolving_ground_is_stamped_with_what_this_package_resolved_it_to() -> None:
    """§7: the stamped values are identifiers and spans **this** side resolved.

    An ``M`` label becomes "the identifier of the record the loop itself labelled", and a
    span becomes the span checked against this turn's own request. No identifier crossed
    the seam in either direction (ADR-0228 §8).
    """
    revision = _revised(
        ProposedUnderstanding(
            outcome="book a campsite for Sunday",
            outcome_ground=Ground.USER_STATED,
            outcome_span="Sunday",
            constraints=(
                ProposedElement(
                    text="the site must allow dogs",
                    ground=Ground.FROM_EVIDENCE,
                    evidence_label="M2",
                ),
            ),
            criteria=(ProposedElement(text="a booking reference exists", ground=Ground.INFERRED),),
        ),
        supply=[_belief("m-1", "lives in Leeds"), _belief("m-2", "the user has a dog")],
    )

    assert revision.outcome_ground is Ground.USER_STATED
    assert revision.outcome_span == "Sunday"
    (constraint,) = revision.constraints
    assert constraint.evidence_id == "m-2", "the record at 1-based index 2 of this call's supply"
    assert constraint.span is None
    (criterion,) = revision.criteria
    assert criterion.ground is Ground.INFERRED
    assert (criterion.evidence_id, criterion.span) == (None, None)


def test_a_blank_span_resolves_to_nothing() -> None:
    """§7's refusal reaching the one span that is a span of every request.

    ``EncodableText`` admits the empty string, which warrants nothing at all — so a
    ground resting on one is a ground this package could not resolve to anything the
    user said, and it is dropped exactly as an out-of-range label is.
    """
    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            conditions=(ProposedElement(text="somewhere", ground=Ground.USER_STATED, span=""),),
        )
    )

    assert revision.conditions == ()


# --------------------------------------------------------------------------- #
# §16 item 21 — a minted record is not a ground                                #
# --------------------------------------------------------------------------- #


def test_a_from_evidence_element_naming_a_minted_record_is_dropped() -> None:
    """§16 item 21, and §7's clause it is the arm for.

    The label is **valid** — a search-minted record stands in the supply and carries one
    — and it still resolves to nothing here, because ADR-0231 §16 makes such a record
    "not a durable reference" whose id "resolves in no store". "A durable record grounded
    on an identifier nothing can retrieve states a warrant it cannot show."
    """
    supply = [_belief("m-1", "lives in Leeds"), _belief("search-1", "a campsite in the Dales")]

    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(
                ProposedElement(text="the Dales", ground=Ground.FROM_EVIDENCE, evidence_label="M2"),
            ),
        ),
        supply=supply,
        minted=["search-1"],
    )

    assert revision.constraints == (), "the element is dropped"
    assert revision.outcome == _FIRST_ASKED, "and the turn is not degraded"


def test_the_minted_refusal_is_about_the_record_and_not_the_label() -> None:
    """The same label, over the same position, resolves where nothing was minted.

    Asserted beside the arm above so the refusal cannot be read as "``M2`` is
    unresolvable": what makes it unresolvable is the record it names.
    """
    supply = [_belief("m-1", "lives in Leeds"), _belief("m-2", "the user has a dog")]

    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(
                ProposedElement(
                    text="dogs allowed", ground=Ground.FROM_EVIDENCE, evidence_label="M2"
                ),
            ),
        ),
        supply=supply,
    )

    (constraint,) = revision.constraints
    assert constraint.evidence_id == "m-2"


# --------------------------------------------------------------------------- #
# §16 items 23, 24 — retention, omission, and an invented label                #
# --------------------------------------------------------------------------- #


def test_an_untouched_constraint_survives_a_correction_turn() -> None:
    """§16 item 23: retained by label, copied **whole and unchanged**.

    "The new revision carries the budget element with its **original** ``ground``,
    ``evidence_id`` and ``span`` byte for byte, the date element newly grounded on a span
    of **this** turn's request, and the **current brief** the next call receives still
    shows the budget." The arm fails if the constraint is dropped, re-grounded
    ``INFERRED``, or re-grounded ``USER_STATED`` on a span this turn does not contain.
    """
    goal = _goal(_opened(constraints=(_budget(),)))

    revision = _revised(
        ProposedUnderstanding(
            outcome="book a campsite for Sunday",
            outcome_ground=Ground.USER_STATED,
            outcome_span="Sunday",
            constraints=(
                ProposedElement(retains="C1"),
                ProposedElement(text="Sunday", ground=Ground.USER_STATED, span="Sunday"),
            ),
        ),
        goal=goal,
    )

    budget, date = revision.constraints
    assert budget == _budget(), "byte for byte, including its span of the *first* turn"
    assert date.ground is Ground.USER_STATED
    assert date.span == "Sunday"
    moved = goal.model_copy(update={"interpretation": (*goal.interpretation, revision)})
    assert [one.text for one in GoalBrief.of(moved).constraints] == ["under $100", "Sunday"]


def test_an_element_the_understanding_omits_is_removed() -> None:
    """§16 item 24, first half. "Omission is removal", and that is the whole mechanism.

    There is no delete member and no partial-update shape, "because a revision is a
    complete statement of an understanding and a patch would make two revisions
    unreadable without replaying every one between them".
    """
    goal = _goal(_opened(constraints=(_budget(),)))

    revision = _revised(ProposedUnderstanding(retains_outcome=True), goal=goal)

    assert revision.constraints == ()
    assert goal.interpretation[-1].constraints == (_budget(),), "and the earlier one is unedited"


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("C2", id="beyond-the-tuple"),
        pytest.param("C0", id="below-one"),
        pytest.param("S1", id="another-tuples-letter"),
        pytest.param("C01", id="padded"),
        pytest.param("c1", id="lower-cased"),
        pytest.param("constraint one", id="not-a-label-at-all"),
        # Longer than CPython's own int-str conversion limit, which `int()` refuses with
        # a `ValueError`. A model-supplied string is bounded by nothing, and §7's
        # "dropped … silently and without failing the turn" is what makes converting
        # before bounding a defect rather than a curiosity.
        pytest.param("C" + "9" * 5000, id="more-digits-than-int-will-convert"),
    ],
)
def test_a_retains_label_outside_the_shown_set_drops_its_element(label: str) -> None:
    """§16 item 24, second half, and §7's per-tuple label space.

    "A ``retains`` label outside the brief's shown set resolves to nothing, and the
    retaining element is dropped, exactly as an out-of-range ``M`` label is. A label
    naming an element of a tuple other than the one the retaining element sits in
    likewise resolves to nothing." ``S1`` is that case: the goal *has* a criterion at
    that ordinal, and a constraint naming it still resolves to nothing.
    """
    goal = _goal(
        _opened(
            constraints=(_budget(),),
            criteria=(GoalElement(text="a booking reference exists", ground=Ground.INFERRED),),
        )
    )

    revision = _revised(
        ProposedUnderstanding(retains_outcome=True, constraints=(ProposedElement(retains=label),)),
        goal=goal,
    )

    assert revision.constraints == ()
    assert revision.outcome == _FIRST_ASKED, "and the turn is otherwise unharmed"


# --------------------------------------------------------------------------- #
# §16 item 27 — an unchanged outcome keeps its grounding                       #
# --------------------------------------------------------------------------- #


def test_a_retained_outcome_is_copied_forward_byte_for_byte() -> None:
    """§16 item 27, over a revision 1 this system authored.

    "The recorded revision's ``outcome``, ``outcome_ground``, ``outcome_evidence_id`` and
    ``outcome_span`` are **byte-identical** to the previous revision's, the constraint is
    newly grounded on a span of **this** turn's request." The arm fails if the outcome is
    re-grounded ``INFERRED``, re-grounded ``USER_STATED`` on a span this turn does not
    contain, or dropped.
    """
    current = _opened()

    revision = _revised(
        ProposedUnderstanding(
            retains_outcome=True,
            constraints=(ProposedElement(text="Sunday", ground=Ground.USER_STATED, span="Sunday"),),
        ),
        goal=_goal(current),
    )

    assert revision.outcome == current.outcome
    assert revision.outcome_ground is current.outcome_ground
    assert revision.outcome_evidence_id == current.outcome_evidence_id
    assert revision.outcome_span == current.outcome_span
    (constraint,) = revision.constraints
    assert (constraint.ground, constraint.span) == (Ground.USER_STATED, "Sunday")


def test_retaining_a_migrated_outcome_records_it_again_with_no_span() -> None:
    """§16 item 27's second half, over §12's migrated revision 1.

    "Retaining an outcome grounded ``USER_STATED`` with no span records it again with no
    span, rather than refusing the revision or inventing one." A retained outcome "passes
    through no resolution at all: nothing crosses the seam to resolve, and the ground
    copied forward is one an earlier revision already resolved or §12 derived."
    """
    migrated = GoalInterpretation(
        revision=1,
        outcome=_FIRST_ASKED,
        outcome_ground=Ground.USER_STATED,
        recorded_at=_NOW,
    )

    revision = _revised(ProposedUnderstanding(retains_outcome=True), goal=_goal(migrated))

    assert revision.outcome_ground is Ground.USER_STATED
    assert revision.outcome_span is None, "§1's fourth absence, carried forward and not invented"
    assert revision.outcome == _FIRST_ASKED


def test_an_understanding_that_neither_retains_nor_states_an_outcome_does_not_construct() -> None:
    """§7's validator, restated here because item 27 ends on it.

    "An understanding that neither states an outcome nor retains one is **not
    constructible**", which is what makes omitting the objective impossible rather than a
    silent removal — so no resolution this module performs has to handle the case.
    """
    with pytest.raises(ValueError, match="states an outcome or retains"):
        ProposedUnderstanding(constraints=(ProposedElement(text="x", ground=Ground.INFERRED),))


# --------------------------------------------------------------------------- #
# §6's writer clause, over the values this module stamps                       #
# --------------------------------------------------------------------------- #


def test_the_provenance_of_a_revision_is_this_packages_and_not_the_models() -> None:
    """§6: ``revision``, ``recorded_at`` and ``raised_by`` are ``orchestration``'s.

    A planner envelope carries no field any of the three could arrive on, so the
    discarding is **structural** — and what this arm holds is the other half: that the
    values actually stamped are the ones this side supplied.
    """
    goal = _goal(_opened(), earlier=())

    revision = _revised(ProposedUnderstanding(retains_outcome=True), goal=goal)

    assert revision.revision == goal.interpretation[-1].revision + 1
    assert revision.recorded_at == _LATER
    assert revision.raised_by == "turn-2"
    assert not hasattr(ProposedUnderstanding, "model_fields") or {
        "phase",
        "revision",
        "raised_by",
        "recorded_at",
    }.isdisjoint(ProposedUnderstanding.model_fields), "no field one could arrive on"
