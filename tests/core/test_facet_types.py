"""The facet types and the stamp they carry (ADR-0096 §1, §2, §5, §6, §8).

ADR-0096 §8 enumerates what the ``core`` lane owes beyond the coverage check in
``test_facet_coverage.py``: the blank/no-normalisation pair on ``source``, a
round-trip pinning that a reading's facet payload survives ``model_dump`` and
``model_validate``, and **three independent rejection tests** on the stamp-equality
validator. The enumeration is normative because one test over a facet differing in
all three fields would pass against a validator written with ``and`` where it meant
``or`` — accepting a reading whose facet names a different source while every other
required test stayed green.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import CalendarFacet, ContextFacet, EmailFacet, SourceReading

_READ_AT = datetime(2026, 8, 4, 9, 30, tzinfo=UTC)
_AS_OF = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
_COVERS_UNTIL = _READ_AT + timedelta(days=7)


def _facet(**overrides: object) -> CalendarFacet:
    """A valid calendar facet, with the field under test overridden."""
    fields: dict[str, object] = {
        "source": "calendar",
        "read_at": _READ_AT,
        "as_of": _AS_OF,
        "entries_in_progress": 1,
        "next_starts_at": _READ_AT + timedelta(hours=2),
        "covers_until": _COVERS_UNTIL,
    }
    fields.update(overrides)
    return CalendarFacet.model_validate(fields)


def _reading(facet: CalendarFacet | EmailFacet | None) -> SourceReading:
    """A reading stamped ``calendar`` / ``_READ_AT`` / ``_AS_OF``, carrying ``facet``.

    The stamp is one reading's, so both facet types are constructed carrying it —
    ADR-0096 §5's validator is about the stamp being *faithful* and says nothing
    about which payload shape a source produces.
    """
    return SourceReading(source="calendar", read_at=_READ_AT, as_of=_AS_OF, facet=facet)


# --- §2: the source is rejected when blank and never normalised -------------


def test_a_blank_source_is_refused() -> None:
    """A facet naming nothing legible satisfies §7's floor while saying nothing."""
    with pytest.raises(ValidationError, match="must not be blank"):
        _facet(source="   ")


def test_an_accepted_source_is_returned_byte_for_byte() -> None:
    """The half a normalising validator would silently break (ADR-0096 §2).

    ``SourceReading.source`` is ``EncodableText`` and does not strip, so a facet
    that stripped would fail the stamp-equality validator for a *conforming*
    reader whose declared name is padded — a drift that stays invisible until
    something compares the two spellings, which is exactly what that validator
    does. A stripping implementation passes the blank test above and fails here.
    """
    assert _facet(source="  calendar  ").source == "  calendar  "


def test_the_padded_source_round_trips_through_a_reading() -> None:
    """The drift the previous test forbids, exercised end to end."""
    padded = _facet(source="  calendar  ")
    reading = SourceReading(source="  calendar  ", read_at=_READ_AT, as_of=_AS_OF, facet=padded)
    assert reading.facet is not None
    assert reading.facet.source == reading.source


def test_a_facet_without_a_declared_as_of_is_valid() -> None:
    """``None`` is the first real source's case and is a ruling, not laxity."""
    assert _facet(as_of=None).as_of is None


def test_the_base_is_frozen() -> None:
    """ADR-0068: a boundary-crossing value object does not mutate under a consumer."""
    facet = _facet()
    with pytest.raises(ValidationError):
        facet.source = "elsewhere"


# --- §6: the calendar payload ------------------------------------------------


def test_a_negative_entry_count_is_refused() -> None:
    """A count of occurrences cannot be negative."""
    with pytest.raises(ValidationError):
        _facet(entries_in_progress=-1)


def test_no_next_occurrence_is_representable() -> None:
    """``None`` says the reading found none *within its window*, never that none exists."""
    assert _facet(next_starts_at=None).next_starts_at is None


def test_the_facet_carries_no_entry_text() -> None:
    """ADR-0096 §6's prohibition, pinned as a property of the type.

    Three scalars and an instant carry no free text at all, which is what keeps the
    facet needing no content budget, no truncation rule and no timezone ruling —
    and, under ADR-0098 §5, what keeps attacker-authored strings off the facet path
    entirely. A field added here would be a decision, not an edit.

    ``kind`` is the discriminator ADR-0140 §6 requires of every concrete facet
    type, and it is a ``Literal`` tag rather than free text — a distinction
    ``test_facet_coverage.py`` holds as a property of the file, so the name cannot
    acquire a payload meaning here or on any later facet.
    """
    assert tuple(CalendarFacet.model_fields) == (
        "source",
        "read_at",
        "as_of",
        "kind",
        "entries_in_progress",
        "next_starts_at",
        "covers_until",
    )


def test_the_email_facet_carries_no_span_of_a_message() -> None:
    """ADR-0140 §6's second clause, pinned as a property of the type.

    Two scalars and a tag: no sender, address, display name, subject, body,
    identifier or per-message instant. The prohibition is stronger here than the
    calendar's because a subject line is *attacker-chosen* text on a path that
    reaches every prompt, and the assembler that would escape it does not exist
    yet (#672). A field added here would be a decision, not an edit.
    """
    assert tuple(EmailFacet.model_fields) == (
        "source",
        "read_at",
        "as_of",
        "kind",
        "arrived_in_window",
        "covers_from",
    )


def test_a_negative_arrival_count_is_refused() -> None:
    """A count of messages parsed from the store cannot be negative."""
    with pytest.raises(ValidationError):
        EmailFacet(
            source="email",
            read_at=_READ_AT,
            as_of=None,
            arrived_in_window=-1,
            covers_from=_READ_AT - timedelta(days=7),
        )


def test_the_base_is_not_constructed_as_a_facet_in_its_own_right() -> None:
    """``ContextFacet`` is a base for shared fields, never a field annotation (§1).

    It stays constructible — nothing in pydantic makes a base abstract, and making
    it so would buy nothing the coverage check does not — so what is pinned is that
    a base instance carries the stamp and no payload, which is precisely why an
    annotation naming it loses one.
    """
    bare = ContextFacet(source="calendar", read_at=_READ_AT)
    assert bare.model_dump() == {"source": "calendar", "read_at": _READ_AT, "as_of": None}


# --- §5: the reading's facet is stamped from the reading ---------------------


def test_a_reading_carrying_no_facet_is_valid() -> None:
    """A reader whose source has no situational reading returns ``None`` in it."""
    assert _reading(None).facet is None


def test_a_faithfully_stamped_facet_is_accepted() -> None:
    """The accepting case the three rejections below are read against."""
    facet = _facet()
    assert _reading(facet).facet == facet


def test_a_facet_naming_a_different_source_is_refused() -> None:
    """Rejection one of three, altering exactly ``source`` (ADR-0096 §8)."""
    with pytest.raises(ValidationError, match="source"):
        _reading(_facet(source="tasks"))


def test_a_facet_carrying_a_different_read_at_is_refused() -> None:
    """Rejection two of three, altering exactly ``read_at``."""
    with pytest.raises(ValidationError, match="read_at"):
        _reading(_facet(read_at=_READ_AT + timedelta(seconds=1)))


def test_a_facet_carrying_a_different_as_of_is_refused() -> None:
    """Rejection three of three, altering exactly ``as_of``.

    Including the case a validator that only compared "both present" would miss:
    the reading declares one and the facet does not.
    """
    with pytest.raises(ValidationError, match="as_of"):
        _reading(_facet(as_of=None))
    with pytest.raises(ValidationError, match="as_of"):
        SourceReading(source="calendar", read_at=_READ_AT, facet=_facet(as_of=_AS_OF))


def test_a_reading_with_a_facet_round_trips_with_its_payload_intact() -> None:
    """The property §1's third clause exists to hold (ADR-0096 §8).

    A base-annotated field holding a ``CalendarFacet`` dumped the three stamp
    fields and dropped the payload, with no warning emitted at all. The concrete
    annotation removes that at the root, and this is what would catch its
    regression: the count and both instants survive the round trip.
    """
    original = _reading(_facet())
    restored = SourceReading.model_validate(original.model_dump())
    assert restored.facet is not None
    assert isinstance(restored.facet, CalendarFacet)
    assert restored.facet == original.facet
    assert restored.facet.entries_in_progress == 1
    assert restored.facet.covers_until == _COVERS_UNTIL


# --- ADR-0140 §6: the union discriminates at validation ----------------------
# The static property ``test_facet_coverage.py`` gains — that each concrete facet
# declares a distinct ``Literal`` tag — is **necessary and not sufficient**: an
# ordinary union satisfies it while the annotation carries no
# ``Field(discriminator="kind")`` and pydantic resolves by inference. These cases
# exercise the resolution itself, which is where §6's stated defect lives: "two
# facets that differ only in a scalar could parse as each other, quietly".


def _email_facet(**overrides: object) -> EmailFacet:
    """A valid email facet stamped exactly as :func:`_reading`'s reading is."""
    fields: dict[str, object] = {
        "source": "calendar",
        "read_at": _READ_AT,
        "as_of": _AS_OF,
        "arrived_in_window": 4,
        "covers_from": _READ_AT - timedelta(days=7),
    }
    fields.update(overrides)
    return EmailFacet.model_validate(fields)


def test_each_tagged_payload_resolves_through_a_reading_to_its_own_type() -> None:
    """Both directions, because one alone is passed by a union that always picks it."""
    for facet, expected in ((_facet(), CalendarFacet), (_email_facet(), EmailFacet)):
        restored = SourceReading.model_validate(_reading(facet).model_dump())
        assert isinstance(restored.facet, expected)
        assert restored.facet == facet


def test_the_tag_decides_the_member_rather_than_the_payload_fitting_one() -> None:
    """A payload tagged ``email`` carrying calendar-shaped fields is an ``EmailFacet``.

    This is the case a *smart* union gets wrong: offered a payload whose extra
    fields fit ``CalendarFacet`` better, an inferring union picks by fit and the
    tag is decoration. A discriminated one reads the tag first and never looks at
    the rest, which is what makes a facet's type a fact of the payload rather than
    of pydantic's scoring.
    """
    payload = _reading(_email_facet()).model_dump()
    payload["facet"]["entries_in_progress"] = 5
    payload["facet"]["covers_until"] = _COVERS_UNTIL

    restored = SourceReading.model_validate(payload)

    assert isinstance(restored.facet, EmailFacet)
    assert restored.facet.arrived_in_window == 4


def test_a_payload_carrying_no_tag_is_rejected_rather_than_inferred() -> None:
    """The half ADR-0140 §6 spends a paragraph on: the default cannot rescue it.

    A discriminated union extracts its tag from the *input* before it selects a
    member, so a model-field default never runs for an input that omits the
    discriminator. Nothing persists or wire-carries one of these types today, so
    there is no legacy payload this invalidates — but the behaviour is real and
    counter-intuitive, and a later lane that gives either type a stored form finds
    it written down here rather than in a stack trace.
    """
    payload = _reading(_email_facet()).model_dump()
    del payload["facet"]["kind"]

    with pytest.raises(ValidationError, match="kind"):
        SourceReading.model_validate(payload)
