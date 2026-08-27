"""``ToolInvocation``, ``RecordedInvocation``, the cost field and its carrier.

ADR-0192 §§2 and 5 for the row and the field; ADR-0195 §2 for ``ReportedOutput``,
the envelope a successful call composes to put a figure *into* that field.

The row has **exactly two well-formed shapes** and a validator refuses every other
combination at construction. That is ADR-0029 §3's standard — the
self-contradictory combinations are *unrepresentable* rather than discouraged —
and §10 of that ADR is how it was met there: a rejection test for each. So the
table below is exhaustive over the four fields' presence rather than illustrative,
because a validator checking ``completes`` against ``outcome`` alone accepts a
completion with no cost, which then reaches a spend accumulator and ADR-0192 §4's
rendering floor as a completion with no price.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    CostBasis,
    RecordedInvocation,
    ReportedOutput,
    ToolCost,
    ToolFailure,
    ToolFailureKind,
    ToolInvocation,
    ToolOutcome,
    ToolResult,
)

AT: Final = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
UNKNOWN: Final = ToolCost(basis=CostBasis.UNKNOWN)
PRICED: Final = ToolCost(basis=CostBasis.PER_CALL, amount=Decimal("0.25"), currency="USD")


def _row(**overrides: object) -> dict[str, object]:
    """The two mandatory members, plus whichever optional ones a case is about."""
    fields: dict[str, object] = {"id": "inv-1", "decision_id": "d-1", "recorded_at": AT}
    fields.update(overrides)
    return fields


def _well_formed(*, completes: bool, outcome: ToolOutcome | None, cost: bool, kind: bool) -> bool:
    """Whether ADR-0192 §2's two shapes admit this combination.

    Written as the ADR states it rather than as the validator implements it, so the
    table is evidence about the contract and not a restatement of the code.
    """
    if not completes:
        return outcome is None and not cost and not kind
    if outcome is None or not cost:
        return False
    return not (kind and outcome is ToolOutcome.SUCCEEDED)


#: Every combination of the four discriminating fields' presence, with each
#: ``outcome`` value spelled out, because ``failure_kind``'s admissibility turns on
#: which one it is and not merely on whether one is there.
_COMBINATIONS: Final = [
    (completes, outcome, cost, kind)
    for completes, cost, kind in itertools.product([False, True], repeat=3)
    for outcome in (None, ToolOutcome.SUCCEEDED, ToolOutcome.FAILED, ToolOutcome.INDETERMINATE)
]


@pytest.mark.parametrize(("completes", "outcome", "cost", "kind"), _COMBINATIONS)
def test_only_a_claim_or_a_completion_constructs(
    *, completes: bool, outcome: ToolOutcome | None, cost: bool, kind: bool
) -> None:
    fields = _row()
    if completes:
        fields["completes"] = "inv-0"
    if outcome is not None:
        fields["outcome"] = outcome
    if cost:
        fields["incurred_cost"] = UNKNOWN
    if kind:
        fields["failure_kind"] = ToolFailureKind.TIMED_OUT

    if _well_formed(completes=completes, outcome=outcome, cost=cost, kind=kind):
        assert ToolInvocation(**fields)  # type: ignore[arg-type]  # heterogeneous table
    else:
        with pytest.raises(ValidationError):
            ToolInvocation(**fields)  # type: ignore[arg-type]  # heterogeneous table


def test_the_table_covers_every_shape_and_rejects_far_more_than_it_admits() -> None:
    """A guard on the table itself, so a future edit cannot quietly empty it.

    Six admissible rows: the claim, and five completions — a ``SUCCEEDED`` one,
    which carries no kind at all, plus each of the two non-success outcomes with
    and without a reported kind.
    """
    accepted = [
        (completes, outcome, cost, kind)
        for completes, outcome, cost, kind in _COMBINATIONS
        if _well_formed(completes=completes, outcome=outcome, cost=cost, kind=kind)
    ]

    assert len(accepted) == 6, f"one claim shape and five completions, got {accepted}"
    assert len(_COMBINATIONS) - len(accepted) > 4 * len(accepted)


def test_a_claim_is_the_absence_of_every_completion_field() -> None:
    claim = ToolInvocation(**_row())  # type: ignore[arg-type]  # heterogeneous builder

    assert claim.completes is None
    assert claim.outcome is None
    assert claim.incurred_cost is None
    assert claim.failure_kind is None


@pytest.mark.parametrize(
    "outcome", [ToolOutcome.FAILED, ToolOutcome.INDETERMINATE], ids=["failed", "indeterminate"]
)
def test_a_kindless_non_success_completion_is_well_formed(outcome: ToolOutcome) -> None:
    """The shape a cancellation-derived completion has, and no lane may fill it.

    ADR-0031 §3 rules that the seam never synthesises ``CANCELLED``, and no other
    member of ``ToolFailureKind`` describes an externally delivered cancellation.
    The absence is the honest value and is readable as one: a non-success this
    system observed without a reported cause.
    """
    completion = ToolInvocation(
        **_row(completes="inv-0", outcome=outcome, incurred_cost=UNKNOWN)  # type: ignore[arg-type]  # heterogeneous builder
    )

    assert completion.failure_kind is None


def test_a_succeeded_completion_carrying_a_kind_is_unconstructable() -> None:
    with pytest.raises(ValidationError, match="failure_kind"):
        ToolInvocation(
            **_row(  # type: ignore[arg-type]  # heterogeneous builder
                completes="inv-0",
                outcome=ToolOutcome.SUCCEEDED,
                incurred_cost=UNKNOWN,
                failure_kind=ToolFailureKind.TIMED_OUT,
            )
        )


def test_a_completion_with_no_cost_is_unconstructable() -> None:
    """The combination a ``completes``-versus-``outcome`` validator accepts.

    It would reach the accumulator and the rendering floor as a completion with no
    price, which is the absence ADR-0192 §5 exists to make unrepresentable.
    """
    with pytest.raises(ValidationError, match="incurred_cost"):
        ToolInvocation(
            **_row(completes="inv-0", outcome=ToolOutcome.FAILED)  # type: ignore[arg-type]  # heterogeneous builder
        )


def test_the_row_carries_exactly_the_seven_fields_the_adr_declares() -> None:
    """No ``ToolDefinition``, no digest, no step, no execution, no ordinal, no content."""
    assert set(ToolInvocation.model_fields) == {
        "id",
        "decision_id",
        "recorded_at",
        "completes",
        "outcome",
        "incurred_cost",
        "failure_kind",
    }


def test_the_row_is_frozen_and_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        ToolInvocation(**_row(step_id="s-1"))  # type: ignore[arg-type]  # the extra is the case


def test_a_naive_recorded_at_is_refused() -> None:
    """The trail is durable *and ordered*, so a naive instant is refused not assumed."""
    with pytest.raises(ValidationError):
        ToolInvocation(**_row(recorded_at=datetime(2026, 7, 20, 12, 0)))  # type: ignore[arg-type]  # noqa: DTZ001 — the fault under test


# --- the joined value --------------------------------------------------------


def _claim() -> ToolInvocation:
    return ToolInvocation(**_row())  # type: ignore[arg-type]  # heterogeneous builder


def test_a_recorded_invocation_carries_the_row_and_three_facts_about_its_decision() -> None:
    joined = RecordedInvocation(
        invocation=_claim(), tool="smtp", capability="send_email", egress_call=True
    )

    assert joined.invocation == _claim()
    assert joined.tool == "smtp"
    assert joined.capability == "send_email"
    assert joined.egress_call is True


def test_a_recorded_invocation_carries_nothing_else() -> None:
    """No ruling, no reason, no binding, no destination, no digest, no definition."""
    assert set(RecordedInvocation.model_fields) == {
        "invocation",
        "tool",
        "capability",
        "egress_call",
    }


def test_a_recorded_invocation_forbids_extras() -> None:
    with pytest.raises(ValidationError):
        RecordedInvocation(
            invocation=_claim(),
            tool="smtp",
            capability="send_email",
            egress_call=False,
            destination="alice@example.com",  # type: ignore[call-arg]  # the extra is the case
        )


def test_an_invisible_tool_identifier_is_refused() -> None:
    """``VisibleIdentifier``: these are shown to the user beside what happened."""
    with pytest.raises(ValidationError):
        RecordedInvocation(
            invocation=_claim(), tool="\u200b", capability="send_email", egress_call=False
        )


# --- what a call reported it cost (ADR-0192 §5) ------------------------------


def test_a_result_reports_no_figure_by_default() -> None:
    """``None`` states that the tool reported no figure, and the row records ``UNKNOWN``.

    Still what every registered tool in this tree produces, and a budget over it
    fails closed. Since ADR-0195 a tool *may* populate it — by returning a
    :class:`ReportedOutput` on the success exit — but nothing is obliged to, and
    the two exits the tool does not compose report nothing at all.
    """
    assert ToolResult(outcome=ToolOutcome.SUCCEEDED).incurred_cost is None


def test_a_result_may_report_a_measured_figure() -> None:
    result = ToolResult(outcome=ToolOutcome.SUCCEEDED, incurred_cost=PRICED)

    assert result.incurred_cost == PRICED


def test_a_failed_result_may_report_what_it_spent_before_failing() -> None:
    """A call that cost something and then failed is not free."""
    result = ToolResult(
        outcome=ToolOutcome.FAILED,
        failure=ToolFailure(kind=ToolFailureKind.TIMED_OUT, message="upstream did not answer"),
        incurred_cost=PRICED,
    )

    assert result.incurred_cost == PRICED


def test_an_unknown_basis_is_the_value_for_not_knowing() -> None:
    """ADR-0016 §4's distinction, which is why the field is a ``ToolCost``.

    "The distinction that matters to a policy is not present/absent but *free*
    versus *unknown*" — so a tool whose billing is asynchronous reports ``UNKNOWN``
    and never a number it constructed to fill the field, which is the fiction
    ADR-0029 §3 refused the field over.
    """
    result = ToolResult(outcome=ToolOutcome.SUCCEEDED, incurred_cost=UNKNOWN)

    assert result.incurred_cost is not None
    assert result.incurred_cost.basis is CostBasis.UNKNOWN
    assert result.incurred_cost.amount is None


# --- the carrier a successful call composes (ADR-0195 §2) --------------------


def test_the_envelope_carries_an_output_and_the_figure_together() -> None:
    """The whole of what a tool reports on the exit it composes by returning."""
    envelope = ReportedOutput(output={"sent": True}, incurred_cost=PRICED)

    assert envelope.output == {"sent": True}
    assert envelope.incurred_cost == PRICED


def test_an_envelope_without_a_figure_is_refused() -> None:
    """``incurred_cost`` is required, and this is the case that holds it required.

    Every behavioural case in the seam's suite supplies a cost, so an
    implementation that defaulted this field — to ``UNKNOWN``, say — would pass
    all of them while minting a second spelling of a bare return. ADR-0195 §2
    makes the field required to foreclose exactly that, and the Alternatives
    section's answer to ADR-0032's "two spellings of one thing" objection rests
    on it.
    """
    with pytest.raises(ValidationError, match="incurred_cost"):
        ReportedOutput(output={"sent": True})  # type: ignore[call-arg]  # the point of the case


def test_an_envelope_may_report_a_figure_over_no_output_at_all() -> None:
    """``output`` defaults, because a priced call need not produce a value."""
    envelope = ReportedOutput(incurred_cost=PRICED)

    assert envelope.output is None


def test_an_unknown_basis_in_an_envelope_is_permitted() -> None:
    """ADR-0195 §5: it lands identically to reporting nothing, and is not refused.

    An integration computing a figure from a tariff table that sometimes yields
    ``UNKNOWN`` would otherwise have to branch at its return statement to avoid
    tripping a validator, and refusing a value that is *true* would convert an
    honest report into a failed call.
    """
    assert ReportedOutput(incurred_cost=UNKNOWN).incurred_cost.basis is CostBasis.UNKNOWN


def test_the_envelope_states_no_outcome_and_none_can_be_added() -> None:
    """It carries a price and never what the seam rules (ADR-0031 §2, ADR-0195 §2).

    ``extra="forbid"`` is what stops an outcome, a failure kind or a disclosure
    report being smuggled onto a value the tool composes: a callable's own
    account of what happened to it is not evidence, and the two fields here are
    the whole of what it may say.
    """
    assert set(ReportedOutput.model_fields) == {"output", "incurred_cost"}
    with pytest.raises(ValidationError, match="outcome"):
        ReportedOutput(incurred_cost=PRICED, outcome=ToolOutcome.SUCCEEDED)  # type: ignore[call-arg]  # the point of the case


def test_the_envelope_is_frozen() -> None:
    """A figure that could be rewritten after the seam read it is not a report."""
    envelope = ReportedOutput(incurred_cost=PRICED)

    with pytest.raises(ValidationError):
        envelope.incurred_cost = UNKNOWN


def test_an_output_the_annotation_refuses_raises_in_the_tools_own_frame() -> None:
    """``output`` is ``FrozenJsonValue``, so the envelope opens no new route.

    A value ``ToolResult.output`` would refuse is refused here too, at the
    envelope's own construction — which is *inside* the callable, so it escapes
    as an ordinary exception and the seam classifies it ``INTERNAL``, exactly
    where the same value lands when it is returned bare (ADR-0029 §3).
    """
    with pytest.raises(ValidationError):
        ReportedOutput(output={1, 2}, incurred_cost=PRICED)  # type: ignore[arg-type]  # the point


def test_an_envelope_cannot_nest_inside_another() -> None:
    """``FrozenJsonValue`` admits no ``BaseModel``, so no unwrapping loop is owed."""
    nested = ReportedOutput(incurred_cost=PRICED)

    with pytest.raises(ValidationError):
        # The annotation refuses it statically too, which is the stronger half:
        # `mypy` rejects this argument, so the runtime refusal is the backstop.
        ReportedOutput(output=nested, incurred_cost=PRICED)  # type: ignore[arg-type]  # the point
