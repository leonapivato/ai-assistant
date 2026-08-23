"""ADR-0181 §3's field on the three models it names, and what each refuses.

§10's first clause states four cases in terms and this module is them: that a
``CarriedProvenance``, an ``EgressBinding`` and a ``ConfirmationEgress`` each refuse
construction with the field **omitted**, and that
``PermissionDecision.authorises`` answers ``False`` for two bindings identical but
for it. The last is the one that bites: it fails an implementation that exempted
the field from the comparison, which is the repair a lane reaches for when a
resumed call is refused (§3's sixth clause, §5's sixth).

**The refusals are the substance rather than the style**, and ADR-0181 §3 gives the
argument as ADR-0150 §5's: "a defaulted field is what a lane forgets". Here the
safe-looking default is ``False``, which reads as *nothing external was in front of
the model* — a claim about a selection the defaulting lane never made. A test that
only constructed a well-formed value would satisfy none of the clause.

**Nothing here states or implies that the field detects anything.** It records that
material this system *selected* included a record resting on recorded external
content; ADR-0098 §5 and ADR-0106 §1 bind it verbatim, and ADR-0181 §2's second
clause forbids any surface, consumer or test from reading it as influence.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    ActionRequest,
    BoundAccount,
    CarriedProvenance,
    ConfirmationEgress,
    CostBasis,
    DataTier,
    DiscloserProvenance,
    EgressBinding,
    EgressSpan,
    EgressSpanLocator,
    Idempotency,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

_AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
_ACCOUNT = BoundAccount(identity="work@example.com", reference="conn-0001")
_ENDPOINT = "test://endpoint/one"
_SPAN = EgressSpan(
    argument="body",
    provenance=DiscloserProvenance.SYSTEM_SELECTED,
    extent=5,
)

_TOOL = ToolDefinition(
    id="smtp",
    capability="send_email",
    description="Send an email.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NATURAL,
    parameters_schema={"type": "object"},
)


def _binding(*, planned_with_external_content: bool) -> EgressBinding:
    """A one-span binding differing from its twin in exactly this field."""
    return EgressBinding(
        spans=(_SPAN,),
        account=_ACCOUNT,
        transport_endpoint=_ENDPOINT,
        planned_with_external_content=planned_with_external_content,
    )


def _request(binding: EgressBinding) -> ActionRequest:
    """The request the policy rules on, carrying ``binding`` whole."""
    return ActionRequest(
        tool=_TOOL,
        parameters={"body": "hello"},
        step_id="step-1",
        execution_id="exec-1",
        egress_binding=binding,
    )


def _allowing(request: ActionRequest) -> PermissionDecision:
    """A recorded ``ALLOW`` for ``request``, so ``authorises``'s first conjunct holds."""
    return PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="a rule allowed it"),
        id="d-1",
        decided_at=_AT,
    )


# --- §3, §10: construction refuses omission, on each of the three models ------


def test_a_carrier_refuses_construction_with_the_field_omitted() -> None:
    """ADR-0181 §3's first clause: required, with no default."""
    with pytest.raises(ValidationError, match=r"planned_with_external_content"):
        CarriedProvenance(spans={})  # type: ignore[call-arg]  # the omission under test


def test_a_binding_refuses_construction_with_the_field_omitted() -> None:
    """ADR-0181 §3's second clause: required, with no default."""
    with pytest.raises(ValidationError, match=r"planned_with_external_content"):
        EgressBinding(  # type: ignore[call-arg]  # the omission under test
            spans=(_SPAN,), account=_ACCOUNT, transport_endpoint=_ENDPOINT
        )


def test_a_confirmation_egress_refuses_construction_with_the_field_omitted() -> None:
    """ADR-0181 §3's third clause: required, with no default."""
    with pytest.raises(ValidationError, match=r"planned_with_external_content"):
        ConfirmationEgress(  # type: ignore[call-arg]  # the omission under test
            account_identity=_ACCOUNT.identity, spans=(_SPAN,)
        )


@pytest.mark.parametrize("stated", [True, False])
def test_each_model_keeps_the_value_it_was_given(stated: bool) -> None:
    """Both states are constructible, and neither is normalised on the way in.

    The ``False`` half is not padding: ADR-0181 §6's fourth clause renders the fact
    in **both** states, so a model that quietly dropped a ``False`` would leave a
    surface with nothing to render on exactly the calls whose silence a user learns
    to read as clearance.
    """
    carrier = CarriedProvenance(spans={}, planned_with_external_content=stated)
    binding = _binding(planned_with_external_content=stated)
    reduced = ConfirmationEgress(
        account_identity=_ACCOUNT.identity,
        spans=(_SPAN,),
        planned_with_external_content=stated,
    )

    assert carrier.planned_with_external_content is stated
    assert binding.planned_with_external_content is stated
    assert reduced.planned_with_external_content is stated


def test_the_carrier_holds_the_two_facts_it_carries_and_no_third() -> None:
    """ADR-0181 §3: one field added to the carrier, and ADR-0152 §1's is unchanged.

    The span mapping still answers ADR-0146 §1's axis — *who disclosed this span* —
    and the new field answers ADR-0181 §1's third: whether this system's selection
    rested on recorded external content. §1's third clause forbids reading either as
    an answer on the other, and the type keeps them apart by holding both.
    """
    assert set(CarriedProvenance.model_fields) == {"spans", "planned_with_external_content"}
    assert all(field.is_required() for field in CarriedProvenance.model_fields.values())

    carrier = CarriedProvenance(
        spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
        planned_with_external_content=True,
    )

    assert carrier.spans[EgressSpanLocator(argument="body")] is DiscloserProvenance.USER_AUTHORED
    assert carrier.planned_with_external_content is True


# --- §3's fourth clause, §10: `authorises` compares it with the rest -----------


def test_authorises_answers_false_across_this_field_alone() -> None:
    """ADR-0181 §10's third case, which fails an implementation that exempted it.

    The two bindings are equal in every other member — same spans, same account,
    same endpoint — so nothing but this field can make the comparison fail. It is
    compared because it is a member of the binding and the fifth conjunct compares
    the binding **whole and by value** (ADR-0150 §9); no conjunct was added for it,
    and ADR-0181 §3's fourth clause is explicit that none may be.
    """
    approved = _request(_binding(planned_with_external_content=True))
    decision = _allowing(approved)

    offered = _request(_binding(planned_with_external_content=False))

    assert decision.authorises(approved) is True, "the baseline: the same call is authorised"
    assert decision.authorises(offered) is False
    assert offered.parameters_digest == approved.parameters_digest, (
        "the digests agree, so the refusal is this field's and not the payload's"
    )


def test_authorises_answers_false_in_the_other_direction_too() -> None:
    """The mirror, so the comparison is not one-sided.

    A decision recorded over a call planned over **no** external material does not
    authorise one that was — which is the substitution that would matter, since the
    approver was shown the ``False``.
    """
    approved = _request(_binding(planned_with_external_content=False))
    decision = _allowing(approved)

    offered = _request(_binding(planned_with_external_content=True))

    assert decision.authorises(approved) is True
    assert decision.authorises(offered) is False
