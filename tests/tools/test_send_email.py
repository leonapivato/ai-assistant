"""The declaration that is complete, registered nowhere, and transmits nothing.

Two properties this file exists to keep apart. The declaration is **honest** —
ADR-0016 §1's "declared, not inferred", with every safety field stating what a
send actually risks — and the integration is **inert**: unregistered, and paired
with a callable that refuses. A lane that later designates the seam changes the
second and should not need to change the first.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from ai_assistant.core.errors import ToolError
from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolDefinition,
)
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.tools.builtin import build_default_registry
from ai_assistant.tools.destination_arguments import DestinationSelectionError
from ai_assistant.tools.destinations import canonical_destination_set
from ai_assistant.tools.payload_description import DiscloserProvenance, SpanRef
from ai_assistant.tools.send_email import (
    SEND_EMAIL,
    SEND_EMAIL_DESTINATIONS,
    SEND_EMAIL_ID,
    SEND_EMAIL_PAYLOAD,
    SendEmail,
    UndesignatedSeamError,
    describe_send_email,
)

_ARGUMENTS = {
    "to": ("bob@example.com",),
    "subject": "lunch",
    "body": "see you at one",
}


async def test_the_tool_is_not_registered_in_the_default_registry() -> None:
    """Nothing may reach a callable that would transmit (ADR-0029 §1).

    Registration is what makes a tool invocable — "invocable if and only if
    registered" — so leaving it out is the strongest available statement that the
    seam is undesignated, and it is checked rather than trusted because the factory
    is one line away from including it.
    """
    registry = build_default_registry(memory=FakeMemoryStore())

    assert await registry.get(SEND_EMAIL_ID) is None
    assert SEND_EMAIL_ID not in {tool.id for tool in await registry.all_tools()}
    assert SEND_EMAIL.capability not in await registry.capabilities()


async def test_the_callable_refuses_and_names_the_undesignated_seam() -> None:
    """ADR-0017 §2: the boundary is approved and undesignated, and transmits nothing.

    Raised rather than returned as a ``FAILED`` result, because a
    ``ToolFailure`` carries a retryable flag and there is nothing here to retry
    (the reasoning ``ToolBindingError`` is raised under).
    """
    with pytest.raises(UndesignatedSeamError) as raised:
        await SendEmail()(_ARGUMENTS, idempotency_key=None)

    assert "ai_assistant.tools.egress" in str(raised.value)
    assert "undesignated" in str(raised.value)
    assert isinstance(raised.value, ToolError)


def test_the_definition_declares_a_world_changing_irreversible_high_risk_act() -> None:
    """ADR-0016 §1: every field a permission decision depends on, stated.

    Each is asserted separately rather than by comparing the whole model, so a
    failure names which claim changed.
    """
    assert SEND_EMAIL.risk_level is RiskLevel.HIGH
    assert SEND_EMAIL.reversibility is Reversibility.IRREVERSIBLE
    assert SEND_EMAIL.side_effecting is True
    assert SEND_EMAIL.reads == (DataTier.SECRET,)
    assert SEND_EMAIL.writes == ()
    assert SEND_EMAIL.cost.basis is CostBasis.UNKNOWN
    assert SEND_EMAIL.idempotency is Idempotency.NONE
    assert SEND_EMAIL.idempotency_window is None


def test_the_definition_discloses_a_non_empty_reach() -> None:
    """ADR-0148 §8's second clause, which is what puts the user in the loop.

    "A tool registered at the seam that transmits declares a **non-empty**
    ``discloses``, so ADR-0021 §5's floor applies to every egress call and no
    egress call is auto-granted." §8 names the evasion it closes: a tool declaring
    ``discloses=()`` "would clear §5's floor and reach ``ALLOW`` with no user in
    the loop, and nothing in ADR-0016 detects a declaration that understates."
    """
    assert SEND_EMAIL.discloses == (DataTier.PERSONAL,)


def test_the_definition_declares_the_one_schema_dialect_that_is_read() -> None:
    """ADR-0145 §5: draft 2020-12, declared rather than left to the default."""
    assert SEND_EMAIL.parameters_schema["$schema"] == (
        "https://json-schema.org/draft/2020-12/schema"
    )
    assert SEND_EMAIL.parameters_schema["additionalProperties"] is False


def test_every_argument_the_schema_admits_is_covered_by_the_payload_declaration() -> None:
    """ADR-0148 §6: the description covers **every span the call transmits**.

    With ``additionalProperties: false`` the schema's properties are exactly the
    arguments a call can carry, so this join is what makes coverage a property of
    the declaration rather than of the arguments any particular call happens to
    bring.
    """
    properties = SEND_EMAIL.parameters_schema["properties"]
    assert isinstance(properties, Mapping)

    assert set(properties) == {argument.name for argument in SEND_EMAIL_PAYLOAD.arguments}


def test_every_destination_bearing_argument_is_one_the_schema_declares() -> None:
    """A declaration naming a field the schema does not admit selects nobody."""
    properties = SEND_EMAIL.parameters_schema["properties"]
    assert isinstance(properties, Mapping)

    assert {argument.name for argument in SEND_EMAIL_DESTINATIONS.arguments} <= set(properties)


def test_the_recipient_fields_are_the_destination_bearing_ones() -> None:
    """``bcc`` is a recipient, and omitting it would be a mis-declaration.

    ADR-0148 §2's third clause: an integration that "believed its operation selects
    nothing while an argument in fact names a recipient has mis-declared its
    destination-bearing arguments, which is a defect in the same class as a
    mis-declared ``discloses``."
    """
    assert [argument.name for argument in SEND_EMAIL_DESTINATIONS.arguments] == [
        "to",
        "cc",
        "bcc",
    ]


def test_the_recipient_fields_establish_a_tier_and_the_free_text_fields_do_not() -> None:
    """ADR-0146 §5's test applied field by field, which is where §5's round 4 bit.

    "a message body, a note, a subject line" carry "arbitrary text the user
    supplied … however well the implementation knows what that field is for", so
    they establish no tier; a recipient list passes the test and establishes
    ``PERSONAL``.
    """
    established = {
        argument.name: argument.establishes_tier for argument in SEND_EMAIL_PAYLOAD.arguments
    }

    assert established == {
        "to": DataTier.PERSONAL,
        "cc": DataTier.PERSONAL,
        "bcc": DataTier.PERSONAL,
        "subject": None,
        "body": None,
    }


def test_describing_a_send_yields_both_forms_and_one_canonical_member() -> None:
    """ADR-0148 §14's alias case end to end, through the tool's own declarations."""
    description = describe_send_email(
        {**_ARGUMENTS, "to": ("Bob@Example.com",), "cc": ("bob@example.com",)},
        provenance={SpanRef(argument="body"): DiscloserProvenance.USER_AUTHORED},
    )

    assert [(one.supplied, one.canonical) for one in description.destinations] == [
        ("Bob@Example.com", "Bob@example.com"),
        ("bob@example.com", "bob@example.com"),
    ]
    assert canonical_destination_set(description.destinations) == (
        "Bob@example.com",
        "bob@example.com",
    )


def test_describing_a_send_states_no_tier_for_the_body_the_user_wrote() -> None:
    """The description ADR-0146 §5 calls honest, produced by the tool that owes it."""
    description = describe_send_email(
        _ARGUMENTS, provenance={SpanRef(argument="body"): DiscloserProvenance.USER_AUTHORED}
    )

    body = next(span for span in description.spans if span.span.argument == "body")
    assert body.tier is None
    assert body.provenance is DiscloserProvenance.USER_AUTHORED
    assert body.characters == len("see you at one")


def test_describing_a_send_is_deterministic() -> None:
    """§6's determinism clause, at the surface a request builder would call."""
    assert describe_send_email(_ARGUMENTS, provenance={}) == describe_send_email(
        _ARGUMENTS, provenance={}
    )


def test_a_send_with_an_uncanonicalisable_recipient_is_refused_before_any_ruling() -> None:
    """ADR-0148 §1's third clause: no ruling is sought for a request like this."""
    with pytest.raises(DestinationSelectionError):
        describe_send_email({**_ARGUMENTS, "to": ("bob@[192.0.2.1]",)}, provenance={})


def test_the_definition_is_frozen() -> None:
    """ADR-0016 §1: a decision is recorded against the definition in force."""
    assert ToolDefinition.model_config["frozen"] is True

    with pytest.raises(ValidationError):
        SEND_EMAIL.risk_level = RiskLevel.LOW
