"""The routed contract surface, invariant by invariant (ADR-0197 §8, §9, §12).

§12's first Normative names the coverage this module owes, and it names it as a
roster rather than as a theme: five invariants on
:class:`~ai_assistant.core.types.RoutedOperation` asserted in **both** directions,
:class:`~ai_assistant.core.types.OperationConfirmation`'s own cardinality and arm
rules, the ``routed``/``step`` mutual exclusion, ADR-0197 §8's widened
:class:`~ai_assistant.core.types.TurnOutcome` across all four of its routed cases,
and :class:`~ai_assistant.core.types.RouteApproval`'s two-directional validator
against §3's tag.

**Why the negative half is not enough on its own, twice over.** A validator with no
rule at all passes every "this constructs" case, and a validator that refuses
*everything* passes every "this is refused" case; the pairs below are what tell the
two apart. The sharpest instance is §8's tag-to-outcome rule, which §12 requires
asserted on a read-only ``NOT_FOUND`` with ``listing`` **``None``** and on no other
combination — see
:func:`test_a_read_only_operation_admits_only_performed_unrecorded_and_failed`.

**Records are built locally rather than imported from a sibling test package.**
``tests/permissions/permission_builders.py`` and the conformance suites are on
pytest's path only once something in their own directory has been collected, so a
cross-directory import here would make this module's collection depend on the rest of
the run. The builders below are the smallest coherent value of each arm and nothing
more; ``tests/core/test_spend_types.py`` already takes the same position.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    ActionPlan,
    Belief,
    BeliefBand,
    ContinuationToken,
    CostBasis,
    CurrentContext,
    Disposition,
    ExecutionState,
    Goal,
    GrantScope,
    Idempotency,
    MemoryKind,
    MemorySource,
    OperationConfirmation,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PlanStep,
    Provenance,
    Question,
    QuestionState,
    ReadOutcome,
    RecordedInvocation,
    Reversibility,
    RiskLevel,
    RoutableOperation,
    RouteApproval,
    RoutedOperation,
    RoutedOperationRecord,
    RouteOutcome,
    SourceGrant,
    SourceReadRecord,
    SpendPeriod,
    SpendTotal,
    StepOutcome,
    TimeOfDay,
    ToolCost,
    ToolDefinition,
    ToolInvocation,
    TurnOutcome,
    TurnResult,
    admitted_route_outcomes,
    routed_listing_arm,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

#: A fixed instant, so every assertion below is about the value under test rather
#: than about how fast the suite runs.
AT: Final = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)

#: The nine members ADR-0197 §3 fixes, split by its own tag. Spelled out rather than
#: derived from :attr:`RoutableOperation.confirm_owed`, because deriving it would make
#: the roster agree with the property by construction and assert nothing about either.
_READ_ONLY: Final = (
    "questions",
    "recent_reads",
    "recent_invocations",
    "recent_decisions",
    "standing_grants",
    "spend_totals",
)
_CONFIRM_OWED: Final = ("forget", "revoke", "forget_question")


# --- the smallest coherent value of each RoutedListing arm -------------------


def belief(record_id: str = "b-1", content: str = "the user likes jazz") -> Belief:
    """One live belief, as §5's ``forget`` lookup resolves it."""
    return Belief(
        id=record_id,
        band=BeliefBand.ASSERTED,
        kind=MemoryKind.SEMANTIC,
        content=content,
        confidence=1.0,
        last_updated=AT,
    )


def question(question_id: str = "q-1", content: str = "did the user move?") -> Question:
    """One deferred question, as §5's ``forget_question`` lookup resolves it."""
    return Question(
        id=question_id,
        state=QuestionState.OPEN,
        content=content,
        kind=MemoryKind.SEMANTIC,
        band=BeliefBand.DERIVED,
        rationale="the observer was unsure",
        reason="the policy wants a human answer",
        retires=(),
        asked_at=AT,
        expires_at=None,
    )


def grant(source: str = "calendar") -> SourceGrant:
    """One standing source grant, as §5's ``revoke`` lookup resolves it.

    The scope names one use because ``SourceGrant`` refuses an empty one — "a grant
    authorising nothing still reads as a grant" (ADR-0097 §2) — and nothing below is
    about which use it names.
    """
    return SourceGrant(id="g-1", source=source, scope=(GrantScope.INGEST,), decided_at=AT)


def read(record_id: str = "r-1") -> SourceReadRecord:
    """One source-read row, as a routed ``recent_reads`` returns it."""
    return SourceReadRecord(
        id=record_id,
        source="calendar",
        use=GrantScope.INGEST,
        checked_at=AT,
        outcome=ReadOutcome.COMPLETED,
        grant="g-1",
        produced=0,
    )


def invocation(row_id: str = "i-1") -> RecordedInvocation:
    """One invocation row, as a routed ``recent_invocations`` returns it."""
    return RecordedInvocation(
        invocation=ToolInvocation(id=row_id, decision_id="d-1", recorded_at=AT),
        tool="t-1",
        capability="c-1",
        egress_call=False,
    )


def ruled(decision_id: str = "d-1") -> PermissionDecision:
    """One permission decision, as a routed ``recent_decisions`` returns it."""
    return PermissionDecision(
        id=decision_id,
        ruling=PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="below the threshold"),
        tool=ToolDefinition(
            id="t-1",
            capability="send_email",
            description="Send an email.",
            risk_level=RiskLevel.LOW,
            reversibility=Reversibility.REVERSIBLE,
            side_effecting=True,
            reads=(),
            writes=(),
            discloses=(),
            cost=ToolCost(basis=CostBasis.FREE),
            idempotency=Idempotency.NONE,
        ),
        parameters_digest="0" * 64,
        decided_at=AT,
    )


def total() -> SpendTotal:
    """One period total, as a routed ``spend_totals`` returns it."""
    return SpendTotal(
        period=SpendPeriod.CALENDAR_DAY,
        period_start=datetime(2026, 8, 27, tzinfo=UTC),
        period_end=datetime(2026, 8, 28, tzinfo=UTC),
        start_offset=timedelta(0),
        end_offset=timedelta(0),
    )


#: One coherent value per arm, keyed by the operation whose listing it belongs to.
#: Total over :class:`RoutableOperation` and asserted so below, which is what makes a
#: member added under §3's widening rule fail here rather than in a renderer.
_ROW: Final[Mapping[RoutableOperation, Callable[[], BaseModel]]] = {
    RoutableOperation.QUESTIONS: question,
    RoutableOperation.RECENT_READS: read,
    RoutableOperation.RECENT_INVOCATIONS: invocation,
    RoutableOperation.RECENT_DECISIONS: ruled,
    RoutableOperation.STANDING_GRANTS: grant,
    RoutableOperation.SPEND_TOTALS: total,
    RoutableOperation.FORGET: belief,
    RoutableOperation.REVOKE: grant,
    RoutableOperation.FORGET_QUESTION: question,
}


def card(
    operation: RoutableOperation = RoutableOperation.FORGET,
) -> OperationConfirmation:
    """One wholly valid confirmation for ``operation``.

    "Wholly valid" is what several cases below turn on: they vary exactly one thing
    about a value that is otherwise correct, so the refusal they assert is about that
    one thing and not about a second defect the case never named.
    """
    return OperationConfirmation(
        operation=operation,
        # `_ROW` is keyed by operation and its value is the arm that operation names,
        # which is a correspondence `routed_listing_arm` states and the case below
        # asserts — but not one a `Mapping` annotation can carry, so the narrowing is
        # the builder's rather than the type's.
        subject=(_ROW[operation](),),  # type: ignore[arg-type]
        token=ContinuationToken(handle="h-1"),
    )


def parked_step() -> StepOutcome:
    """A step outcome that is *not* a park, for the mutual-exclusion case.

    Deliberately not a parked one: ``TurnOutcome`` refuses a reply beside a parked
    step for its own reason (ADR-0170 §4), and a case about ``routed``/``step``
    exclusion must not be able to pass on that clause instead.
    """
    return StepOutcome(
        disposition=Disposition.EXECUTED,
        state=ExecutionState(id="e-1", plan_id="p-1", steps=(), updated_at=AT),
        step_id="s-1",
    )


# --- §3's vocabulary and §8's outcomes, pinned as rosters --------------------


def test_the_routable_vocabulary_is_exactly_the_nine_members_section_three_names() -> None:
    """ADR-0197 §3 closes the vocabulary at nine, and the closure is the decision.

    A tenth member is a ``core/types.py`` change ratified contract-first, and §3's
    widening rule states five conditions a lane must show its member satisfies. Pinning
    the roster here is what makes a member added silently fail the gate — "adding a
    member silently does not satisfy this clause, and neither does citing this ADR in
    place of the statement".

    **The values are pinned too**, because they are ``StrEnum`` strings the router
    emits and a stored row carries: renaming one changes what a conforming model must
    reply and what an already-written trail row means.
    """
    assert [member.value for member in RoutableOperation] == [*_READ_ONLY, *_CONFIRM_OWED]


@pytest.mark.parametrize("value", _READ_ONLY)
def test_a_read_only_member_is_tagged_read_only(value: str) -> None:
    """§3's tag is a property of the **operation**, not of the turn or the user.

    "No setting, adapter, policy or later ADR makes a confirm-owed operation route
    without §7's confirmation", so the tag has to be readable off the member alone —
    which is what lets §8's validators state the tag-to-outcome rule without a second
    field that could disagree with this one.
    """
    assert not RoutableOperation(value).confirm_owed


@pytest.mark.parametrize("value", _CONFIRM_OWED)
def test_a_confirm_owed_member_is_tagged_confirm_owed(value: str) -> None:
    """The other direction, and ``revoke`` is the member that makes it worth stating.

    §3: "The direction of a write does not change its tag." ``revoke`` only ever
    narrows what the assistant may read and is confirm-owed anyway, because what §7
    guards is not the risk of the operation but the fact that a **model** selected it
    and its subject from a sentence.
    """
    assert RoutableOperation(value).confirm_owed


def test_the_route_outcome_vocabulary_is_exactly_section_eight_s_members() -> None:
    """ADR-0197 §8 fixes eight members, and two of them are the pair that matters.

    ``FAILED`` means the operation was **called and raised**; ``UNRECORDED`` means §9's
    row was not written, so it was **never called** and nothing was destroyed. "The two
    are separate members because they are opposite statements about the same question —
    did anything happen — and a surface that rendered them alike would tell a user their
    belief might be gone when this decision guarantees it is not."
    """
    assert [member.value for member in RouteOutcome] == [
        "performed",
        "awaiting_confirmation",
        "refused",
        "ambiguous",
        "ambiguous_truncated",
        "not_found",
        "unrecorded",
        "failed",
    ]


@pytest.mark.parametrize("operation", list(RoutableOperation))
def test_every_operation_names_an_arm_of_the_routed_listing(
    operation: RoutableOperation,
) -> None:
    """§8: the operation is the discriminator, so the mapping must be total.

    "A lane reads the arm off ``operation``, and an implementation that infers it from
    the value's shape does not conform: an **empty** tuple is a legal value of every
    arm, so the shape decides nothing on exactly the case a listing is most likely to
    take." A member with no arm would leave that reader with nothing to read.
    """
    arm = routed_listing_arm(operation)

    assert isinstance(_ROW[operation](), arm)


@pytest.mark.parametrize("operation", list(RoutableOperation))
def test_the_tag_decides_the_admissible_outcomes_as_a_closed_set(
    operation: RoutableOperation,
) -> None:
    """§8's rule stated as a set per tag, and checked as one for every member.

    A read-only operation admits exactly three, because §5 gives it nothing to be
    ambiguous about: it takes no query and resolves no argument, so ``AMBIGUOUS``,
    ``AMBIGUOUS_TRUNCATED`` and ``NOT_FOUND`` are statements about a lookup that never
    ran, and ``AWAITING_CONFIRMATION`` and ``REFUSED`` are statements about a
    confirmation §7 never offers it.

    Parametrised over the whole enum rather than over two examples, so a member added
    under §3's widening rule is tagged and checked here rather than discovered by a
    surface that was handed an outcome it cannot render.
    """
    admitted = admitted_route_outcomes(operation)

    if operation.confirm_owed:
        assert admitted == frozenset(RouteOutcome)
    else:
        assert admitted == frozenset(
            {RouteOutcome.PERFORMED, RouteOutcome.UNRECORDED, RouteOutcome.FAILED}
        )


# --- OperationConfirmation's own validator (§8) ------------------------------


def test_a_confirmation_shows_exactly_one_subject() -> None:
    """The positive half, which is what the two refusals below are measured against."""
    shown = card()

    assert len(shown.subject) == 1
    assert shown.subject[0] == belief()


def test_a_confirmation_showing_nothing_is_refused() -> None:
    """§8: "A zero-element subject is a card showing the user nothing to approve."

    ADR-0073 §5's reason, applied: *a person cannot consent to destroying something they
    were not shown*. It is a validator or it is nothing — a zero-element tuple constructs
    under a bare ``RoutedListing`` annotation, so the type says nothing about it.
    """
    with pytest.raises(ValidationError, match="must show exactly one"):
        OperationConfirmation(
            operation=RoutableOperation.FORGET,
            subject=(),
            token=ContinuationToken(handle="h-1"),
        )


def test_a_confirmation_showing_two_subjects_is_refused() -> None:
    """§8: a two-element subject is §5's ``AMBIGUOUS`` case rendered as a confirmation.

    §5 forbids performing anything for that case — "ambiguity ends the route" — so a
    card offering a yes/no over two candidates would be asking the user to approve
    something the resolution never chose. ``AssistantEngine.resume`` takes
    ``approved: bool`` and cannot carry a selection, so there is no answer such a card
    could take.
    """
    with pytest.raises(ValidationError, match="must show exactly one"):
        OperationConfirmation(
            operation=RoutableOperation.FORGET,
            subject=(belief("b-1"), belief("b-2")),
            token=ContinuationToken(handle="h-1"),
        )


def test_a_confirmation_showing_a_record_of_another_kind_is_refused() -> None:
    """The arm rule, on the card as well as on the listing (§8).

    A ``forget`` card rendering a ``SourceGrant`` would be showing the user a source
    while asking them to approve destroying a belief. The operation is the
    discriminator, so the element has to be of the arm it names.
    """
    with pytest.raises(ValidationError, match="subject must be a Belief"):
        OperationConfirmation(
            operation=RoutableOperation.FORGET,
            subject=(grant(),),
            token=ContinuationToken(handle="h-1"),
        )


# --- RoutedOperation's five invariants, both directions each (§8, §12) -------


def test_a_parked_route_carries_its_confirmation() -> None:
    """First invariant, positive direction.

    "A client handed one without has nothing to resume with" — the token rides the
    card, and §7 makes it the **only** way a routed park is answered.
    """
    routed = RoutedOperation(
        operation=RoutableOperation.FORGET,
        outcome=RouteOutcome.AWAITING_CONFIRMATION,
        confirmation=card(),
    )

    assert routed.confirmation is not None
    assert routed.confirmation.token.handle == "h-1"


def test_a_parked_route_without_its_confirmation_is_refused() -> None:
    """First invariant, negative direction on the ``AWAITING_CONFIRMATION`` side.

    A nullable field with no invariant permits a parked outcome carrying neither card
    nor token, and a client handed one has nothing to resume with and no contract
    violation to point at — which is
    :meth:`StepOutcome._confirmation_matches_disposition`'s own argument, one type over.
    """
    with pytest.raises(ValidationError, match="must carry the confirmation"):
        RoutedOperation(
            operation=RoutableOperation.FORGET, outcome=RouteOutcome.AWAITING_CONFIRMATION
        )


@pytest.mark.parametrize(
    "outcome",
    [RouteOutcome.PERFORMED, RouteOutcome.REFUSED, RouteOutcome.NOT_FOUND],
)
def test_an_unparked_route_carrying_a_confirmation_is_refused(outcome: RouteOutcome) -> None:
    """First invariant, negative direction on the other side.

    A confirmation on a route that did not park is a prompt for an action nobody is
    waiting on — and on ``PERFORMED`` it is worse than idle: it would offer the user a
    yes/no over something already done.
    """
    with pytest.raises(ValidationError, match="must not carry a confirmation"):
        RoutedOperation(operation=RoutableOperation.FORGET, outcome=outcome, confirmation=card())


@pytest.mark.parametrize("outcome", [RouteOutcome.AMBIGUOUS, RouteOutcome.AMBIGUOUS_TRUNCATED])
def test_an_ambiguous_route_carries_its_candidates(outcome: RouteOutcome) -> None:
    """Second invariant, positive direction on the two ambiguous outcomes.

    §5: both perform nothing, both confirm nothing, both carry the listing, and both
    write no row. "No surface renders fewer candidates than the outcome carries or
    summarises in place of them."
    """
    routed = RoutedOperation(
        operation=RoutableOperation.FORGET,
        outcome=outcome,
        listing=(belief("b-1"), belief("b-2")),
    )

    assert routed.listing is not None
    assert len(routed.listing) == 2


def test_a_read_only_performed_route_carries_its_result() -> None:
    """Second invariant, positive direction on its third and least obvious arm.

    A read-only ``PERFORMED`` is the case the listing exists *for*: §6 gives the
    composing stage two enum values and no listing, so what the user reads the trail
    from is this member, "rendered by the adapter from typed values with the renderer
    that adapter already has for that operation".
    """
    routed = RoutedOperation(
        operation=RoutableOperation.RECENT_READS,
        outcome=RouteOutcome.PERFORMED,
        listing=(read(),),
    )

    assert routed.listing == (read(),)


def test_a_read_only_performed_route_without_its_listing_is_refused() -> None:
    """Second invariant, negative direction: the outcome alone says nothing found.

    A routed "what have you read lately?" answered with a bare ``PERFORMED`` is a turn
    that did something rendered as a turn that produced nothing, which is exactly the
    failure ADR-0197's Consequences name for a client that ignores ``routed``.
    """
    with pytest.raises(ValidationError, match="must carry its listing"):
        RoutedOperation(operation=RoutableOperation.RECENT_READS, outcome=RouteOutcome.PERFORMED)


@pytest.mark.parametrize(
    "outcome",
    [RouteOutcome.NOT_FOUND, RouteOutcome.UNRECORDED, RouteOutcome.FAILED],
)
def test_a_route_that_resolved_nothing_carrying_a_listing_is_refused(
    outcome: RouteOutcome,
) -> None:
    """Second invariant, the other negative direction.

    ``NOT_FOUND`` is a lookup that matched nothing, ``UNRECORDED`` never called the
    operation at all, and ``FAILED`` has no result to show — so a listing on any of them
    would be records the pass did not produce, presented as though it had.
    """
    with pytest.raises(ValidationError, match="must carry no listing"):
        RoutedOperation(operation=RoutableOperation.FORGET, outcome=outcome, listing=(belief(),))


def test_a_confirm_owed_performed_route_carries_no_listing() -> None:
    """The clause that keeps ``PERFORMED``'s listing rule tag-sensitive rather than flat.

    A confirm-owed ``PERFORMED`` is a destruction or a withdrawal: ``forget`` answers a
    ``bool`` and ``revoke`` a withdrawn grant, neither of which §8 gives an arm, and §6
    keeps both out of every prompt in any case. A validator that made ``PERFORMED``
    always carry a listing would make a routed ``forget`` unrepresentable.
    """
    routed = RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED)

    assert routed.listing is None


def test_a_listing_of_the_wrong_arm_is_refused() -> None:
    """Third invariant: the operation is the discriminator, never the value's shape.

    The listing here is **wholly well-formed on its own terms** — two real
    ``SourceGrant`` rows, which is exactly what a routed ``revoke`` or
    ``standing_grants`` carries — and the route is a ``forget``. Nothing about the value
    is wrong; what is wrong is the pairing, which is why the operation has to be the
    thing consulted. An implementation reading the arm off the value would accept it and
    hand a ``forget`` renderer a source.
    """
    with pytest.raises(ValidationError, match="listing holds only Belief rows"):
        RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AMBIGUOUS,
            listing=(grant("calendar"), grant("email")),
        )


def test_a_listing_mixing_two_arms_is_not_a_listing_at_all() -> None:
    """§8's arms are **homogeneous** tuples, so a mixed listing is no arm.

    Refused by the union itself rather than by the validator, and the distinction is
    worth pinning: the validator's arm check is about a well-formed listing paired with
    the wrong operation, and this is about a value that is not a listing in the first
    place. An arm declared as a tuple of a union would admit it, and every renderer
    downstream would then have to branch per element.
    """
    with pytest.raises(ValidationError, match="listing"):
        RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AMBIGUOUS,
            # The mixed listing is the subject: no arm of `RoutedListing` is
            # heterogeneous, so `mypy` refuses it statically and the runtime refusal
            # asserted here is what a client decoding the wire would meet.
            listing=(belief(), grant()),  # type: ignore[arg-type]
        )


def test_an_empty_listing_is_admitted_on_the_outcomes_that_carry_one() -> None:
    """The other half of the clause above, and it is why the rule is stated at all.

    An empty tuple satisfies every arm, so it can never be *refused* by an arm check —
    which is precisely why §8 names ``operation`` as the discriminator rather than
    letting a reader infer the arm from what it was handed.
    """
    routed = RoutedOperation(
        operation=RoutableOperation.RECENT_READS,
        outcome=RouteOutcome.PERFORMED,
        listing=(),
    )

    assert routed.listing == ()


def test_a_confirmation_about_another_operation_is_refused() -> None:
    """Fourth invariant, and the one an inner-model validator cannot reach.

    The card here is **wholly valid on its own terms** — one element, of its own arm, a
    real token — and describes ``revoke`` while the route is a ``forget``. "A user
    reading 'revoke this grant?' would be approving a ``forget``." One discriminator per
    value is §8's rule, and two values carrying it must agree or the pair is not a
    description of one route.
    """
    with pytest.raises(ValidationError, match="its confirmation is about revoke"):
        RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card(RoutableOperation.REVOKE),
        )


def test_a_confirmation_about_the_same_operation_is_admitted() -> None:
    """Fourth invariant, positive direction — the pair describes one route."""
    routed = RoutedOperation(
        operation=RoutableOperation.REVOKE,
        outcome=RouteOutcome.AWAITING_CONFIRMATION,
        confirmation=card(RoutableOperation.REVOKE),
    )

    assert routed.confirmation is not None
    assert routed.confirmation.operation is routed.operation


@pytest.mark.parametrize(
    "outcome",
    [RouteOutcome.PERFORMED, RouteOutcome.UNRECORDED, RouteOutcome.FAILED],
)
def test_a_read_only_operation_admits_its_three_outcomes(outcome: RouteOutcome) -> None:
    """Fifth invariant, positive direction: the three a read-only route can reach.

    ``PERFORMED`` carries the listing, and the other two carry none — which is what
    makes the parametrisation meaningful rather than decorative, since the listing rule
    and the tag rule disagree about what accompanies each.
    """
    listing = (read(),) if outcome is RouteOutcome.PERFORMED else None

    routed = RoutedOperation(
        operation=RoutableOperation.RECENT_READS, outcome=outcome, listing=listing
    )

    assert routed.outcome is outcome


def test_a_read_only_operation_carrying_a_valid_confirmation_is_refused() -> None:
    """Fifth invariant: ``AWAITING_CONFIRMATION`` is a statement §7 never makes.

    The card is **wholly valid** — one ``Question``, its own operation, a real token —
    so what is refused here is the *tag* rule and not the card. §7 never offers a
    confirmation for a read-only operation, so an outcome claiming one would describe a
    park that could not have been registered.
    """
    with pytest.raises(ValidationError, match="read-only operation \\(questions\\) admits only"):
        RoutedOperation(
            operation=RoutableOperation.QUESTIONS,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card(RoutableOperation.QUESTIONS),
        )


def test_a_read_only_operation_carrying_refused_is_refused() -> None:
    """Fifth invariant: ``REFUSED`` is a statement about an answer nobody was asked for.

    §7 offers a read-only operation no confirmation, so there is nothing for the user to
    have declined.
    """
    with pytest.raises(ValidationError, match="read-only operation \\(questions\\) admits only"):
        RoutedOperation(operation=RoutableOperation.QUESTIONS, outcome=RouteOutcome.REFUSED)


@pytest.mark.parametrize("outcome", [RouteOutcome.AMBIGUOUS, RouteOutcome.AMBIGUOUS_TRUNCATED])
def test_a_read_only_operation_carrying_an_ambiguous_outcome_is_refused(
    outcome: RouteOutcome,
) -> None:
    """Fifth invariant: a read-only route runs no lookup, so it has nothing to be about.

    §5: such an operation "takes no query and resolves no argument", and is performed
    exactly as the promoted surface declares it. The listing here is otherwise valid —
    two real ``Question`` rows of the operation's own arm — so the refusal is the tag
    rule and not the arm rule.
    """
    with pytest.raises(ValidationError, match="read-only operation \\(questions\\) admits only"):
        RoutedOperation(
            operation=RoutableOperation.QUESTIONS,
            outcome=outcome,
            listing=(question("q-1"), question("q-2")),
        )


def test_a_read_only_operation_carrying_not_found_and_no_listing_is_refused() -> None:
    """Fifth invariant, on **the one combination that isolates it** (ADR-0197 §12).

    §12 requires this asserted "with the same operation carrying ``NOT_FOUND`` and
    ``listing`` **``None``** — that last combination and no other, because a read-only
    ``NOT_FOUND`` *with* a listing is already refused by the listing invariant above, so
    a test written that way passes against a validator with no tag-to-outcome rule at
    all."

    So the value here is correct on every clause but the tag rule: ``NOT_FOUND`` carries
    no listing and no confirmation, and an implementation that only implemented §8's
    listing and confirmation rules would construct it happily. The message asserted is
    the tag rule's own, which is what stops the case passing for the wrong reason.
    """
    with pytest.raises(ValidationError, match="read-only operation \\(questions\\) admits only"):
        RoutedOperation(operation=RoutableOperation.QUESTIONS, outcome=RouteOutcome.NOT_FOUND)


@pytest.mark.parametrize("outcome", list(RouteOutcome))
def test_a_confirm_owed_operation_admits_all_eight_outcomes(outcome: RouteOutcome) -> None:
    """Fifth invariant, the confirm-owed direction — the closed set is the whole enum.

    Stated as a set per tag rather than as the exclusions the pipeline happens to
    notice, which is what keeps §8's claim true "when a ninth member is added to
    ``RouteOutcome`` rather than silently admitting it on both tags". A member added
    without a decision fails on the read-only side above and passes here, which is the
    asymmetry the two directions exist to expose.
    """
    routed = RoutedOperation(
        operation=RoutableOperation.FORGET,
        outcome=outcome,
        listing=(belief(),)
        if outcome in {RouteOutcome.AMBIGUOUS, RouteOutcome.AMBIGUOUS_TRUNCATED}
        else None,
        confirmation=card() if outcome is RouteOutcome.AWAITING_CONFIRMATION else None,
    )

    assert routed.outcome is outcome


# --- TurnOutcome: the mutual exclusion and §8's four routed shapes -----------


def test_an_outcome_carries_a_route_or_a_step_but_never_both() -> None:
    """§8's mutual exclusion: a pass that routed drove no step.

    §1 ends the pipeline at a taken route — "no plan is made or persisted, no step is
    driven" — so an outcome carrying both would be describing two passes.
    """
    with pytest.raises(ValidationError, match="never both"):
        TurnOutcome(
            turn=None,
            step=parked_step(),
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED
            ),
            reply="done",
        )


def test_a_routed_non_park_carries_its_reply_beside_a_none_turn() -> None:
    """§8's first routed shape, and the partial supersession of ADR-0170 §4.

    That section refused a reply beside a ``None`` turn because "a recovered park
    persisted no context and no memories, so there was nothing to compose from". That
    reason is true of a recovered park and **false** of a routed pass, where there is
    something to compose from — the operation and its outcome — and the outcome shows it
    in the member the prose is about.
    """
    outcome = TurnOutcome(
        turn=None,
        reply="I destroyed that belief.",
        routed=RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED),
    )

    assert outcome.reply == "I destroyed that belief."
    assert outcome.turn is None


def test_a_routed_pass_whose_composition_failed_carries_the_degradation() -> None:
    """§8's second routed shape — the one a naive validator silently forbids.

    §10 requires a composition failure on a routed pass to degrade it exactly as
    ADR-0170 §8 rules: ``reply`` ``None``, ``reply_degraded`` ``True``, the outcome
    returned rather than raised, "and the routed operation's own outcome is unaffected
    by it. An operation that ran is still reported as having run."

    A validator written as "a routed pass carries a reply" would refuse this shape, and
    every other case in this module would still pass — which is why §12 names it.
    """
    outcome = TurnOutcome(
        turn=None,
        reply=None,
        reply_degraded=True,
        routed=RoutedOperation(operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED),
    )

    assert outcome.reply is None
    assert outcome.reply_degraded is True
    assert outcome.routed is not None
    assert outcome.routed.outcome is RouteOutcome.PERFORMED


def test_a_routed_park_carries_neither_a_reply_nor_a_degradation() -> None:
    """§8's third routed shape: a routed park owes no answer at all.

    §10: on a routed park "the composing stage is not reached, originates no model call,
    and ``reply_degraded`` stays ``False``" — ADR-0170 §4's rule for a parked step, for
    its own reason: the confirmation is what the user must answer, and prose beside it
    competes with the question.
    """
    outcome = TurnOutcome(
        turn=None,
        routed=RoutedOperation(
            operation=RoutableOperation.FORGET,
            outcome=RouteOutcome.AWAITING_CONFIRMATION,
            confirmation=card(),
        ),
    )

    assert outcome.reply is None
    assert outcome.reply_degraded is False


def test_a_routed_park_carrying_a_reply_is_refused() -> None:
    """The negative half of the shape above, in the ``reply`` direction."""
    with pytest.raises(ValidationError, match="routed park must carry no reply"):
        TurnOutcome(
            turn=None,
            reply="I have asked you to confirm.",
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET,
                outcome=RouteOutcome.AWAITING_CONFIRMATION,
                confirmation=card(),
            ),
        )


def test_a_routed_park_carrying_a_degradation_is_refused() -> None:
    """The negative half in the flag direction, which is the one that says *why*.

    Without it a park could report a composition failure for a composition that was
    never attempted, and a client could not tell "no answer was owed" from "an answer
    was owed and could not be composed" — the distinction the flag exists for.
    """
    with pytest.raises(ValidationError, match="routed park owes no answer"):
        TurnOutcome(
            turn=None,
            reply_degraded=True,
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET,
                outcome=RouteOutcome.AWAITING_CONFIRMATION,
                confirmation=card(),
            ),
        )


def test_a_routed_pass_that_owed_an_answer_and_carries_none_is_refused() -> None:
    """The silent-``None`` case, which is an answer the user never got.

    §8: "a routed pass **owes an answer** exactly when ``routed`` is non-``None`` and
    ``routed.outcome`` is not ``AWAITING_CONFIRMATION``". A bare ``None`` there is
    refused so nobody has to guess whether the answer was withheld or lost.
    """
    with pytest.raises(ValidationError, match="routed pass owed an answer"):
        TurnOutcome(
            turn=None,
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED
            ),
        )


def test_a_recovered_park_still_refuses_a_reply() -> None:
    """§8's fourth case, and the one that pins the supersession as **narrow**.

    "An outcome carrying **no** ``routed`` obeys ADR-0170 §4 and ADR-0173 §6 exactly as
    before, and a **recovered** park is such an outcome: it refuses a ``reply`` after
    this decision as it did before." Without this case the suite would pin the new
    behaviour and not its scope, and an implementation that relaxed the ``None``-turn
    rule outright would pass everything above.
    """
    with pytest.raises(ValidationError, match="outcome with no turn must carry no reply"):
        TurnOutcome(turn=None, step=parked_step(), reply="composed from nothing")


def turn_that_ran() -> TurnResult:
    """One wholly valid turn, for the case that must reach the routed validator.

    Built in full rather than faked, because the field is validated **before** the
    model validator runs: a malformed ``turn`` fails on ``TurnResult``'s own required
    fields and never reaches §8's clause, so the case would pass for the wrong reason.
    """
    goal = Goal(
        id="g-1",
        statement="forget that I like jazz",
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=AT),
        created_at=AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=AT, time_of_day=TimeOfDay.AFTERNOON, is_weekend=False, within_working_hours=True
        ),
        memories=(),
        plan=ActionPlan(
            id="p-1",
            goal_id=goal.id,
            steps=(PlanStep(id="s-1", intent="send the note", capability="send_email"),),
            created_at=AT,
        ),
    )


def test_a_routed_outcome_carrying_a_turn_is_refused() -> None:
    """§8: a routed pass produces no ``TurnResult``, so it may not claim one.

    "``TurnResult``'s ``plan`` is required, and the only ``ActionPlan`` a routed pass
    could supply is one nobody planned" — persisting a planner's decision the planner
    never made is ADR-0170 §3's refusal of ``ActionPlan.rationale`` as a home for an
    answer, arriving one type further out.

    The turn handed in is **wholly valid**, so what is refused is the combination and
    not the turn: a case built on a malformed one would fail on ``TurnResult``'s own
    fields and pass against an implementation with no such clause at all.
    """
    with pytest.raises(ValidationError, match="mints no goal"):
        TurnOutcome(
            turn=turn_that_ran(),
            reply="done",
            routed=RoutedOperation(
                operation=RoutableOperation.FORGET, outcome=RouteOutcome.PERFORMED
            ),
        )


# --- RoutedOperationRecord: §9's roster and its two-directional validator ----


def test_a_row_carries_exactly_the_seven_fields_section_nine_names() -> None:
    """§9: "exactly seven fields and no others", and the roster is the guarantee.

    "The record carries **no content**: no query, no utterance, no belief text, no
    listing, no reason, and no free text of any kind." That is ADR-0185 §2's ground — a
    trail row is a statement about a decision, not a copy of what the decision was about
    — and it is what makes the row safe to keep after the belief it names is destroyed.

    Pinned as a roster because an eighth field is exactly how content would arrive, and
    a prose assertion about "no content" cannot see one being added.
    """
    assert list(RoutedOperationRecord.model_fields) == [
        "id",
        "route_id",
        "decided_at",
        "operation",
        "approval",
        "subject",
        "conversation_id",
    ]


@pytest.mark.parametrize("value", _READ_ONLY)
def test_a_read_only_row_is_always_not_owed(value: str) -> None:
    """§9's validator, first direction: a read-only operation is never confirmed.

    §7 offers it no confirmation, so ``OWED``, ``GIVEN`` and ``REFUSED`` are all
    statements about an exchange that never happened.
    """
    row = RoutedOperationRecord(
        id="row-1",
        route_id="route-1",
        decided_at=AT,
        operation=RoutableOperation(value),
        approval=RouteApproval.NOT_OWED,
    )

    assert row.approval is RouteApproval.NOT_OWED


@pytest.mark.parametrize("value", _READ_ONLY)
@pytest.mark.parametrize(
    "approval", [RouteApproval.OWED, RouteApproval.GIVEN, RouteApproval.REFUSED]
)
def test_a_read_only_row_carrying_an_approval_is_refused(
    value: str, approval: RouteApproval
) -> None:
    """The refusal half, over every approval a read-only row could wrongly carry."""
    with pytest.raises(ValidationError, match="is read-only, so its row is always NOT_OWED"):
        RoutedOperationRecord(
            id="row-1",
            route_id="route-1",
            decided_at=AT,
            operation=RoutableOperation(value),
            approval=approval,
        )


@pytest.mark.parametrize("value", _CONFIRM_OWED)
@pytest.mark.parametrize(
    "approval", [RouteApproval.OWED, RouteApproval.GIVEN, RouteApproval.REFUSED]
)
def test_a_confirm_owed_row_carries_one_of_the_three_approvals(
    value: str, approval: RouteApproval
) -> None:
    """§9's validator, second direction, positive half.

    A confirm-owed route writes two rows — ``OWED`` when the router put the question,
    then ``GIVEN`` or ``REFUSED`` when the user answered it — "two facts about two
    moments, in an append-only trail that cannot revise the first when the second
    arrives".
    """
    row = RoutedOperationRecord(
        id="row-1",
        route_id="route-1",
        decided_at=AT,
        operation=RoutableOperation(value),
        approval=approval,
        subject="subject-1",
    )

    assert row.approval is approval


@pytest.mark.parametrize("value", _CONFIRM_OWED)
def test_a_confirm_owed_row_is_never_not_owed(value: str) -> None:
    """The refusal half, and it is the direction that costs a user the most.

    A destruction filed as ``NOT_OWED`` is a row an operator would read as evidence that
    the act needed no approval — which is the one claim the trail exists to be able to
    contradict, since a routed ``forget`` destroys the only other evidence of itself.
    """
    with pytest.raises(ValidationError, match="is confirm-owed, so its row is never NOT_OWED"):
        RoutedOperationRecord(
            id="row-1",
            route_id="route-1",
            decided_at=AT,
            operation=RoutableOperation(value),
            approval=RouteApproval.NOT_OWED,
            subject="subject-1",
        )


def test_the_route_approval_vocabulary_is_exactly_section_nine_s_four_members() -> None:
    """§9 fixes four, and ``OWED`` is the one whose meaning is easiest to overstate.

    "``RouteApproval.OWED`` states that **the router decided to seek the user's
    confirmation**… It does **not** state that a card was rendered, delivered, or seen…
    No surface renders an ``OWED`` row as 'you were asked'." The values are pinned
    because a stored row carries them.
    """
    assert [member.value for member in RouteApproval] == [
        "not_owed",
        "owed",
        "given",
        "refused",
    ]
