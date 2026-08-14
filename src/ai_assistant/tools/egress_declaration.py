"""The two keywords a tool declares egress with, read out of its own schema.

ADR-0152 §3 and §4 in code. The declaration vocabulary the binding seam reads is
**two keywords and no others**, riding in the tool's ``parameters_schema`` rather
than on a new :class:`~ai_assistant.core.types.ToolDefinition` field:

- ``x-egress-destination``, whose value is a
  :class:`~ai_assistant.core.types.DestinationProtocol` member's own string value,
  present exactly on a **destination-bearing** argument (ADR-0148 §2); and
- ``x-egress-tier``, whose value is a
  :class:`~ai_assistant.core.types.DataTier` member's own string value, present
  exactly where the argument's field **establishes** that tier (ADR-0146 §5).

**Two rather than the producer's four is a result rather than a simplification.**
PR #1120's producer carried ``protocol``, ``multiple`` and ``required`` per
recipient argument across one declaration and ``establishes_tier`` and
``multiple`` per transmitted one across another. ADR-0150 §4 has since removed
three of the five: the decomposition is the *value's*, the coverage is total over
the arguments, and requiredness is JSON Schema's own ``required``. What is left is
exactly the two facts the schema cannot state, and neither is derivable from
anything — ADR-0016 §1's "declared, not inferred" holding at the two places it
still bites. :mod:`ai_assistant.tools.send_email` is that producer migrated onto
the result, and carries no declaration outside its own schema.

**Read only on the immediate subschema of a top-level property, and refused
anywhere else** (ADR-0152 §3). A keyword nested inside ``items``, inside a
subschema of a subschema, inside ``additionalProperties``, ``patternProperties``,
``propertyNames``, ``$defs``, or inside any applicator would be declaring
something about a value *inside* a span, which the binding surface has no field to
carry and ADR-0150 §4's depth rule forbids describing. Ignoring it would let an
author believe they had declared a recipient argument while the seam described a
body span, which is the mis-declaration ADR-0148 §2's third clause names arriving
through the mechanism meant to prevent it.

**The check is a deep walk that knows nothing about the dialect, and that is
deliberate.** Distinguishing a keyword *position* from a property *name* position
would need a model of JSON Schema draft 2020-12's applicator vocabulary, and an
unknown applicator is exactly where a mis-declaration would hide. So the walk
refuses either name as a key of **any** mapping in the schema other than a
permitted top-level property subschema, and the two names are correspondingly
**reserved**: no property may be named either of them, at any depth. That is the
conservative direction ADR-0148 §2 and ADR-0152 §3 both take, and it costs a tool
author a rename before anything is registered.

**Nothing here reads a value, a clock, a store or a network.** It reads one
frozen JSON document and answers questions about it, so two reads of one schema
agree — which is half of what ADR-0148 §6's determinism clause needs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import EgressBindingError
from ai_assistant.core.types import DataTier, DestinationProtocol

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

    from ai_assistant.core.types import FrozenJson

#: The keyword marking a destination-bearing argument (ADR-0152 §3). ``x-``
#: prefixed rather than bare: ``$``-prefixed names are reserved to the
#: specification, and an unprefixed ``egress`` could collide with a future
#: keyword, at which point a schema would mean two things at once.
DESTINATION_KEYWORD: Final = "x-egress-destination"

#: The keyword stating the tier an argument's field establishes (ADR-0152 §3,
#: ADR-0146 §5).
TIER_KEYWORD: Final = "x-egress-tier"

#: Both, for the presence scan ADR-0152 §8's partition turns on.
EGRESS_KEYWORDS: Final = (DESTINATION_KEYWORD, TIER_KEYWORD)


@dataclass(frozen=True, slots=True)
class ArgumentDeclaration:
    """What one top-level argument declares to the binding seam.

    Attributes:
        name: The argument's name, as the schema's top-level ``properties``
            object spells it. It is the tool author's text, which is what ADR-0152
            §11 permits a refusal to name.
        protocol: The protocol its values are canonicalised under, where the
            argument is destination-bearing, and ``None`` otherwise.
        tier: The tier its field establishes (ADR-0146 §5), or ``None`` where it
            establishes none — which includes every user-authored free-text
            argument.
    """

    name: str
    protocol: DestinationProtocol | None
    tier: DataTier | None


@dataclass(frozen=True, slots=True)
class EgressDeclaration:
    """A tool's whole declaration to the binding seam, already checked.

    Constructed only by :func:`read_declaration`, which refuses every breach
    ADR-0152 §3 and §4 state before this value exists — so holding one means the
    declaration is usable, in ADR-0016 §1's sense that "a tool that does not
    declare its reach does not load".

    Attributes:
        tool_id: The tool this describes, for a refusal's text.
        named: Every top-level key the schema **statically names** — a key of its
            top-level ``properties`` object — in the order the schema lists them.
            A key admitted only by an open-ended form is not among them, however
            validly a call type-checks against it (ADR-0152 §6).
        arguments: One entry per statically named key, keyed by name.
    """

    tool_id: str
    named: tuple[str, ...]
    arguments: Mapping[str, ArgumentDeclaration]

    def declaration_for(self, argument: str) -> ArgumentDeclaration | None:
        """What ``argument`` declares, or ``None`` where the schema never named it.

        Args:
            argument: A top-level key of a call's parameters.

        Returns:
            Its declaration, or ``None``.
        """
        return self.arguments.get(argument)


def _refuse(message: str) -> EgressBindingError:
    """Build the refusal, which renders no argument value (ADR-0152 §11)."""
    return EgressBindingError(message)


def _subschemas(node: FrozenJson) -> Iterator[Mapping[str, FrozenJson]]:
    """Every mapping reachable from ``node``, itself included, depth first.

    Deliberately structure-blind: it walks mappings and sequences without knowing
    which keys are applicators, because an unknown applicator is exactly where a
    mis-declared keyword would otherwise hide.
    """
    if isinstance(node, str):
        return
    if isinstance(node, Mapping):
        yield node
        for value in node.values():
            yield from _subschemas(value)
        return
    if isinstance(node, Sequence):
        for value in node:
            yield from _subschemas(value)


def mentions_a_keyword(schema: Mapping[str, FrozenJson]) -> bool:
    """Whether either keyword appears anywhere in ``schema`` (ADR-0152 §8).

    The presence scan ADR-0152 §8's partition turns on, and it is deliberately
    **not** the well-formedness check: a tool this seam holds no egress
    registration for is refused where it declares either keyword *anywhere*,
    because returning ``None`` would silently discard a declaration its author
    wrote — whether or not that declaration would also have been refused for where
    it put the keyword.

    Args:
        schema: The tool's ``parameters_schema``.

    Returns:
        ``True`` where either keyword is a key of any mapping in it.
    """
    return any(
        keyword in subschema for subschema in _subschemas(schema) for keyword in EGRESS_KEYWORDS
    )


def _top_level_properties(schema: Mapping[str, FrozenJson]) -> Mapping[str, FrozenJson]:
    """The schema's top-level ``properties`` object, or an empty mapping.

    A tool with no ``parameters_schema``, or with one carrying no top-level
    ``properties`` object, statically names **no** key (ADR-0152 §6). ADR-0145 §9's
    "an absent schema declares no constraint" is relied on as true and is exactly
    why the seam adds a constraint of its own here.
    """
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        return properties
    return {}


def _untyped_defect(declared: FrozenJson) -> str:
    """Why a ``type`` that is neither ``"string"`` nor ``"array"`` is not flat.

    A subschema declaring no type at all, or a union of types, or an applicator in
    place of one, is not a flat declaration (ADR-0152 §4). Split out so
    :func:`_flat_defect` stays inside the branch budget rather than growing a
    ``noqa``.
    """
    if declared is None:
        return "declares no type"
    if not isinstance(declared, str):
        return "declares a union of types"
    return f"declares type {declared!r}"


def _flat_defect(subschema: Mapping[str, FrozenJson]) -> str | None:
    """Why ``subschema`` is not ADR-0152 §4's flat declaration, or ``None``.

    Exactly two forms and no other: ``"type": "string"``, or ``"type": "array"``
    whose ``items`` is a subschema whose own ``"type"`` is ``"string"``. A
    subschema declaring no type, a union of types, a ``$ref``, or an applicator in
    place of a type is not flat.

    What the constraint buys is that two of ADR-0150 §4's three
    under-representation failures stop being *reachable* for a destination rather
    than being refused: a destination-bearing argument's value decomposes to
    exactly one recipient in exactly one span, so a span cannot hold two
    recipients and a supplied form is never extracted from inside a structured
    value. `core`'s own supplied-form invariant is then total.
    """
    if "$ref" in subschema:
        return "carries a $ref in place of a type"
    declared = subschema.get("type")
    if declared == "string":
        return None
    if declared != "array":
        return _untyped_defect(declared)
    return _flat_items_defect(subschema.get("items"))


def _flat_items_defect(items: FrozenJson) -> str | None:
    """Why an array declaration's ``items`` is not a bare string subschema.

    ``items`` must be a single subschema whose own ``type`` is ``"string"``: a
    tuple form, an absent one, or one reached through a ``$ref`` each leaves the
    element type decided somewhere this seam does not read.
    """
    if not isinstance(items, Mapping):
        return "is an array declaring no single items subschema"
    if "$ref" in items:
        return "is an array whose items carries a $ref in place of a type"
    if items.get("type") != "string":
        return "is an array whose items is not declared as a string"
    return None


def _declared_protocol(
    tool_id: str, name: str, value: FrozenJson, canonicalises: Collection[DestinationProtocol]
) -> DestinationProtocol:
    """Resolve ``x-egress-destination``'s value, refusing what the seam cannot use.

    Raises:
        EgressBindingError: If the value names no ``DestinationProtocol`` member,
            or names one this seam holds no canonicaliser for — ADR-0148 §1's
            third clause, and not a pass-through.
    """
    members = {member.value: member for member in DestinationProtocol}
    protocol = members.get(value) if isinstance(value, str) else None
    if protocol is None:
        msg = (
            f"{tool_id}: argument {name!r} declares {DESTINATION_KEYWORD} as a value "
            f"naming no destination protocol this repository defines"
        )
        raise _refuse(msg)
    if protocol not in canonicalises:
        msg = (
            f"{tool_id}: argument {name!r} declares destinations in protocol "
            f"{protocol.value!r}, which this seam holds no canonicaliser for"
        )
        raise _refuse(msg)
    return protocol


def _declared_tier(tool_id: str, name: str, value: FrozenJson) -> DataTier:
    """Resolve ``x-egress-tier``'s value.

    Raises:
        EgressBindingError: If it names no :class:`DataTier` member. No lane reads
            an unrecognised value as "no declaration".
    """
    members = {member.value: member for member in DataTier}
    tier = members.get(value) if isinstance(value, str) else None
    if tier is None:
        msg = (
            f"{tool_id}: argument {name!r} declares {TIER_KEYWORD} as a value naming "
            f"no data tier this repository defines"
        )
        raise _refuse(msg)
    return tier


def read_declaration(
    schema: Mapping[str, FrozenJson],
    *,
    tool_id: str,
    canonicalises: Collection[DestinationProtocol],
) -> EgressDeclaration:
    """Read a tool's egress declaration, refusing every breach of ADR-0152 §3 and §4.

    Called on the **detached** copy of the tool's ``parameters_schema`` and on
    nothing else (ADR-0152 §1).

    Args:
        schema: The tool's ``parameters_schema``.
        tool_id: The declaring tool, for a refusal's text. It is the tool author's
            own identifier, which ADR-0152 §11 permits a refusal to name.
        canonicalises: The protocols this seam holds a canonicaliser for. Passed
            rather than imported so the one authority on that set stays the seam
            that holds it.

    Returns:
        The checked declaration.

    Raises:
        EgressBindingError: On a keyword outside a top-level property's own
            subschema; on a keyword value naming no member of its enum; on a
            protocol this seam holds no canonicaliser for; on a
            destination-bearing argument stating no tier; and on a
            destination-bearing argument whose declared shape is neither a string
            nor an array of strings. A declaration that cannot describe a call
            does not bind, which is ADR-0016 §1's "a tool that does not declare its
            reach does not load" at the one seam that reads a declaration the
            registry does not.
    """
    properties = _top_level_properties(schema)
    permitted = {
        id(subschema) for subschema in properties.values() if isinstance(subschema, Mapping)
    }
    for subschema in _subschemas(schema):
        if id(subschema) in permitted:
            continue
        for keyword in EGRESS_KEYWORDS:
            if keyword in subschema:
                msg = (
                    f"{tool_id}: {keyword} appears outside the immediate subschema of a "
                    f"top-level property. It declares a fact about a whole argument, so it "
                    f"is refused there rather than ignored (ADR-0152 §3); both names are "
                    f"reserved and no property may be named either of them"
                )
                raise _refuse(msg)

    arguments: dict[str, ArgumentDeclaration] = {}
    named: list[str] = []
    for name, declared in properties.items():
        named.append(name)
        if not isinstance(declared, Mapping):
            arguments[name] = ArgumentDeclaration(name=name, protocol=None, tier=None)
            continue
        protocol = (
            _declared_protocol(tool_id, name, declared[DESTINATION_KEYWORD], canonicalises)
            if DESTINATION_KEYWORD in declared
            else None
        )
        tier = (
            _declared_tier(tool_id, name, declared[TIER_KEYWORD])
            if TIER_KEYWORD in declared
            else None
        )
        if protocol is not None:
            if tier is None:
                msg = (
                    f"{tool_id}: argument {name!r} is destination-bearing and states no "
                    f"tier. A recipient is a value whose field establishes its tier "
                    f"(ADR-0146 §5), and a description stating none for the destinations "
                    f"under-describes the span the approver most needs (ADR-0148 §8)"
                )
                raise _refuse(msg)
            defect = _flat_defect(declared)
            if defect is not None:
                msg = (
                    f"{tool_id}: argument {name!r} is marked destination-bearing and {defect}. "
                    f"Only a string, or an array whose items is a string, may be "
                    f"(ADR-0152 §4); widening that needs its own ratified ADR"
                )
                raise _refuse(msg)
        arguments[name] = ArgumentDeclaration(name=name, protocol=protocol, tier=tier)

    return EgressDeclaration(tool_id=tool_id, named=tuple(named), arguments=arguments)


__all__ = [
    "DESTINATION_KEYWORD",
    "EGRESS_KEYWORDS",
    "TIER_KEYWORD",
    "ArgumentDeclaration",
    "EgressDeclaration",
    "mentions_a_keyword",
    "read_declaration",
]
