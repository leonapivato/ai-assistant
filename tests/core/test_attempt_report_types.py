"""ADR-0262 §11's L1: the ``core`` surface, and the three arms §12 marks L1.

Four additions, no refusal of any Protocol and no store conjunct — §11 states that in
terms: "It states no Protocol refusal, so every existing caller still commits." What
this file pins is therefore what the **types** decide and, just as load-bearing, what
they deliberately leave to L3's store: a version pair naming an execution the attempt
does not name constructs here and is refused there, because an
:class:`~ai_assistant.core.types.AttemptTransition` cannot see the attempt it names and
a second spelling of that rule would be free to disagree with the one guarding the
write.

The three L1-marked arms of §12 are arm 3's ``OUTPUT_PRESENT`` refusal, arm 5's pinned
declaration, and arm 8's negative version. Each is named in the test that carries it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionPlan,
    ActionRequest,
    AttemptOutcome,
    AttemptReport,
    AttemptTransition,
    CostBasis,
    CurrentContext,
    ExecutionState,
    GoalBrief,
    GoalStatus,
    Ground,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    StepVerification,
    TimeOfDay,
    ToolCost,
    ToolDefinition,
    TurnOutcome,
    TurnResult,
    VerificationKind,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_AT: Final = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

#: A real turn result, for the one case that needs a pass which actually planned.
#: Every other case here is about a value rather than about a turn.
_PLANNED: Final = TurnResult(
    utterance="book the riverside pitch for Sunday",
    goal=GoalBrief(
        goal_id="g-1",
        outcome="book a campsite",
        outcome_ground=Ground.USER_STATED,
        status=GoalStatus.ACTIVE,
    ),
    context=CurrentContext(
        now=_AT, time_of_day=TimeOfDay.MORNING, within_working_hours=True, is_weekend=False
    ),
    memories=(),
    plan=ActionPlan(id="p-1", goal_id="g-1", steps=(), created_at=_AT, targets_revision=1),
)

#: The two kinds ADR-0262 §2 admits as a declared postcondition.
_BOOKED: Final = StepVerification(kind=VerificationKind.FIELD_PRESENT, field="reference")
_CONFIRMED: Final = StepVerification(
    kind=VerificationKind.FIELD_EQUALS, field="status", equals="confirmed"
)


def _tool(**overrides: object) -> ToolDefinition:
    """A declaration carrying whatever this file's cases need to vary."""
    fields: dict[str, object] = {
        "id": "book_room",
        "capability": "book_accommodation",
        "description": "Book a room at a named campsite.",
        "risk_level": RiskLevel.MEDIUM,
        "reversibility": Reversibility.REVERSIBLE,
        "side_effecting": True,
        "reads": (),
        "writes": (),
        "discloses": (),
        "cost": ToolCost(basis=CostBasis.FREE),
        "idempotency": Idempotency.NATURAL,
    }
    return ToolDefinition(**{**fields, **overrides})  # type: ignore[arg-type]  # heterogeneous test kwargs


# --- ADR-0262 §2: ``ToolDefinition.postconditions`` --------------------------


def test_a_declaration_that_says_nothing_declares_the_empty_tuple() -> None:
    """§2: the empty tuple is the **fail-closed** claim and is the default.

    It is an exception to ADR-0016 §1's required-field rule because it makes the
    **opposite** claim to the one that rule refuses: a tool declaring none establishes
    nothing, so no criterion resting on it is ever met and no goal of it reaches
    ``ACHIEVED``. A value that can only refuse to establish is the direction §1 exists
    to protect, which is why it may default where ``reads`` may not.

    **And nothing in this tree declares one yet** (§8): LA's migration decodes stored
    declarations with the empty tuple and a registry definition declaring none carries
    the same value, so the comparison is between two empty tuples until an author
    writes one.
    """
    assert _tool().postconditions == ()


def test_the_two_kinds_that_say_something_about_an_output_are_admitted() -> None:
    """§2: ``FIELD_PRESENT`` and ``FIELD_EQUALS``, each naming a key of the output.

    Both say something about **what** came back rather than that something did, which
    is the whole of why they are admitted where the third is not. More than one is
    admitted too — §12's arm 3 is stated over a tool declaring **two**, one satisfied
    and one refused — so the tuple is a conjunction and not a slot.
    """
    declared = _tool(postconditions=(_BOOKED, _CONFIRMED))

    assert declared.postconditions == (_BOOKED, _CONFIRMED)


def test_output_present_is_unconstructible_as_a_declared_postcondition() -> None:
    """§12's arm 3, the half marked **L1**: the arm that fails a model-authored predicate.

    *"The producing step's ``output`` is not ``None``"* is the circularity R48 exists to
    close, one level down from the reply: a criterion met because the call it verifies
    **answered at all** establishes nothing about the goal, and a goal reaching
    ``ACHIEVED`` on that fact is exactly what ADR-0262 refuses.

    Refused **at construction of the declaration**, so no comparison ever has to know
    about it and no later reader can reach one.
    """
    with pytest.raises(ValidationError, match="OUTPUT_PRESENT"):
        _tool(postconditions=(StepVerification(kind=VerificationKind.OUTPUT_PRESENT),))


def test_the_refusal_is_on_the_declaration_and_not_on_the_vocabulary() -> None:
    """§2: it is **not** a criticism of ``verifies``'s own vocabulary (ADR-0253 §4).

    There ``OUTPUT_PRESENT`` answers *did this step produce what the plan said it
    would*, which is a question about one step's own run and is answered honestly by
    *it returned something*. The member therefore stays in the enumeration and stays
    constructible as a :class:`StepVerification`; what is refused is declaring one **on
    a tool**. A lane reading this refusal as a defect in ``VerificationKind`` would
    remove a member ADR-0253 §4 needs.
    """
    assert VerificationKind.OUTPUT_PRESENT in set(VerificationKind)
    assert StepVerification(kind=VerificationKind.OUTPUT_PRESENT).kind is (
        VerificationKind.OUTPUT_PRESENT
    )


def test_a_refused_member_anywhere_in_the_tuple_refuses_the_declaration() -> None:
    """§2, stated over position: the refusal is not about the first entry.

    An implementation testing only ``postconditions[0]`` passes the case above and
    admits the circularity behind any admissible member, which is the shape a
    declaration would actually be written in — the honest predicate first and the
    catch-all appended.
    """
    with pytest.raises(ValidationError, match="OUTPUT_PRESENT"):
        _tool(
            postconditions=(
                _BOOKED,
                StepVerification(kind=VerificationKind.OUTPUT_PRESENT),
            )
        )


def test_the_declaration_a_decision_recorded_decodes_as_it_was_recorded() -> None:
    """§12's arm 5, the half marked **L1**: the declaration is the **pinned** one.

    ``ActionRequest.tool`` and ``PermissionDecision.tool`` embed the **whole**
    definition by value — ADR-0021 §1's *"There is no name left to rebind"*, which §2
    relies on — so what the comparison holds an output against is the declaration **the
    decision recorded**, not whatever the registry answers at the moment it is read.
    L1's half of the arm is that the recorded value survives the round trip the audit
    trail takes it on: re-registering the tool id with declarations the stored output
    would fail leaves the decision saying what it said.

    Asserted over the **serialised** record rather than over the live object, because
    that is where the loss would be — ``SqliteAuditTrail`` persists each decision as a
    JSON record, and a definition whose new tuple did not survive ``model_dump`` would
    decode as a tool declaring nothing and quietly make every criterion resting on it
    unestablished.
    """
    recorded = PermissionDecision(
        id="d-1",
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="the user confirmed it"),
        tool=_tool(postconditions=(_BOOKED, _CONFIRMED)),
        parameters_digest=ActionRequest(
            tool=_tool(postconditions=(_BOOKED, _CONFIRMED)),
            parameters={"site": "riverside"},
            step_id="step-1",
            execution_id="exec-1",
        ).parameters_digest,
        decided_at=_AT,
        step_id="step-1",
        execution_id="exec-1",
    )

    # The registry moves under it: the same tool id, declaring something the stored
    # output would fail. Nothing about that reaches the decision.
    reregistered = _tool(
        postconditions=(
            StepVerification(
                kind=VerificationKind.FIELD_EQUALS, field="status", equals="cancelled"
            ),
        )
    )
    assert reregistered.id == recorded.tool.id

    decoded = PermissionDecision.model_validate(recorded.model_dump())

    assert decoded.tool.postconditions == (_BOOKED, _CONFIRMED)
    assert decoded == recorded


def test_a_decision_written_before_this_decision_decodes_with_none_declared() -> None:
    """§8: *"a decision written before this decision decodes with ``postconditions``
    empty, which is the fail-closed claim §2 states"*.

    **No record is rewritten, back-filled or re-decided.** The default is what makes
    that true, and it is asserted over a payload with the member simply absent —
    which is what a record LA's migration restamps actually holds.
    """
    written = PermissionDecision(
        id="d-0",
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        tool=_tool(),
        parameters_digest="0" * 64,
        decided_at=_AT,
        step_id="step-0",
        execution_id="exec-0",
    ).model_dump()
    del written["tool"]["postconditions"]

    assert PermissionDecision.model_validate(written).tool.postconditions == ()


# --- ADR-0262 §4: ``AttemptTransition.execution_versions`` -------------------


def _transition(**overrides: object) -> AttemptTransition:
    """A transition carrying whatever this file's cases need to vary."""
    fields: dict[str, object] = {"attempt_id": "att-1", "expected_version": 3}
    return AttemptTransition(**{**fields, **overrides})  # type: ignore[arg-type]  # heterogeneous test kwargs


def test_the_snapshot_defaults_empty_and_takes_the_pairs_it_is_given() -> None:
    """§4: possibly empty, each pair an execution id and the version the caller read.

    Empty is what an attempt naming **no** execution carries, and it is the default so
    that every caller this decision does not touch — a phase stamp, an effort counter,
    an append — writes exactly as it does today.
    """
    assert _transition().execution_versions == ()
    assert _transition(execution_versions=(("exec-1", 0), ("exec-2", 7))).execution_versions == (
        ("exec-1", 0),
        ("exec-2", 7),
    )


def test_a_pair_carrying_a_negative_version_is_refused_at_construction() -> None:
    """§12's arm 8, the half marked **L1**: *"before any store sees it"*.

    The arm that fails against a field typed ``int`` and validated nowhere.
    :attr:`ExecutionState.version` declares ``ge=0``, so a negative figure names no
    state any store has written — and refusing it here is what keeps the store's two
    refusals apart. There, a version that is not the stored one raises
    ``StaleExecutionError``, whose documented meaning is *the stored execution has
    advanced since the caller read it … re-read and retry*. A negative figure is not
    that: nothing advanced, so a class promising a fruitful retry would be a false
    statement about the store.
    """
    with pytest.raises(ValidationError):
        _transition(execution_versions=(("exec-1", -1),))


def test_zero_is_admitted_because_it_is_the_version_a_fresh_execution_holds() -> None:
    """§4: the floor is ``ExecutionState.version``'s own domain and not a positivity test.

    ``ExecutionState.version`` defaults to ``0``, so an execution nothing has written to
    since ``start_execution`` is at zero and a caller's honest snapshot of it says so. A
    ``gt=0`` here would refuse the commonest true value there is.
    """
    assert _transition(execution_versions=(("exec-1", 0),)).execution_versions == (("exec-1", 0),)


@pytest.mark.parametrize("version", [0, 1, 7, "1", 1.0, True, -1, 1.5, "one", None])
def test_the_version_domain_is_exactly_the_one_it_mirrors(version: object) -> None:
    """§4: the domain is *"``ExecutionState.version``'s own ``ge=0`` domain"*, and not a
    domain of this decision's own.

    Asserted as an **equality with that field** rather than as a list of refusals,
    because a list is what drifts: this pair is *"the ``ExecutionState.version`` the
    caller read"*, so a value that field accepts and this one refuses would refuse a
    version an execution really holds, and a value this one accepts and that field
    refuses would carry a figure no execution could be at. §4's *"No lane widens the
    domain, coerces a value into it"* is a rule about **lanes** — nobody clamps a
    negative to zero or substitutes a figure for an absent one — and the corpus reads
    every other ``int`` in ``core`` under pydantic's ordinary lax validation, this
    command's own ``expected_version`` and ``planner_calls`` included. Making this one
    element strict would give it a **narrower** domain than the field §4 names, which is
    the one thing that clause fixes.

    Both directions are asserted over one input at a time, so a failure names the value
    and which side took it.
    """
    mirrored = _accepts(
        lambda: ExecutionState(
            id="exec-1",
            plan_id="p-1",
            steps=(),
            version=version,  # type: ignore[arg-type]  # the domain itself is under test
            updated_at=_AT,
        )
    )
    snapshot = _accepts(lambda: _transition(execution_versions=(("exec-1", version),)))

    assert snapshot is mirrored, "the pair's domain is ExecutionState.version's own"


def _accepts(build: Callable[[], object]) -> bool:
    """Whether ``build`` constructs, for the domain comparison above."""
    try:
        build()
    except ValidationError:
        return False
    return True


def test_a_blank_execution_id_is_refused_because_the_pair_names_an_execution() -> None:
    """The id half is ``Identifier``, which is what every other id on this command is.

    Nothing about this is ADR-0262's; it is the type the corpus already spells an
    execution id with, and stating it here is what keeps a later widening visible.
    """
    with pytest.raises(ValidationError):
        _transition(execution_versions=(("  ", 1),))


@pytest.mark.parametrize(
    ("pairs", "why"),
    [
        ((("exec-1", 1), ("exec-1", 2)), "a duplicate id"),
        ((("exec-9", 1),), "an id the attempt does not name"),
        ((), "a partial snapshot of an attempt that names one"),
    ],
)
def test_the_malformed_sets_construct_here_because_the_store_refuses_them(
    pairs: tuple[tuple[str, int], ...], why: str
) -> None:
    """§11: **L1 states no refusal**, and §4 says which refusals are L3's.

    A missing id, an extra id and a duplicate are each a **malformed command** refused
    with ``ValueError`` at ``commit_attempt``, *"decided in the same indivisible step as
    the write"* — and they have to be, because whether the pairs are exactly the
    attempt's is a question about an attempt this value cannot see. A check here would
    be a second spelling of that rule, free to disagree with the one that actually
    guards the commit, which is the defect ADR-0251 §3 names.

    So this is the **absence** of a refusal asserted deliberately. A lane that adds one
    here fails this test and has to read §4 rather than discover the disagreement in
    review.
    """
    assert _transition(execution_versions=pairs).execution_versions == pairs, why


def test_every_other_transition_may_carry_the_field_and_is_unaffected_by_it() -> None:
    """§4: *"It is the ``→ ENDED`` limb **alone** that reads the field"*.

    ``→ CANCELLED`` included — so ADR-0261 §2's act is unaffected whatever it passes,
    and §12's arm 8 asserts one carrying a **stale** pair still commits. That is a
    statement about the store, and what this type owes it is that such a transition
    constructs at all.
    """
    cancelled = _transition(to_state=None, execution_versions=(("exec-1", 1),), planner_calls=4)

    assert cancelled.execution_versions == (("exec-1", 1),)
    assert cancelled.planner_calls == 4


# --- ADR-0262 §6: ``AttemptReport`` and ``TurnOutcome.attempt_report`` -------


def test_the_report_carries_exactly_two_fields() -> None:
    """§6: *"exactly two fields"*, and it carries no third.

    No goal id, no attempt id, no criterion, no criterion text, no count, no evidence
    reference, no step id, no instant and no prose — ADR-0249 §9's containment reached
    for its own reason: *"an implementation that rendered every field of every value it
    was handed … discloses none of those, because there is none on the value to
    disclose."* Pinned as a roster rather than as a list of absences, so a lane adding
    any one of them fails here.
    """
    assert set(AttemptReport.model_fields) == {"outcome", "continues"}


def test_the_report_is_frozen_and_forbids_what_it_does_not_declare() -> None:
    """§6: a frozen model with ``extra="forbid"``.

    ``extra="forbid"`` is also the first of the wire grounds behind this lane's
    ``PROTOCOL_VERSION`` move, one model out: it is what makes a member an older peer
    does not know a refusal rather than a silent drop.
    """
    assert AttemptReport.model_config.get("frozen") is True
    assert AttemptReport.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        AttemptReport.model_validate(
            {"outcome": AttemptOutcome.VERIFIED, "continues": False, "goal_id": "g-1"}
        )


@pytest.mark.parametrize("missing", ["outcome", "continues"])
def test_neither_field_defaults(missing: str) -> None:
    """§6: ``outcome`` is **required**, and ``continues`` is required for its own reason.

    Either value of ``continues`` is a claim. The composing stage's instruction
    *requires* the answer to end with an offer to continue where it is set, so a default
    would silently decide whether a user is offered one — and the two facts it is
    computed from, the member and whether the goal is open, are in front of whoever
    constructs the value. ``outcome`` defaulting would be worse still: it would name a
    verdict no comparison reached.
    """
    fields: dict[str, object] = {"outcome": AttemptOutcome.VERIFIED, "continues": True}
    del fields[missing]

    with pytest.raises(ValidationError):
        AttemptReport.model_validate(fields)


@pytest.mark.parametrize("member", list(AttemptOutcome))
def test_the_type_refuses_no_member_including_the_one_no_limb_reaches(
    member: AttemptOutcome,
) -> None:
    """§11: **L1 states no refusal**, and that includes ``CANCELLED``.

    §4 is explicit that ``CANCELLED`` *"is reached by no limb"* of the comparison — a
    cancelled attempt is terminal and ADR-0261 §2's act is what produces it. That is a
    rule about **which member the comparison yields**, and this type is handed a member
    rather than computing one, so a refusal here would be this decision policing a value
    ADR-0261 §3 owns.

    **This is not a licence for a seventh fixed statement, and the obligation is refused
    where it could actually be acquired.** §6 fixes one statement per member and
    enumerates **six**; the member a surface never sees is one no surface owes prose
    for. What a consumer drives a surface from is the canonical fake, and that **refuses
    the arrangement outright** —
    ``tests/testing/test_fake_engine_attempt_report.py`` is the other side of this
    split: the type stays as wide as the vocabulary it is typed by, and the phase's
    stand-in stays as narrow as the phase.

    Asserted over every member rather than over that one, so the roster moving is what
    fails this test.
    """
    assert AttemptReport(outcome=member, continues=False).outcome is member


def test_the_outcome_member_and_continues_are_independent_on_the_type() -> None:
    """§6: ``continues`` is computed **from two facts** and one of them is not here.

    ``True`` exactly where the member is ``PARTIAL``, ``FAILED`` or ``UNCERTAIN``
    **and the goal is open** (ADR-0250 §1). The goal's status is on no field of this
    value, so the rule is not one the type can state — an ``UNCERTAIN`` report over a
    goal a revision closed carries ``False`` and is well-formed. Making the type refuse
    the combinations would encode half a rule and refuse the other half's true cases.
    """
    assert AttemptReport(outcome=AttemptOutcome.UNCERTAIN, continues=False).continues is False
    assert AttemptReport(outcome=AttemptOutcome.VERIFIED, continues=False).continues is False
    assert AttemptReport(outcome=AttemptOutcome.PARTIAL, continues=True).continues is True


def test_a_turn_carries_no_report_unless_it_ended_an_attempt() -> None:
    """§6: ``None``-defaulting, and ``None`` is what almost every turn carries.

    Non-``None`` **exactly** on a turn that ended an attempt under §4 — so ``None`` on a
    turn that engaged no goal, on a routed operation, on ADR-0198 §1's restatement, on
    every turn whose attempt stayed live, and on the turn whose ``commit_attempt`` was
    refused after the reply was composed. Which of those a turn is, is L4's to decide;
    what L1 owes is that the absent value is the default.
    """
    assert TurnOutcome(turn=None).attempt_report is None


def test_the_member_is_emitted_on_every_outcome_that_crosses() -> None:
    """The first of this lane's two wire grounds, asserted about the type itself.

    ``wire/codec.py`` renders a model by ``model_dump()`` and ``TurnOutcome`` sets
    ``extra="forbid"``, so a defaulted member is **emitted** rather than omitted and a
    client one ``PROTOCOL_VERSION`` back fails it with ``extra_forbidden``. That is
    ADR-0124 §9's second limb, and it is why the bump rides this lane rather than the
    lane that first populates the member.
    """
    dumped = TurnOutcome(turn=None).model_dump()

    assert "attempt_report" in dumped
    assert dumped["attempt_report"] is None
    assert TurnOutcome.model_config.get("extra") == "forbid"


def test_a_turn_that_ended_an_attempt_carries_the_report_beside_its_reply() -> None:
    """§6: rendered **beside** the reply and never in place of it.

    So the two members ride together on one outcome, which is what a surface needs to
    render the fixed statement beside the answer. The report says nothing about the
    reply and the reply nothing about the report: ADR-0170 §4's shapes are untouched
    and ``reply_degraded`` stays ``False``.
    """
    outcome = TurnOutcome(
        turn=_PLANNED,
        reply="I booked the riverside pitch for Sunday.",
        attempt_report=AttemptReport(outcome=AttemptOutcome.UNCERTAIN, continues=True),
    )

    assert outcome.attempt_report == AttemptReport(outcome=AttemptOutcome.UNCERTAIN, continues=True)
    assert outcome.reply == "I booked the riverside pitch for Sunday."
    assert outcome.reply_degraded is False
