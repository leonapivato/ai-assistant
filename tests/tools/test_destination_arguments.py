"""Reading the destination set out of named fields, and refusing before the ruling.

ADR-0148 §1's second clause fixes what a request may carry when a policy rules on
it, and its third fixes what happens when it cannot be completed: "refused
**before the ruling**, and no ruling is sought for it". Everything here is one or
the other — a set read mechanically out of declared fields, or a refusal.
"""

from __future__ import annotations

import pytest

from ai_assistant.tools.destination_arguments import (
    DestinationArgument,
    DestinationDeclaration,
    DestinationSelectionError,
    select_destinations,
)
from ai_assistant.tools.destinations import (
    DestinationCanonicalisationError,
    DestinationProtocol,
    canonical_destination_set,
)

_TO = DestinationArgument(
    name="to", protocol=DestinationProtocol.SMTP, multiple=True, required=True
)
_CC = DestinationArgument(
    name="cc", protocol=DestinationProtocol.SMTP, multiple=True, required=False
)
_SENDER = DestinationArgument(
    name="sender", protocol=DestinationProtocol.SMTP, multiple=False, required=True
)

_DECLARATION = DestinationDeclaration(tool_id="send_email", arguments=(_TO, _CC))


def test_recipients_are_read_from_the_declared_fields_in_declaration_order() -> None:
    """The declaration is the authority, not the shape of the values (ADR-0016 §1)."""
    selected = select_destinations(
        _DECLARATION, {"to": ("bob@example.com",), "cc": ("carol@example.com",)}
    )

    assert [destination.supplied for destination in selected] == [
        "bob@example.com",
        "carol@example.com",
    ]


def test_an_address_inside_a_body_selects_nobody() -> None:
    """Which arguments bear destinations is declared, never inferred from values.

    ADR-0016 §1 rejects "deriving risk … from whether the tool's name starts with
    ``send_``" for the reason that applies here: an inference "fails silently for
    every tool nobody thought about". An address in prose is prose.
    """
    selected = select_destinations(_DECLARATION, {"to": ("bob@example.com",)})

    assert len(selected) == 1


def test_two_spellings_of_one_recipient_are_two_occurrences_and_one_member() -> None:
    """ADR-0148 §14's alias case, at the level that produces the set.

    "two calls whose destination-bearing arguments were supplied in different
    forms that canonicalise to one recipient produce descriptions and audit
    records each stating its **own** supplied form beside the shared canonical
    one" — and within one call, both supplied forms have to survive as well.
    """
    selected = select_destinations(
        _DECLARATION, {"to": ("Alice@Example.com",), "cc": ("Alice@example.com",)}
    )

    assert [destination.supplied for destination in selected] == [
        "Alice@Example.com",
        "Alice@example.com",
    ]
    assert canonical_destination_set(selected) == ("Alice@example.com",)


def test_an_optional_argument_that_is_absent_selects_nobody() -> None:
    """No default is supplied and nothing is expanded (ADR-0148 §1)."""
    assert len(select_destinations(_DECLARATION, {"to": ("bob@example.com",)})) == 1


def test_a_required_argument_that_is_absent_is_refused() -> None:
    """Refused where the request is built, not answered with an empty set."""
    with pytest.raises(DestinationSelectionError, match="required argument 'to' is absent"):
        select_destinations(_DECLARATION, {"cc": ("carol@example.com",)})


def test_a_required_argument_selecting_nobody_is_refused() -> None:
    """An empty ``to`` is a call with no recipient, not a call with an empty set."""
    with pytest.raises(DestinationSelectionError, match="selects no recipient"):
        select_destinations(_DECLARATION, {"to": ()})


def test_a_call_selecting_no_recipient_at_all_is_refused() -> None:
    """Whatever route it arrives by, a call with no destination cannot be completed."""
    optional_only = DestinationDeclaration(tool_id="send_email", arguments=(_CC,))

    with pytest.raises(DestinationSelectionError, match="selects no recipient"):
        select_destinations(optional_only, {})


def test_a_string_where_a_list_is_declared_is_refused_rather_than_iterated() -> None:
    """A ``str`` is a ``Sequence``; iterating one makes a recipient per character."""
    with pytest.raises(DestinationSelectionError, match="declared as a list"):
        select_destinations(_DECLARATION, {"to": "bob@example.com"})


def test_a_list_where_a_single_destination_is_declared_is_refused() -> None:
    """The declared shape is the shape, so a mismatch is a refusal not a guess."""
    single = DestinationDeclaration(tool_id="resolve", arguments=(_SENDER,))

    with pytest.raises(DestinationSelectionError, match="entry 0 is not a string"):
        select_destinations(single, {"sender": ("bob@example.com",)})


def test_a_non_string_entry_is_refused() -> None:
    """A number is not a destination, and coercing it would be inventing one."""
    with pytest.raises(DestinationSelectionError, match="entry 1 is not a string"):
        select_destinations(_DECLARATION, {"to": ("bob@example.com", 7)})


def test_an_uncanonicalisable_form_is_refused_and_names_where_it_sat() -> None:
    """The refusal chains the canonicalisation failure and adds the position.

    A caller catching either type refuses the whole request, which is ADR-0148
    §1's third clause; the position is what makes the refusal actionable without
    quoting a Tier 1 value.
    """
    with pytest.raises(DestinationSelectionError) as raised:
        select_destinations(
            _DECLARATION, {"to": ("bob@example.com",), "cc": ("carol@[192.0.2.1]",)}
        )

    assert "argument 'cc' entry 0" in str(raised.value)
    assert isinstance(raised.value.__cause__, DestinationCanonicalisationError)


def test_a_refusal_never_quotes_the_address_it_refused() -> None:
    """The whole chain keeps the Tier 1 value out of the message."""
    needle = "needle-local-part"

    with pytest.raises(DestinationSelectionError) as raised:
        select_destinations(_DECLARATION, {"to": (f'"{needle}"@example.com',)})

    assert needle not in str(raised.value)


def test_a_declaration_naming_no_argument_is_refused() -> None:
    """ADR-0148 §2's third clause is real and this type cannot express it.

    A call whose arguments select no onward recipient is authorised against the
    connected account alone — which needs a connection record whose owner
    ADR-0125 §12 leaves undecided, so the empty declaration is refused rather
    than silently meaning "selects nobody".
    """
    with pytest.raises(DestinationSelectionError, match="at least one"):
        DestinationDeclaration(tool_id="send_email", arguments=())


def test_a_declaration_naming_one_argument_twice_is_refused() -> None:
    """Two entries for one field would describe one span twice or disagree."""
    with pytest.raises(DestinationSelectionError, match="each argument once"):
        DestinationDeclaration(tool_id="send_email", arguments=(_TO, _TO))


def test_a_declaration_naming_a_protocol_this_seam_cannot_canonicalise_is_refused() -> None:
    """Adversarial round 7: it reached the canonicaliser and raised the wrong error.

    A protocol with no entry in the seam's mapping has no canonical form to
    assert, so the declaration cannot be completed against — ADR-0148 §2's first
    clause and §1's third. Caught at construction, so a malformed declaration does
    not load rather than failing at the first call made against it.
    """
    malformed = DestinationArgument(
        name="to",
        protocol=None,  # type: ignore[arg-type]
        multiple=True,
        required=True,
    )

    with pytest.raises(DestinationSelectionError, match="does not canonicalise"):
        DestinationDeclaration(tool_id="send_email", arguments=(malformed,))


def test_a_declaration_holding_a_malformed_member_refuses_before_it_is_used() -> None:
    """Adversarial round 8: the checks ran after the names were collected.

    An unhashable name reached ``set`` and a member that was not an argument at
    all reached an attribute access, so a declaration this type documents as
    refusing raised a bare ``TypeError`` or ``AttributeError`` instead. "A guard
    whose own failure modes bypass the failure path it specifies is enforcing
    nothing" — ADR-0026 §2's rule for ``checked_clock``.
    """
    with pytest.raises(DestinationSelectionError, match="destination-bearing arguments"):
        DestinationDeclaration(tool_id="send_email", arguments=(None,))  # type: ignore[arg-type]

    unhashable = DestinationArgument(
        name=[],  # type: ignore[arg-type]
        protocol=DestinationProtocol.SMTP,
        multiple=True,
        required=True,
    )
    with pytest.raises(DestinationSelectionError, match="has no name"):
        DestinationDeclaration(tool_id="send_email", arguments=(unhashable,))


def test_a_declaration_built_from_a_list_cannot_be_edited_afterwards() -> None:
    """Adversarial round 11: frozen protects the field, not what the field points at.

    A ``list`` passed where the annotation says ``tuple`` leaves the caller
    holding the container this type validated — replace an entry after
    construction and a declaration checked for one recipient set is used for
    another, with no invariant re-run. The arguments are snapshotted into a tuple
    before anything is checked.
    """
    mutable = [_TO]
    declaration = DestinationDeclaration(tool_id="send_email", arguments=mutable)  # type: ignore[arg-type]

    mutable[0] = DestinationArgument(
        name="body", protocol=DestinationProtocol.SMTP, multiple=False, required=True
    )

    assert declaration.arguments == (_TO,)
    assert [one.supplied for one in select_destinations(declaration, {"to": ("a@b.com",)})] == [
        "a@b.com"
    ]


def test_a_declaration_whose_arguments_are_not_a_sequence_is_refused() -> None:
    """The snapshot has to be takeable before it can be checked."""
    with pytest.raises(DestinationSelectionError, match="a sequence of arguments"):
        DestinationDeclaration(tool_id="send_email", arguments=None)  # type: ignore[arg-type]


def test_a_declaration_naming_no_tool_is_refused_without_rendering_it() -> None:
    """Every other refusal opens with the tool id, so it is checked before it is."""
    needle = "the secret is swordfish"

    with pytest.raises(DestinationSelectionError) as raised:
        DestinationDeclaration(tool_id=needle.encode(), arguments=(_TO,))  # type: ignore[arg-type]

    assert needle not in str(raised.value)


def test_a_declaration_naming_a_nameless_argument_is_refused() -> None:
    """An argument with no name selects from no field and describes no span."""
    nameless = DestinationArgument(
        name="", protocol=DestinationProtocol.SMTP, multiple=True, required=True
    )

    with pytest.raises(DestinationSelectionError, match="has no name"):
        DestinationDeclaration(tool_id="send_email", arguments=(nameless,))
