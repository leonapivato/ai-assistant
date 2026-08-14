"""The declaration reader on its own (ADR-0152 §3, §4).

The suite exercises every §3 and §4 refusal *through* ``bind``, which is where
they bite. What is here is what belongs to this module rather than to the
contract: which keys count as statically named, that the presence scan ADR-0152
§8's partition turns on sees a keyword wherever it sits, and the one conservative
call this reader makes — that both keyword names are **reserved**, so a property
named after one is refused rather than read as a name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.core.errors import EgressBindingError
from ai_assistant.core.types import DataTier, DestinationProtocol
from ai_assistant.tools.egress_declaration import (
    DESTINATION_KEYWORD,
    TIER_KEYWORD,
    mentions_a_keyword,
    read_declaration,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson

_ALL: frozenset[DestinationProtocol] = frozenset(DestinationProtocol)

_RECIPIENTS: Mapping[str, FrozenJson] = {
    "type": "array",
    "items": {"type": "string"},
    DESTINATION_KEYWORD: "smtp",
    TIER_KEYWORD: "personal",
}


def _schema(properties: Mapping[str, FrozenJson], **rest: FrozenJson) -> Mapping[str, FrozenJson]:
    """A draft 2020-12 object schema naming ``properties``."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": dict(properties),
        **rest,
    }


def test_the_named_keys_are_the_top_level_properties_in_schema_order() -> None:
    """ADR-0152 §6: static naming is a key of the top-level ``properties`` object.

    The order is the schema's, because a refusal names the declared arguments and a
    message whose order depended on a set's iteration would differ between runs.
    """
    declaration = read_declaration(
        _schema({"to": _RECIPIENTS, "subject": {"type": "string"}, "body": {"type": "string"}}),
        tool_id="send_email",
        canonicalises=_ALL,
    )

    assert declaration.named == ("to", "subject", "body")
    assert declaration.tool_id == "send_email"


def test_the_two_keywords_are_read_off_the_argument_they_sit_on() -> None:
    """ADR-0152 §3: two facts per argument and no others."""
    declaration = read_declaration(
        _schema({"to": _RECIPIENTS, "body": {"type": "string"}}),
        tool_id="send_email",
        canonicalises=_ALL,
    )

    destination = declaration.declaration_for("to")
    free_text = declaration.declaration_for("body")
    assert destination is not None
    assert destination.protocol is DestinationProtocol.SMTP
    assert destination.tier is DataTier.PERSONAL
    assert free_text is not None
    assert free_text.protocol is None
    assert free_text.tier is None
    assert declaration.declaration_for("never-declared") is None


def test_a_tool_with_no_properties_object_names_nothing() -> None:
    """ADR-0152 §6: ADR-0145 §9's "an absent schema declares no constraint", held to.

    Read as true, which is exactly why the seam adds a constraint of its own: a
    schema declaring nothing still admits keys, and those keys reach the recorded
    decision as locators.
    """
    assert read_declaration({}, tool_id="t", canonicalises=_ALL).named == ()
    assert read_declaration({"type": "object"}, tool_id="t", canonicalises=_ALL).named == ()
    assert (
        read_declaration({"properties": "not an object"}, tool_id="t", canonicalises=_ALL).named
        == ()
    )


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(_schema({"to": _RECIPIENTS}), id="on-a-top-level-property"),
        pytest.param(
            _schema({"to": {"type": "array", "items": dict(_RECIPIENTS)}}), id="inside-items"
        ),
        pytest.param(
            _schema({"to": {"type": "string"}}, **{"$defs": {"r": dict(_RECIPIENTS)}}),
            id="inside-defs",
        ),
        pytest.param(_schema({"to": {"anyOf": [dict(_RECIPIENTS)]}}), id="inside-an-applicator"),
    ],
)
def test_the_presence_scan_sees_a_keyword_wherever_it_sits(
    schema: Mapping[str, FrozenJson],
) -> None:
    """ADR-0152 §8: the partition turns on *mention*, not on well-formedness.

    A tool this seam holds no egress registration for is refused where it declares
    either keyword **anywhere** — returning ``None`` would silently discard a
    declaration its author wrote, whether or not that declaration would also have
    been refused for where it put the keyword.
    """
    assert mentions_a_keyword(schema)


def test_the_presence_scan_is_silent_on_a_schema_declaring_neither_keyword() -> None:
    """ADR-0152 §8: the other limb, so the scan is not vacuously true."""
    assert not mentions_a_keyword(_schema({"query": {"type": "string"}}))
    assert not mentions_a_keyword({})


@pytest.mark.parametrize("keyword", [DESTINATION_KEYWORD, TIER_KEYWORD])
def test_a_property_named_after_a_keyword_is_refused(keyword: str) -> None:
    """ADR-0152 §3, read conservatively: both names are reserved.

    Telling a keyword *position* from a property *name* position needs a model of
    draft 2020-12's applicator vocabulary, and an unknown applicator is exactly
    where a mis-declaration would hide — so the walk is structure-blind and the two
    names are reserved instead. The cost is a rename before anything is registered,
    which is ADR-0017 §4's "a boundary that has never transmitted can be held to
    the standard we would want everywhere".
    """
    with pytest.raises(EgressBindingError, match="reserved"):
        read_declaration(_schema({keyword: {"type": "string"}}), tool_id="t", canonicalises=_ALL)


def test_a_protocol_outside_the_seams_canonicaliser_set_is_refused() -> None:
    """ADR-0152 §3: refused, and not read as "no declaration" (ADR-0148 §1).

    Exercised by **narrowing** the set rather than by inventing a member: nothing
    supplies a second canonicaliser for a protocol the seam already canonicalises,
    which is the clause ADR-0148 §2 states.
    """
    with pytest.raises(EgressBindingError, match="no canonicaliser"):
        read_declaration(_schema({"to": _RECIPIENTS}), tool_id="t", canonicalises=frozenset())


def test_a_non_mapping_property_subschema_declares_nothing_rather_than_raising() -> None:
    """A schema whose property is not an object declares no keyword, so it binds none.

    ``ToolDefinition`` refuses an unreadable schema before this runs on the
    ordinary path, but this reader assumes nothing about its caller (ADR-0152
    §10) — and answering "no declaration" is the only reading available, since
    there is no subschema to read one off.
    """
    declaration = read_declaration({"properties": {"to": True}}, tool_id="t", canonicalises=_ALL)

    named = declaration.declaration_for("to")
    assert named is not None
    assert named.protocol is None
    assert named.tier is None
