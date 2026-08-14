"""Which arguments select recipients, declared rather than found in prose.

ADR-0148's Consequences say what an integration at the designated seam owes, and
this module is the second item: it "declares its destination-bearing arguments".
A **destination-bearing argument** is ADR-0148's own term — "an argument of such a
call from which a semantic recipient **of that same call** is determined" — and
the point of declaring them is that a later seam can compute the canonical
destination set from the call's parameters **mechanically**, by looking in named
fields, rather than by inspecting values to guess which of them look like
addresses.

That the declaration is the authority is the same discipline ADR-0016 §1 fixes
for the safety fields: "declared, not inferred", because deriving a fact "from
whether the tool's name starts with ``send_`` … fails silently for every tool
nobody thought about". ADR-0148 §2's third clause states the consequence of
getting it wrong in terms: "An integration that believed its operation selects
nothing while an argument in fact names a recipient has mis-declared its
destination-bearing arguments, which is a defect in the same class as a
mis-declared ``discloses``".

**Everything here is `tools/`-internal and inert.** The value that carries a
destination set into an ``ActionRequest`` is ADR-0148 §11's surface (a) and is
deferred to its own contract ADR; nothing in this module reaches
``permissions/``, transmits, or is registered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_assistant.core.errors import ToolError
from ai_assistant.tools.destinations import (
    Destination,
    DestinationCanonicalisationError,
    canonicalise,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.tools.destinations import DestinationProtocol


class DestinationSelectionError(ToolError):
    """The call's arguments do not yield a destination set this seam will assert.

    Raised for a malformed declaration, for an argument whose value is not of the
    declared shape, and — chained from
    :class:`~ai_assistant.tools.destinations.DestinationCanonicalisationError` —
    for a supplied form with no canonical form. All three end at ADR-0148 §1's
    third clause: the request "is **refused before the ruling**, and no ruling is
    sought for it".

    The message names the argument and the position within it, never the value:
    an address is Tier 1 and a refusal message reaches a log.
    """


@dataclass(frozen=True, slots=True)
class DestinationArgument:
    """One argument of a tool's schema from which recipients are determined.

    Attributes:
        name: The parameter's name, as the tool's ``parameters_schema`` declares
            it.
        protocol: The protocol under whose rules its values are canonicalised.
            Declared per argument rather than per tool, because nothing stops a
            future integration selecting recipients in two protocols, and the
            canonicaliser is chosen per destination (ADR-0148 §2).
        multiple: Whether the value is a sequence of destinations rather than
            one. Declared rather than sniffed from the value, so a JSON string
            arriving where a list was meant is a refusal instead of a single
            recipient nobody intended.
        required: Whether the call must select at least one recipient through
            this argument.
    """

    name: str
    protocol: DestinationProtocol
    multiple: bool
    required: bool


@dataclass(frozen=True, slots=True)
class DestinationDeclaration:
    """Every destination-bearing argument of one registered tool.

    Attributes:
        tool_id: The ``ToolDefinition.id`` this declaration describes. Carried so
            a refusal can name the tool, and so a declaration cannot be paired
            with a definition it was not written for.
        arguments: The destination-bearing arguments, in the order a description
            and a confirmation list them. The order is part of the declaration
            because a deterministic description needs one (ADR-0148 §6) and
            ``to`` before ``bcc`` is what a user reads.

    Raises:
        DestinationSelectionError: If it names no argument, or names one twice.
    """

    tool_id: str
    arguments: tuple[DestinationArgument, ...]

    def __post_init__(self) -> None:
        """Refuse a declaration no call could be completed against.

        The empty case is refused rather than treated as ADR-0148 §2's third
        clause — a call whose arguments select no onward recipient, whose
        destination set is "the **connected account** alone". That case is real
        and this type cannot express it: the connected account is bound by an
        identity and a connection reference (§6) that live in a connection record
        whose owner and location ADR-0125 §12 and ADR-0148 §13 leave undecided.
        Returning an empty set here would let such a call be described as
        selecting nobody rather than as selecting the account, which is the
        carve-out #68's third comment warns "needs care".

        Raises:
            DestinationSelectionError: On an empty or duplicated declaration.
        """
        if not self.arguments:
            msg = (
                f"{self.tool_id}: a destination declaration names at least one "
                f"argument. A call whose arguments select no onward recipient is "
                f"authorised against the connected account alone (ADR-0148 §2), "
                f"which no value in tools/ can name today (ADR-0125 §12)"
            )
            raise DestinationSelectionError(msg)
        names = [argument.name for argument in self.arguments]
        if len(set(names)) != len(names):
            msg = f"{self.tool_id}: a destination declaration names each argument once"
            raise DestinationSelectionError(msg)


def _supplied_forms(
    declaration: DestinationDeclaration, argument: DestinationArgument, value: object
) -> tuple[str, ...]:
    """Read the supplied destination forms out of one argument's value.

    Args:
        declaration: The declaration being applied, for the refusal's text.
        argument: The declared argument whose value this is.
        value: The value the parameters carried under ``argument.name``.

    Returns:
        The supplied forms, in the order the argument carried them.

    Raises:
        DestinationSelectionError: If the value is not of the declared shape, or
            a required argument selects nobody.
    """
    where = f"{declaration.tool_id}: argument {argument.name!r}"
    if argument.multiple:
        # `str` is a `Sequence` and is excluded deliberately: iterating one would
        # turn a single address into a recipient per character.
        if isinstance(value, str) or not isinstance(value, Sequence):
            msg = f"{where} is declared as a list of destinations"
            raise DestinationSelectionError(msg)
        given: tuple[object, ...] = tuple(value)
    else:
        given = (value,)
    forms: list[str] = []
    for index, form in enumerate(given):
        if not isinstance(form, str):
            msg = f"{where} entry {index} is not a string"
            raise DestinationSelectionError(msg)
        forms.append(form)
    if argument.required and not forms:
        msg = f"{where} is required and selects no recipient"
        raise DestinationSelectionError(msg)
    return tuple(forms)


def select_destinations(
    declaration: DestinationDeclaration, parameters: Mapping[str, FrozenJson]
) -> tuple[Destination, ...]:
    """Every recipient ``parameters`` selects, each in both forms.

    One **occurrence** per supplied form, in declaration order and then in the
    order the argument carried them — not a set. Two occurrences may share a
    canonical form (``Alice@Example.com`` in ``to`` and ``alice@example.com`` in
    ``cc`` are one recipient), and ADR-0148 §2's fourth clause requires *both*
    supplied forms to survive into the description and the audit record, so the
    de-duplication happens where the *set* is taken —
    :func:`~ai_assistant.tools.destinations.canonical_destination_set` — and never
    here.

    Nothing is resolved, defaulted, expanded or added: this reads named fields
    and canonicalises what it finds, which is the whole of what ADR-0148 §1's
    second clause permits before the ruling.

    Args:
        declaration: The tool's destination-bearing arguments.
        parameters: The call's arguments.

    Returns:
        The selected destinations, ordered deterministically.

    Raises:
        DestinationSelectionError: If a required argument is absent or selects
            nobody, if a value is not of the declared shape, if a supplied form
            has no canonical form, or if the call selects no recipient at all.
    """
    selected: list[Destination] = []
    for argument in declaration.arguments:
        if argument.name not in parameters:
            if argument.required:
                msg = f"{declaration.tool_id}: required argument {argument.name!r} is absent"
                raise DestinationSelectionError(msg)
            continue
        forms = _supplied_forms(declaration, argument, parameters[argument.name])
        for index, form in enumerate(forms):
            try:
                selected.append(canonicalise(argument.protocol, form))
            except DestinationCanonicalisationError as exc:
                msg = (
                    f"{declaration.tool_id}: argument {argument.name!r} entry "
                    f"{index} has no canonical form — {exc}"
                )
                raise DestinationSelectionError(msg) from exc
    if not selected:
        msg = f"{declaration.tool_id}: the call selects no recipient"
        raise DestinationSelectionError(msg)
    return tuple(selected)


__all__ = [
    "DestinationArgument",
    "DestinationDeclaration",
    "DestinationSelectionError",
    "select_destinations",
]
