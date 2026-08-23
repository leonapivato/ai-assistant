"""The three ``core`` values ADR-0152 §2 authorises, and what each refuses.

ADR-0152 §13 states the carrier and locator cases in terms, and says what a test
that only constructs a well-formed one satisfies: none of them. So each case here
is a refusal or a detachment, and the happy path appears only where a clause is
stated in both directions.

``BoundEgressCall``'s own obligations are here too — three fields and no others,
and the two it detaches — because they are properties of the type rather than of
either implementation of the seam that returns it.
"""

from __future__ import annotations

import pickle
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import AssistantError, EgressBindingError
from ai_assistant.core.types import (
    BoundAccount,
    BoundEgressCall,
    CarriedProvenance,
    CostBasis,
    DataTier,
    DestinationProtocol,
    DiscloserProvenance,
    Disposition,
    EgressBinding,
    EgressDestination,
    EgressSpan,
    EgressSpanLocator,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

_TOOL = ToolDefinition(
    id="smtp",
    capability="send_email",
    description="send a note",
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


def _binding(
    *,
    argument: str = "to",
    index: int | None = 0,
    planned_with_external_content: bool = False,
) -> EgressBinding:
    """A one-span binding whose span sits at ``(argument, index)``."""
    return EgressBinding(
        spans=(
            EgressSpan(
                argument=argument,
                index=index,
                provenance=DiscloserProvenance.SYSTEM_SELECTED,
                extent=len("a@example.com"),
                tier=DataTier.PERSONAL,
                destination=EgressDestination(
                    protocol=DestinationProtocol.SMTP,
                    supplied="a@example.com",
                    canonical="a@example.com",
                ),
            ),
        ),
        account=BoundAccount(identity="work@example.com", reference="conn-0001"),
        transport_endpoint="test://endpoint",
        planned_with_external_content=planned_with_external_content,
    )


# --- ADR-0152 §1: the locator ------------------------------------------------


def test_a_locator_is_hashable_and_usable_as_a_mapping_key() -> None:
    """ADR-0152 §1, §13: it is a mapping key, which is the whole of what it is for."""
    locator = EgressSpanLocator(argument="to", index=0)

    holder = {locator: DiscloserProvenance.USER_AUTHORED}

    assert holder[EgressSpanLocator(argument="to", index=0)] is DiscloserProvenance.USER_AUTHORED


def test_two_locators_with_equal_fields_are_equal_and_hash_equally() -> None:
    """ADR-0152 §1: equal exactly when both fields are equal, and not otherwise."""
    one = EgressSpanLocator(argument="to", index=0)
    same = EgressSpanLocator(argument="to", index=0)
    indexless = EgressSpanLocator(argument="to")

    assert one == same
    assert hash(one) == hash(same)
    assert one != indexless
    assert len({one, same, indexless}) == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("argument", "\ud800", id="an-argument-with-no-utf8-encoding"),
        pytest.param("index", -1, id="a-negative-index"),
    ],
)
def test_a_locator_refuses_what_a_span_would_refuse(field: str, value: object) -> None:
    """ADR-0152 §1, §13: each field's type and validation are ``EgressSpan``'s own.

    A locator that could be well-formed where the span it names could not would be
    a second answer to one question, so this is asserted per field rather than over
    a well-formed one.
    """
    fields: dict[str, object] = {"argument": "to", "index": 0}
    fields[field] = value

    with pytest.raises(ValidationError):
        EgressSpanLocator(**fields)  # type: ignore[arg-type]  # the bypass under test
    with pytest.raises(ValidationError):
        EgressSpan(
            provenance=DiscloserProvenance.SYSTEM_SELECTED,
            extent=0,
            **{**fields, field: value},  # type: ignore[arg-type]  # the same value, same refusal
        )


def test_a_locator_names_exactly_the_span_whose_fields_equal_its_own() -> None:
    """ADR-0152 §1: it names the span of a binding whose ``argument`` and ``index`` match.

    And no other — which is what makes it usable as the key ``rebind`` matches a
    carried provenance by.
    """
    binding = _binding(argument="to", index=0)
    span = binding.spans[0]

    matching = EgressSpanLocator(argument=span.argument, index=span.index)

    assert matching == EgressSpanLocator(argument="to", index=0)
    assert matching != EgressSpanLocator(argument="to", index=1)
    assert matching != EgressSpanLocator(argument="cc", index=0)


def test_a_locator_carries_nothing_a_span_carries() -> None:
    """ADR-0152 §1: two fields and no others — no provenance, extent, tier or destination."""
    assert set(EgressSpanLocator.model_fields) == {"argument", "index"}


def test_a_locator_built_by_model_construct_does_not_survive_revalidation() -> None:
    """ADR-0152 §1: ``revalidate_instances="always"``, for ``SecretName``'s reason.

    ``model_construct`` builds an instance without running validators, and it is
    public — so the annotation on a seam's argument is not the enforcement.
    """
    forged = EgressSpanLocator.model_construct(argument=object(), index="nine")

    with pytest.raises(ValidationError):
        CarriedProvenance(
            spans={forged: DiscloserProvenance.SYSTEM_SELECTED},
            planned_with_external_content=False,
        )


# --- ADR-0152 §1: the carrier ------------------------------------------------


def test_a_carrier_refuses_a_key_that_is_not_a_well_formed_locator() -> None:
    """ADR-0152 §1, §13: exercised separately from the value case.

    An annotation is not a constructor: Python builds no locator for a mapping
    key, so ``{object(): …}`` would cross the boundary unchecked if the argument
    were annotated ``Mapping[EgressSpanLocator, …]`` rather than carried by a
    model that validates on construction (ADR-0150 §8).
    """
    with pytest.raises(ValidationError):
        CarriedProvenance(
            spans={object(): DiscloserProvenance.USER_AUTHORED},  # type: ignore[dict-item]  # the bypass under test
            planned_with_external_content=False,
        )


def test_a_carrier_refuses_a_value_that_is_not_a_discloser_provenance() -> None:
    """ADR-0152 §1, §13: one of ADR-0146 §1's two members, and no third."""
    with pytest.raises(ValidationError):
        CarriedProvenance(
            spans={EgressSpanLocator(argument="to"): "hearsay"},  # type: ignore[dict-item]  # the bypass under test
            planned_with_external_content=False,
        )


def test_a_carrier_does_not_change_when_the_caller_mutates_what_it_passed() -> None:
    """ADR-0152 §1, §13: detached at validation (ADR-0018 §3).

    ``frozen=True`` protects the field, not the object the field points at, so a
    carrier validated over a caller's ``dict`` would otherwise leave the caller
    able to rewrite what the seam then reads — across the seam's own awaited read,
    which is precisely the window the detachment closes.
    """
    caller_holds = {EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED}
    carrier = CarriedProvenance(spans=caller_holds, planned_with_external_content=False)

    caller_holds[EgressSpanLocator(argument="to")] = DiscloserProvenance.SYSTEM_SELECTED
    caller_holds[EgressSpanLocator(argument="body")] = DiscloserProvenance.SYSTEM_SELECTED

    assert len(carrier.spans) == 1
    assert carrier.spans[EgressSpanLocator(argument="body")] is DiscloserProvenance.USER_AUTHORED


def test_a_carrier_omitting_spans_is_refused() -> None:
    """ADR-0152 §1, §13: no default, so a caller holding no origin says so deliberately.

    ADR-0150 §5's no-default reasoning applied at the seam that would otherwise
    inherit the permissive answer for free.
    """
    with pytest.raises(ValidationError):
        CarriedProvenance()  # type: ignore[call-arg]  # the omission under test


def test_a_carrier_over_an_empty_mapping_is_well_formed() -> None:
    """ADR-0152 §1: the deliberate empty carrier, which is today's every call (§5)."""
    carrier = CarriedProvenance(spans={}, planned_with_external_content=False)

    assert len(carrier.spans) == 0
    assert dict(carrier.spans) == {}


def test_a_carriers_mapping_refuses_mutation_and_survives_a_round_trip() -> None:
    """ADR-0152 §1: immutable, and copyable — ``FrozenDict``'s two requirements.

    ``MappingProxyType`` would satisfy the first and fail the second, which is why
    ``core`` does not use one: any model holding it would fail
    ``model_copy(deep=True)``.
    """
    carrier = CarriedProvenance(
        spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
        planned_with_external_content=False,
    )

    with pytest.raises(TypeError):
        carrier.spans["x"] = DiscloserProvenance.SYSTEM_SELECTED  # type: ignore[index]  # immutability under test
    with pytest.raises(AttributeError):
        carrier.spans.anything = 1  # type: ignore[attr-defined]  # immutability under test

    assert carrier.model_copy(deep=True).spans == carrier.spans
    assert pickle.loads(pickle.dumps(carrier.spans)) == carrier.spans  # noqa: S301 — this module's own bytes
    assert carrier.model_dump()["spans"] == [
        {"span": {"argument": "body", "index": None}, "provenance": "user_authored"}
    ]


# --- ADR-0152 §1: the returned pair ------------------------------------------


def test_a_bound_call_carries_exactly_three_fields() -> None:
    """ADR-0152 §1: and no provenance field.

    A span's provenance is already inside the binding, and a second copy beside it
    would be two shapes of one fact — the duplication ADR-0150 is named against.
    ``rebind`` has no ``provenance`` argument at all, so such a field would also be
    filled from a different source per member, for no consumer.
    """
    assert set(BoundEgressCall.model_fields) == {"binding", "tool", "parameters"}


def test_a_bound_call_detaches_the_tool_it_was_built_from() -> None:
    """ADR-0152 §1: ``ActionRequest``'s own reason, applied to the returned pair.

    A caller's definition rewritten through ``object.__setattr__`` would otherwise
    change what the returned value says the binding was derived under.
    """
    parameters: Mapping[str, FrozenJson] = {"to": ["a@example.com"]}
    bound = BoundEgressCall(binding=_binding(), tool=_TOOL, parameters=parameters)

    object.__setattr__(_TOOL, "id", "somebody-else")
    try:
        assert bound.tool.id == "smtp"
    finally:
        object.__setattr__(_TOOL, "id", "smtp")


def test_a_bound_call_freezes_the_parameters_it_was_built_from() -> None:
    """ADR-0152 §1: the same mapping, frozen all the way down and detached."""
    caller_holds: dict[str, FrozenJson] = {"to": ["a@example.com"], "body": "hello"}
    bound = BoundEgressCall(binding=_binding(), tool=_TOOL, parameters=caller_holds)

    caller_holds["body"] = "rewritten"

    assert bound.parameters["body"] == "hello"
    assert bound.parameters["to"] == ("a@example.com",)


def test_a_bound_call_requires_every_field() -> None:
    """ADR-0152 §1: a defaulted empty mapping would let a binding be returned beside no payload."""
    with pytest.raises(ValidationError):
        BoundEgressCall(binding=_binding(), tool=_TOOL)  # type: ignore[call-arg]  # the omission under test


# --- ADR-0152 §9: the failure class and the disposition ----------------------


def test_the_refusal_class_is_a_direct_subclass_of_the_hierarchy_root() -> None:
    """ADR-0152 §9: one class, and no subclass of it.

    ADR-0145 §4's argument decides it: every refusal ends the turn having
    disclosed nothing, asked nobody, written nothing and claimed nothing, and each
    is corrected the same way. "A second member would be a distinction visible to
    a client that cannot act on it differently."
    """
    assert EgressBindingError.__bases__ == (AssistantError,)
    assert EgressBindingError.__subclasses__() == []


def test_the_disposition_member_is_additive_and_distinguishable() -> None:
    """ADR-0152 §9, §13: distinguishable from ``DENIED`` and from ``INVALID_PARAMETERS``.

    A client that could not tell them apart would report "the assistant declined
    to send this" for a tool whose declaration is malformed, which is a falsehood
    about the user's own policy.
    """
    assert Disposition.EGRESS_UNBINDABLE.value == "egress_unbindable"
    assert Disposition("egress_unbindable") is Disposition.EGRESS_UNBINDABLE
    assert len({member.value for member in Disposition}) == len(Disposition)
    assert Disposition.EGRESS_UNBINDABLE.value not in {
        Disposition.DENIED.value,
        Disposition.INVALID_PARAMETERS.value,
        Disposition.NO_CAPABLE_TOOL.value,
    }
