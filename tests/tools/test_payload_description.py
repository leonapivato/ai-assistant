"""The payload description: deterministic, complete, and honest about tiers.

Three of the cases ADR-0148 §14 binds the implementing lane to live here — the
**carried-provenance** pair, the **omitted-span** case in its mixed form, and the
**alias** case's descriptive half — alongside the determinism §6 requires and the
no-tier rule ADR-0146 §5 states.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.types import DataTier
from ai_assistant.tools.destination_arguments import (
    DestinationArgument,
    DestinationDeclaration,
)
from ai_assistant.tools.destinations import DestinationProtocol
from ai_assistant.tools.payload_description import (
    DiscloserProvenance,
    EgressToolDeclaration,
    PayloadArgument,
    PayloadDeclaration,
    PayloadDescriptionError,
    SpanRef,
    UndescribedSpanError,
    describe_payload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.payload_description import PayloadDescription

_DESTINATIONS = DestinationDeclaration(
    tool_id="send_email",
    arguments=(
        DestinationArgument(
            name="to", protocol=DestinationProtocol.SMTP, multiple=True, required=True
        ),
    ),
)

_PAYLOAD = PayloadDeclaration(
    tool_id="send_email",
    arguments=(
        PayloadArgument(name="to", establishes_tier=DataTier.PERSONAL, multiple=True),
        PayloadArgument(name="subject", establishes_tier=None),
        PayloadArgument(name="body", establishes_tier=None),
    ),
)

_DECLARATION = EgressToolDeclaration(
    tool_id="send_email", payload=_PAYLOAD, recipients=_DESTINATIONS
)

_ARGUMENTS: Mapping[str, FrozenJson] = {
    "to": ("bob@example.com",),
    "subject": "lunch",
    "body": "see you at one",
}


def _describe(
    parameters: Mapping[str, FrozenJson],
    provenance: Mapping[SpanRef, DiscloserProvenance] | None = None,
) -> PayloadDescription:
    return describe_payload(_DECLARATION, parameters, provenance=provenance or {})


def test_two_derivations_of_one_request_agree() -> None:
    """ADR-0148 §6's determinism clause, asserted as the clause states it."""
    assert _describe(dict(_ARGUMENTS)) == _describe(dict(_ARGUMENTS))


def test_the_description_is_a_function_of_the_arguments_not_of_their_order() -> None:
    """Declaration order fixes the spans, so a mapping's insertion order cannot."""
    reordered = {"body": "see you at one", "to": ("bob@example.com",), "subject": "lunch"}

    assert _describe(dict(_ARGUMENTS)) == _describe(reordered)


def test_a_span_the_user_composed_states_provenance_extent_and_no_tier() -> None:
    """ADR-0146 §5's fourth clause, and the description it names as honest.

    "A payload description or an audit record states **no tier** for a
    user-authored free-text span. It states the span's provenance and its extent"
    — which is §5's "the user's own words, verbatim, N characters, to
    <destination>".
    """
    description = _describe(
        dict(_ARGUMENTS),
        {SpanRef(argument="body"): DiscloserProvenance.USER_AUTHORED},
    )

    body = next(span for span in description.spans if span.span.argument == "body")
    assert body.provenance is DiscloserProvenance.USER_AUTHORED
    assert body.characters == len("see you at one")
    assert body.tier is None


def test_a_field_that_establishes_a_tier_states_it_whatever_the_provenance() -> None:
    """ADR-0146 §5's second clause: only *free text* is untiered.

    A recipient address passes §5's test — "every value it can hold carries the
    same tier by what the field is for" — so the user having typed it moves
    nothing, which is ADR-0146 §1's first clause on the other axis.
    """
    description = _describe(
        dict(_ARGUMENTS),
        {SpanRef(argument="to", index=0): DiscloserProvenance.USER_AUTHORED},
    )

    recipient = next(span for span in description.spans if span.span.argument == "to")
    assert recipient.provenance is DiscloserProvenance.USER_AUTHORED
    assert recipient.tier is DataTier.PERSONAL


def test_a_span_with_no_recorded_origin_is_system_selected() -> None:
    """ADR-0146 §2's fail-closed default, "the clause most likely to be dropped"."""
    description = _describe(dict(_ARGUMENTS))

    assert all(span.provenance is DiscloserProvenance.SYSTEM_SELECTED for span in description.spans)


def test_two_requests_differing_only_in_carried_provenance_describe_differently() -> None:
    """ADR-0148 §14's carried-provenance pair, in the form the clause fixes.

    "two requests with byte-identical arguments and the same registry definition,
    differing only in the provenance the request carries for one span, produce
    **different** descriptions, each stating that request's own carried
    provenance." An implementation that read the span's value, field or shape
    would derive one description for both.
    """
    authored = _describe(
        dict(_ARGUMENTS), {SpanRef(argument="body"): DiscloserProvenance.USER_AUTHORED}
    )
    selected = _describe(
        dict(_ARGUMENTS), {SpanRef(argument="body"): DiscloserProvenance.SYSTEM_SELECTED}
    )

    assert authored != selected
    assert [span.provenance for span in authored.spans] != [
        span.provenance for span in selected.spans
    ]


def test_provenance_is_per_span_so_one_argument_can_carry_both_kinds() -> None:
    """ADR-0146 §1: provenance is "a property of a span, not of a message or a call".

    A recipient list is the mixed case in miniature — one address the user typed
    beside one the system chose — and an implementation keyed on the argument
    could not state it.
    """
    parameters = dict(_ARGUMENTS) | {"to": ("bob@example.com", "carol@example.com")}
    description = _describe(
        parameters, {SpanRef(argument="to", index=0): DiscloserProvenance.USER_AUTHORED}
    )

    recipients = [span for span in description.spans if span.span.argument == "to"]
    assert [span.provenance for span in recipients] == [
        DiscloserProvenance.USER_AUTHORED,
        DiscloserProvenance.SYSTEM_SELECTED,
    ]


def test_a_mixed_payload_with_two_undescribed_span_kinds_is_refused() -> None:
    """ADR-0148 §14's omitted-span case, which requires both kinds in one payload.

    "a payload carrying a described benign span, an undescribed **selected
    record**, *and* an undescribed **user-authored free-text argument** is
    refused". A test carrying one omission alone does not satisfy the clause, so
    both are here, and the refusal is asserted to be deterministic.
    """
    parameters = dict(_ARGUMENTS) | {
        "attached_record": "memory record 7",
        "postscript": "and bring the tickets",
    }

    with pytest.raises(UndescribedSpanError) as first:
        _describe(parameters)
    with pytest.raises(UndescribedSpanError) as again:
        _describe(parameters)

    assert "2 argument(s)" in str(first.value)
    assert str(first.value) == str(again.value)


def test_the_omitted_span_refusal_names_no_undeclared_key() -> None:
    """Adversarial round 6: an argument *name* is caller-supplied here too.

    `tools/builtin.py`'s `_reject_unknown` names the unexpected keys it refuses,
    and its reason holds where it runs — inside a callable, where ADR-0145 has
    already refused anything outside the schema's ``additionalProperties: false``.
    This derivation runs *before* the request exists (ADR-0148 §1), so a key here
    is a string whatever produced the arguments could write as freely as a value.
    The refusal states a count and the names the declaration itself holds.
    """
    needle = "the secret is swordfish"

    with pytest.raises(UndescribedSpanError) as raised:
        _describe(dict(_ARGUMENTS) | {needle: "x"})

    assert needle not in str(raised.value)
    assert "1 argument(s)" in str(raised.value)


def test_a_description_that_happens_to_be_complete_is_not_what_is_asserted() -> None:
    """The neighbouring positive case, so the refusal above is not vacuous."""
    description = _describe(dict(_ARGUMENTS))

    assert {span.span.argument for span in description.spans} == {"to", "subject", "body"}


def test_provenance_carried_for_a_span_the_call_does_not_transmit_is_refused() -> None:
    """A caller and this derivation disagreeing about the payload is the defect.

    Dropping the extra entry silently would hide exactly the mismatch that
    produces a description of a different call.
    """
    with pytest.raises(PayloadDescriptionError, match="does not transmit"):
        _describe(
            dict(_ARGUMENTS),
            {SpanRef(argument="to", index=4): DiscloserProvenance.USER_AUTHORED},
        )


def test_a_non_text_argument_has_no_described_extent() -> None:
    """Stating a digit count would be describing a span by guessing its encoding."""
    numeric = EgressToolDeclaration(
        tool_id="send_email",
        payload=PayloadDeclaration(
            tool_id="send_email",
            arguments=(
                PayloadArgument(name="to", establishes_tier=DataTier.PERSONAL, multiple=True),
                PayloadArgument(name="priority", establishes_tier=None),
            ),
        ),
        recipients=_DESTINATIONS,
    )

    with pytest.raises(PayloadDescriptionError, match="not text"):
        describe_payload(numeric, {"to": ("bob@example.com",), "priority": 3}, provenance={})


def test_a_destination_declaration_for_another_tool_is_refused() -> None:
    """Adversarial rounds 2 and 3: two halves that can be paired can be mis-paired.

    A destination declaration belonging to some other tool, naming an argument
    this tool happens to have, would have the description record the message body
    as the recipient and omit `to` — a description of a different call, published
    under this tool's name. ADR-0148 §6 makes the description a function of the
    bound tool's definition, so a declaration that is not that tool's is not an
    input to it.

    Refused when the declaration is **built** rather than when a call is
    described, which is what round 3 asked for: the pairing is checked once, so a
    tool whose halves disagree does not load.
    """
    other = DestinationDeclaration(
        tool_id="post_message",
        arguments=(
            DestinationArgument(
                name="body", protocol=DestinationProtocol.SMTP, multiple=False, required=True
            ),
        ),
    )

    with pytest.raises(PayloadDescriptionError, match="not this tool's"):
        EgressToolDeclaration(tool_id="send_email", payload=_PAYLOAD, recipients=other)


def test_a_recipient_field_the_payload_declaration_omits_is_refused() -> None:
    """The description would then cover every span but the recipients (ADR-0148 §6).

    Refused on the declarations rather than on one call's arguments, because a
    payload declaration that does not name a destination-bearing argument is wrong
    for every call that tool could ever make.
    """
    without_recipients = PayloadDeclaration(
        tool_id="send_email",
        arguments=(PayloadArgument(name="body", establishes_tier=None),),
    )

    with pytest.raises(PayloadDescriptionError, match="bears destinations"):
        EgressToolDeclaration(
            tool_id="send_email", payload=without_recipients, recipients=_DESTINATIONS
        )


def test_the_destinations_are_derived_rather_than_accepted_from_the_caller() -> None:
    """Adversarial round 1: an accepted destination tuple is bound by nothing.

    A description whose recipients came from a separate argument is not "a
    function of the request and the registry's definition alone" (ADR-0148 §6), so
    the approver, the seam and a later auditor cannot re-derive and compare it —
    and a caller could describe one set of recipients while the arguments named
    another. There is no parameter to pass one through, and this asserts the
    recipients follow the arguments.
    """
    description = _describe({**_ARGUMENTS, "to": ("carol@example.com",)})

    assert [one.canonical for one in description.destinations] == ["carol@example.com"]


def test_the_description_carries_both_forms_of_every_destination() -> None:
    """ADR-0148 §2's fourth clause: both forms "appear in the payload description"."""
    parameters = dict(_ARGUMENTS) | {"to": ("Bob@Example.com",)}
    description = _describe(parameters)

    assert [(one.supplied, one.canonical) for one in description.destinations] == [
        ("Bob@Example.com", "Bob@example.com")
    ]


def test_the_description_holds_no_content() -> None:
    """§6's reason for storing it at all: it states extent, not the arguments.

    "A description is not the arguments: it states extent, provenance, tiers and
    destinations rather than content, which is exactly the artifact that is safe
    to keep where the content is not."
    """
    parameters = dict(_ARGUMENTS) | {"body": "the secret is swordfish"}
    description = _describe(parameters)

    assert "swordfish" not in repr(description)


def test_spans_are_ordered_by_declaration_then_by_position() -> None:
    """An order that varied would make two derivations of one request unequal."""
    parameters = dict(_ARGUMENTS) | {"to": ("bob@example.com", "carol@example.com")}
    description = _describe(parameters)

    assert [(span.span.argument, span.span.index) for span in description.spans] == [
        ("to", 0),
        ("to", 1),
        ("subject", None),
        ("body", None),
    ]


def test_the_bundled_declaration_is_checked_once_and_then_trusted() -> None:
    """Where the regress stops, asserted as a property rather than left implied.

    A caller can still write a declaration that misdescribes its own tool, and
    nothing in `tools/` detects it: ADR-0148 §2 calls that "a defect in the same
    class as a mis-declared ``discloses``", §8 records that "nothing in ADR-0016
    detects a declaration that understates", and ADR-0021 §1 rules the general
    case — "no producer can prevent it". What is prevented is two honest halves
    being combined wrongly, and a declaration that survived construction is one
    whose halves agree.
    """
    declaration = EgressToolDeclaration(
        tool_id="send_email", payload=_PAYLOAD, recipients=_DESTINATIONS
    )

    assert declaration.payload.tool_id == declaration.tool_id
    assert declaration.recipients.tool_id == declaration.tool_id
    assert {argument.name for argument in declaration.recipients.arguments} <= {
        argument.name for argument in declaration.payload.arguments
    }


def test_a_carried_provenance_outside_the_two_states_is_refused() -> None:
    """Adversarial round 4: the annotation is not the check.

    ADR-0146 §2's fail-closed rule covers the span with **no** recorded origin. A
    value that is not one of §1's two states is a different thing — a caller whose
    wiring is wrong — and letting it through would put a third provenance in a
    description that no clause admits, which is the permissive default arriving by
    another door.
    """
    forged: dict[SpanRef, DiscloserProvenance] = {
        SpanRef(argument="body"): "user_authored"  # type: ignore[dict-item]
    }

    with pytest.raises(PayloadDescriptionError, match="two states"):
        _describe(dict(_ARGUMENTS), forged)


def test_a_carried_provenance_keyed_by_something_other_than_a_span_is_refused() -> None:
    """The other half of the same mapping, checked for the same reason."""
    forged: dict[SpanRef, DiscloserProvenance] = {
        "body": DiscloserProvenance.USER_AUTHORED  # type: ignore[dict-item]
    }

    with pytest.raises(PayloadDescriptionError, match="not a span"):
        _describe(dict(_ARGUMENTS), forged)


def test_a_provenance_refusal_never_quotes_what_it_refused() -> None:
    """A forged entry can hold anything, content included."""
    needle = "the secret is swordfish"
    forged: dict[SpanRef, DiscloserProvenance] = {
        SpanRef(argument="body"): needle  # type: ignore[dict-item]
    }

    with pytest.raises(PayloadDescriptionError) as raised:
        _describe(dict(_ARGUMENTS), forged)

    assert needle not in str(raised.value)


def test_a_span_reference_naming_an_undeclared_argument_is_refused_unquoted() -> None:
    """Adversarial round 5: the *key* is caller-supplied too.

    ``SpanRef.argument`` is a plain string a caller writes, so a refusal that
    named it would put arbitrary text into a message bound for a log — the leak
    `core/logging.py` names and `tools/invocation.py` declines to make with
    ``str(exc)``. A name the declaration holds was written by the tool's author
    and is safe to quote; anything else gets a fixed diagnostic.
    """
    needle = "the secret is swordfish"
    forged: dict[SpanRef, DiscloserProvenance] = {
        SpanRef(argument=needle): DiscloserProvenance.USER_AUTHORED
    }

    with pytest.raises(PayloadDescriptionError) as raised:
        _describe(dict(_ARGUMENTS), forged)

    assert needle not in str(raised.value)
    assert "does not declare" in str(raised.value)


def test_a_span_reference_whose_position_is_not_an_index_is_refused() -> None:
    """The third caller-supplied field of a forged key, checked with the other two."""
    forged: dict[SpanRef, DiscloserProvenance] = {
        SpanRef(argument="to", index="0"): DiscloserProvenance.USER_AUTHORED  # type: ignore[arg-type]
    }

    with pytest.raises(PayloadDescriptionError, match="no usable position"):
        _describe(dict(_ARGUMENTS), forged)


def test_a_payload_declaration_naming_no_argument_is_refused() -> None:
    """A declaration that covers nothing would make every span undescribed."""
    with pytest.raises(PayloadDescriptionError, match="at least one"):
        PayloadDeclaration(tool_id="send_email", arguments=())


def test_a_payload_declaration_naming_one_argument_twice_is_refused() -> None:
    """Two entries could establish two tiers for one field."""
    body = PayloadArgument(name="body", establishes_tier=None)

    with pytest.raises(PayloadDescriptionError, match="each argument once"):
        PayloadDeclaration(tool_id="send_email", arguments=(body, body))
