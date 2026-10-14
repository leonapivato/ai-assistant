"""Every facet keeps the base's stamp and declares its own tag (ADR-0096 §1, §8).

ADR-0096 §1 rules things about a facet's *shape* that a reviewer holds rather than a
mechanism does: a subclass may not redefine ``source``, ``read_at`` or ``as_of``, and
ADR-0140 §6 has every concrete facet declare its own ``kind``. §8 marks a test for
them as owed, in this module's own words — "the same class of gap ADR-0015 names —
an invariant held by prose rather than mechanism".

**This is the shape ``test_instant_coverage.py`` uses**, and for its reason: a
rule stated in an ADR is opt-in, so the tenth facet author who does not read
ADR-0096 is exactly how the gap gets in.

Each path has an independent negative fixture, as ADR-0023 §2 requires of the
module this one is modelled on: either check can regress while the other stays
green, and a combined fixture would not say which one failed.
"""

from __future__ import annotations

import pkgutil
from importlib import import_module
from typing import Literal, get_args, get_origin

import pytest

import ai_assistant.core
from ai_assistant.core.types import CalendarFacet, ContextFacet, EmailFacet

#: The three names :class:`ContextFacet` reserves on every subclass (ADR-0096 §1).
#: Flat fields on a base share one namespace with the payload, so a facet whose own
#: vocabulary includes "source" would shadow the stamp.
RESERVED = ("source", "read_at", "as_of")

#: The name ADR-0140 §6 reserves for the facet union's discriminator, and it is
#: reserved **differently** from the three above. Those three live on the base and
#: a subclass must leave them alone; this one every *concrete* facet is required to
#: declare as its own distinct ``Literal`` — the one thing a no-redefinition rule
#: forbids, and a shared tag on the base would discriminate nothing. What no facet
#: may do is give the name a payload meaning.
DISCRIMINATOR = "kind"


def facets_redefining_a_reserved_name(facet: type[ContextFacet]) -> list[str]:
    """Names of the reserved fields ``facet`` redeclares rather than inherits."""
    own = vars(facet).get("__annotations__", {})
    return [name for name in RESERVED if name in own]


def literal_tag_of(facet: type[ContextFacet]) -> str | None:
    """``facet``'s own ``kind`` tag, or ``None`` where it declares none usable as one.

    ``None`` covers both failures ADR-0140 §6 forbids, because from the union's
    side they are one defect — it cannot resolve on the field. A facet may declare
    no ``kind`` at all, or it may give the name a **payload meaning** by declaring
    it as anything other than a single-valued ``Literal``: a ``kind: str`` is free
    text that discriminates nothing, and two facets could then carry the same tag
    at run time with the type system saying nothing.
    """
    field = facet.model_fields.get(DISCRIMINATOR)
    if field is None:
        return None
    annotation = field.annotation
    args = get_args(annotation)
    if get_origin(annotation) is not Literal or len(args) != 1:
        return None
    tag = args[0]
    return tag if isinstance(tag, str) else None


def _facet_subclasses() -> list[type[ContextFacet]]:
    """Every :class:`ContextFacet` subclass declared anywhere in ``ai_assistant.core``."""
    found: dict[str, type[ContextFacet]] = {}
    for info in pkgutil.walk_packages(ai_assistant.core.__path__, f"{ai_assistant.core.__name__}."):
        module = import_module(info.name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, ContextFacet)
                and value is not (ContextFacet)
            ):
                found[f"{value.__module__}.{value.__qualname__}"] = value
    return list(found.values())


def test_the_scan_actually_finds_the_facets() -> None:
    """A discovery check that silently found nothing would pass forever."""
    assert {facet.__name__ for facet in _facet_subclasses()} >= {"CalendarFacet"}


@pytest.mark.parametrize("facet", _facet_subclasses(), ids=lambda facet: facet.__name__)
def test_no_facet_redefines_a_reserved_stamp_field(facet: type[ContextFacet]) -> None:
    """ADR-0096 §1's second clause: the three names belong to the base."""
    redefined = facets_redefining_a_reserved_name(facet)
    assert not redefined, f"{facet.__name__} redefines reserved field(s) {redefined} (ADR-0096 §1)"


def test_the_base_carries_exactly_the_three_stamp_fields() -> None:
    """The stamp is three fields, and a fourth would be a decision, not an edit.

    ``kind`` is deliberately **not** among them: a discriminator declared on the
    base would be one value shared by every member, which resolves nothing. It is
    each concrete facet's own (ADR-0140 §6).
    """
    assert tuple(ContextFacet.model_fields) == RESERVED


@pytest.mark.parametrize("facet", _facet_subclasses(), ids=lambda facet: facet.__name__)
def test_every_concrete_facet_declares_a_literal_kind(facet: type[ContextFacet]) -> None:
    """ADR-0140 §6, over the file rather than over the facets someone remembered.

    The union in :data:`~ai_assistant.core.types.ReadingFacet` is resolvable only
    while this holds, and the failure of a facet that forgets its tag is not a
    type error at the declaration — it is a ``SourceReading`` that stops
    validating, found by whichever test happens to construct one. Stated here for
    ``test_facet_coverage.py``'s own reason: the ninth facet is the one this
    catches, not the first.
    """
    assert literal_tag_of(facet) is not None, (
        f"{facet.__name__} declares no `kind` as a single-valued Literal, so the facet "
        f"union cannot discriminate on it (ADR-0140 §6)"
    )


def test_no_two_facets_share_a_tag() -> None:
    """Distinct across the union, which is the half a per-facet check cannot see.

    Every facet can declare a perfectly good ``Literal`` and two of them can
    declare the *same* one, at which point the union resolves by whichever member
    pydantic reaches first and §6's stated defect is back — "two facets that
    differ only in a scalar could parse as each other, quietly".
    """
    tags = [literal_tag_of(facet) for facet in _facet_subclasses()]

    assert len(set(tags)) == len(tags), f"facet tags are not distinct: {sorted(map(str, tags))}"


def test_the_two_shipped_facets_carry_the_tags_the_adr_names() -> None:
    """The tags are ADR-0140 §6's own spellings, not this lane's.

    A tag is a wire-visible name the moment either type acquires a persisted or
    wire-carried form, so which string it is stops being an implementation detail
    then. Pinning it now costs nothing and makes a later rename a decision.
    """
    assert literal_tag_of(CalendarFacet) == "calendar"
    assert literal_tag_of(EmailFacet) == "email"


# --- negative fixtures: each check must catch its own omission --------------


def test_the_reserved_name_check_catches_a_redefinition() -> None:
    """Path two, on its own: a subclass shadowing the stamp."""

    class _Shadowing(ContextFacet):
        source: str = "elsewhere"  # the shadowing this check exists to catch

    assert facets_redefining_a_reserved_name(_Shadowing) == ["source"]
    assert facets_redefining_a_reserved_name(CalendarFacet) == []  # the real one stays green


def test_the_tag_check_catches_a_facet_that_declares_none() -> None:
    """Path three: the omission that makes the union unresolvable."""

    class _Untagged(ContextFacet):
        arrived_in_window: int = 0

    assert literal_tag_of(_Untagged) is None
    assert literal_tag_of(EmailFacet) == "email"  # the real one stays green


def test_the_tag_check_catches_the_name_used_as_a_payload_field() -> None:
    """Path three by the subtler route: ``kind`` present, but not a discriminator.

    This is the shape a facet author reaches for when ``kind`` reads to them as a
    description — "which kind of thing this is" as free text. It satisfies every
    check that only asks whether the field exists, and discriminates nothing.
    """

    class _PayloadKind(ContextFacet):
        kind: str = "whatever the producer felt like"

    assert literal_tag_of(_PayloadKind) is None


def test_the_tag_check_catches_a_multi_valued_literal() -> None:
    """And the route between the two: a tag that names more than one member.

    ``Literal["email", "calendar"]`` is a valid annotation and an invalid tag —
    pydantic would map both values onto this one member, so the union would
    resolve a calendar payload to it.
    """

    class _TwoTags(ContextFacet):
        kind: Literal["email", "calendar"] = "email"

    assert literal_tag_of(_TwoTags) is None
