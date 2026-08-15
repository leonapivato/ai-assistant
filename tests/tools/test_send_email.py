"""The declaration that is complete, and the callable that transmits through it.

Two properties this file exists to keep apart. The declaration is **honest** —
ADR-0016 §1's "declared, not inferred", with every safety field stating what a
send actually risks — and the integration is **configured**: present in the
registry exactly where a deployment named a connected account and an endpoint,
absent otherwise. The designating lane (ADR-0154) and the registering lane changed
the second; every case about the first below is untouched, which is what keeping
them apart bought.

The declaration is now the schema's, in ADR-0152 §3's two keywords, so the cases
below read it where the binding seam reads it — and one of them reads it *through*
``read_declaration``, because a schema that looks right to a reviewer and a schema
the reader accepts are two different claims.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import pytest
from egress_transport_harness import binding as _binding
from pydantic import ValidationError

from ai_assistant.core.errors import ToolError
from ai_assistant.core.types import (
    CostBasis,
    DataTier,
    DestinationProtocol,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolDefinition,
    parameter_violations,
)
from ai_assistant.testing import FakeMemoryStore
from ai_assistant.tools.builtin import build_default_registry
from ai_assistant.tools.egress_declaration import (
    DESTINATION_KEYWORD,
    TIER_KEYWORD,
    read_declaration,
)
from ai_assistant.tools.send_email import SEND_EMAIL, SEND_EMAIL_ID, SendEmail

if TYPE_CHECKING:
    from ai_assistant.core.types import EgressBinding, FrozenJson

_RECIPIENT_ARGUMENTS = ("to", "cc", "bcc")


class _RecordingTransport:
    """A :class:`~ai_assistant.tools.send_email.BoundTransport` that keeps what it got.

    It records the **objects**, not copies of them, because what the case checks is
    that the callable forwarded rather than rebuilt: an equal-but-distinct binding
    would pass an equality assertion and would still be a second payload nobody's
    digest covers (ADR-0148 §4).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[EgressBinding, Mapping[str, FrozenJson]]] = []

    async def transmit(self, binding: EgressBinding, parameters: Mapping[str, FrozenJson]) -> None:
        """Record the call instead of making it."""
        self.sent.append((binding, parameters))


class _RefusingTransport:
    """A transport that refuses, in the class its real refusals belong to."""

    async def transmit(
        self,
        binding: EgressBinding,
        parameters: Mapping[str, FrozenJson],
    ) -> None:
        """Refuse without transmitting.

        Raises:
            ToolError: Always.
        """
        msg = "the far end refused the envelope"
        raise ToolError(msg)


def _properties() -> Mapping[str, FrozenJson]:
    """The schema's top-level ``properties`` object, checked to be one."""
    properties = SEND_EMAIL.parameters_schema["properties"]
    assert isinstance(properties, Mapping)
    return properties


def _subschema(name: str) -> Mapping[str, FrozenJson]:
    """One top-level property's own subschema, checked to be one."""
    subschema = _properties()[name]
    assert isinstance(subschema, Mapping)
    return subschema


_ARGUMENTS = {
    "to": ("bob@example.com",),
    "subject": "lunch",
    "body": "see you at one",
}


async def test_an_unconfigured_deployment_registers_no_send_email() -> None:
    """No connected account, no tool (ADR-0148 §6, ADR-0029 §1).

    Registration is what makes a tool invocable — "invocable if and only if
    registered" — so a deployment that named no account gets no way to reach a
    callable that would transmit. Checked rather than trusted, because the factory
    is one argument away from including it.
    """
    registry = build_default_registry(memory=FakeMemoryStore())

    assert await registry.get(SEND_EMAIL_ID) is None
    assert SEND_EMAIL_ID not in {tool.id for tool in await registry.all_tools()}
    assert SEND_EMAIL.capability not in await registry.capabilities()


async def test_the_callable_hands_the_binding_and_the_arguments_on_unchanged() -> None:
    """It transmits what it was given, and derives nothing (ADR-0148 §4).

    The whole of what this callable does. ADR-0148 §4's third clause binds what is
    transmitted to what was authorised and says a later lane "cannot satisfy it by
    re-deriving the set at the seam", so the binding and the arguments reach the
    transport as the *same objects* — identity, not equality, because a copy made
    here would be a second payload nobody's digest covers.
    """
    transport = _RecordingTransport()
    binding = _binding()

    output = await SendEmail(transport).invoke_bound(
        _ARGUMENTS, idempotency_key=None, egress_binding=binding
    )

    assert output is None, "a receipt would be Tier 1 or would be nothing (ADR-0029 §3)"
    assert len(transport.sent) == 1
    sent_binding, sent_parameters = transport.sent[0]
    assert sent_binding is binding
    assert sent_parameters is _ARGUMENTS


async def test_a_transport_refusal_reaches_the_caller_rather_than_being_swallowed() -> None:
    """A refusal is the tool's answer, and the seam classifies it (ADR-0029 §3).

    ``SendEmail`` catches nothing: the transport's own refusals — a moved endpoint,
    a changed record, an indeterminate write — carry more than this callable could
    reconstruct, and converting one into a returned result here would be inventing
    the retryability ADR-0029 §3 defers to a later integration ADR.
    """
    transport = _RefusingTransport()

    with pytest.raises(ToolError, match="refused"):
        await SendEmail(transport).invoke_bound(
            _ARGUMENTS, idempotency_key=None, egress_binding=_binding()
        )


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


def test_every_recipient_argument_declares_both_keywords_and_no_other_does() -> None:
    """ADR-0152 §3: two keywords, on the immediate subschema of a top-level property.

    Asserted over the whole ``properties`` object rather than over the three
    recipient names, so an argument added later without a declaration fails here
    instead of reaching the seam as a silently undeclared span.

    ``subject`` and ``body`` carrying **neither** keyword is the statement, not an
    omission. ADR-0152 §3 puts ``x-egress-tier`` "exactly where the argument's
    field **establishes** that tier", and ADR-0146 §5 rules that a subject line and
    a body do not — they carry "arbitrary text the user supplied", so stating a
    tier for them would assert a fact nobody established.
    """
    declared = {
        name: {keyword for keyword in (DESTINATION_KEYWORD, TIER_KEYWORD) if keyword in subschema}
        for name, subschema in _properties().items()
        if isinstance(subschema, Mapping)
    }

    assert declared == {
        "to": {DESTINATION_KEYWORD, TIER_KEYWORD},
        "cc": {DESTINATION_KEYWORD, TIER_KEYWORD},
        "bcc": {DESTINATION_KEYWORD, TIER_KEYWORD},
        "subject": set(),
        "body": set(),
    }


def test_each_keyword_carries_its_enum_members_own_string_value() -> None:
    """ADR-0152 §3: the value is the member's own ``value``, and nothing else.

    A value naming no member of its enum is refused rather than read as "no
    declaration", so a near-miss here — ``"SMTP"``, ``"email"``, ``"Personal"`` —
    would make the tool unbindable rather than under-declared. Asserted against the
    enums rather than against string literals, so a member renamed in ``core``
    fails here rather than at the seam.
    """
    for name in _RECIPIENT_ARGUMENTS:
        assert _subschema(name)[DESTINATION_KEYWORD] == DestinationProtocol.SMTP.value
        assert _subschema(name)[TIER_KEYWORD] == DataTier.PERSONAL.value


def test_every_recipient_argument_is_declared_flat() -> None:
    """ADR-0152 §4: a string, or an array whose ``items`` is a string, and no other.

    What the constraint buys is structural rather than stylistic: a supplied form
    is never extracted from inside a structured value, so ADR-0150 §4's
    supplied-form invariant is total. A recipient argument declared any other way
    is refused when the declaration is read, before any call is made — so this is
    the shape that keeps the tool bindable at all.
    """
    for name in _RECIPIENT_ARGUMENTS:
        assert _subschema(name)["type"] == "array"
        assert _subschema(name)["items"] == {"type": "string"}


def test_the_required_arguments_bound_is_not_shared_with_the_optional_two() -> None:
    """``to``'s ``minItems`` is ``to``'s, and a shared literal would leak it.

    Asserted over the values rather than over object identity, because the values
    are what a call is evaluated against: ``core`` freezes what a
    ``ToolDefinition`` holds, so the aliasing hazard lives in the literal the
    module hands it, and its only observable effect is a ``minItems`` stated for
    the required argument silently applying to the optional two — which would
    refuse a call that omits ``cc``.
    """
    assert _subschema("to") == {**_subschema("cc"), "minItems": 1}
    assert "minItems" not in _subschema("cc")
    assert "minItems" not in _subschema("bcc")


def test_the_declaration_the_seam_reads_is_the_one_this_tool_intends() -> None:
    """The join between what the tool declares and what ADR-0152 §3's reader makes of it.

    Read through ``read_declaration`` rather than by inspecting the schema, because
    the schema passing an eye test says nothing about whether the reader accepts
    it: a keyword one level too deep, a value naming no enum member, or a
    destination-bearing argument stating no tier are each refusals rather than
    quiet omissions, and this is what pins that none of them is present.
    """
    declaration = read_declaration(
        SEND_EMAIL.parameters_schema,
        tool_id=SEND_EMAIL.id,
        canonicalises=frozenset(DestinationProtocol),
    )

    assert declaration.named == ("to", "cc", "bcc", "subject", "body")
    assert {
        name: (argument.protocol, argument.tier) for name, argument in declaration.arguments.items()
    } == {
        "to": (DestinationProtocol.SMTP, DataTier.PERSONAL),
        "cc": (DestinationProtocol.SMTP, DataTier.PERSONAL),
        "bcc": (DestinationProtocol.SMTP, DataTier.PERSONAL),
        "subject": (None, None),
        "body": (None, None),
    }


def test_the_keywords_leave_the_schema_validating_identically() -> None:
    """ADR-0152 §3: an unknown keyword is an annotation, so validation is unchanged.

    Draft 2020-12 ignores a keyword it does not know, which is what lets the
    declaration ride in ``parameters_schema`` without touching ADR-0145 §5's
    one-dialect rule. Demonstrated against the repository's own evaluator rather
    than against the specification, over an accepted call and a rejected one — a
    schema that accepted everything would pass the first limb alone.
    """
    stripped: Mapping[str, FrozenJson] = {
        **SEND_EMAIL.parameters_schema,
        "properties": {
            name: (
                {
                    key: value
                    for key, value in subschema.items()
                    if key not in (DESTINATION_KEYWORD, TIER_KEYWORD)
                }
                if isinstance(subschema, Mapping)
                else subschema
            )
            for name, subschema in _properties().items()
        },
    }
    accepted: Mapping[str, FrozenJson] = {
        "to": ("bob@example.com",),
        "subject": "lunch",
        "body": "one o'clock",
    }
    rejected: Mapping[str, FrozenJson] = {
        "to": (),
        "subject": "lunch",
        "body": "one o'clock",
        "attachment": "x",
    }

    for parameters in (accepted, rejected):
        assert parameter_violations(SEND_EMAIL.parameters_schema, parameters) == (
            parameter_violations(stripped, parameters)
        )
    assert parameter_violations(SEND_EMAIL.parameters_schema, accepted) == ()
    assert parameter_violations(SEND_EMAIL.parameters_schema, rejected) != ()


def test_the_definition_is_frozen() -> None:
    """ADR-0016 §1: a decision is recorded against the definition in force."""
    assert ToolDefinition.model_config["frozen"] is True

    with pytest.raises(ValidationError):
        SEND_EMAIL.risk_level = RiskLevel.LOW
