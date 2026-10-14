"""The values and the one enumeration ADR-0230 §4 adds, and what each refuses.

§14 item 17 asks that "the models refuse what §1 says they refuse", arm for arm, and
this file covers ``FetchOutcome``'s exactly-one rule and what each listing value
carries.

**Mutation after construction is asserted here too**, because every model ADR-0230
adds is frozen and item 17 names that as an arm of its own: a value a servicer could
edit after verifying it is a value whose verification means nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    Attestation,
    FetchOutcome,
    FetchRefusal,
    MemorySource,
    Provenance,
    SemanticMemory,
    SourceListing,
    SourceListingEntry,
)

_WHEN: Final = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

#: The same instant without a zone, for the arm that refuses one.
_NAIVE: Final = datetime(2026, 3, 1, 9, 0)  # noqa: DTZ001 — the value under test

#: A stand-in for a minted listing authority. Its *contents* mean nothing here: what a
#: token is, and what makes one unforgeable, is the fetcher's (ADR-0230 §4, §13).
_TOKEN: Final = "an opaque authority no test inspects"  # noqa: S105 — not a credential


def _entry(**overrides: object) -> SourceListingEntry:
    """One authentic-shaped entry, with any field overridden."""
    fields: dict[str, object] = {
        "name": "report.md",
        "size_bytes": 12,
        "modified_at": _WHEN,
        "handle": "0.abc",
    }
    return SourceListingEntry.model_validate(fields | overrides)


def _record() -> SemanticMemory:
    """One record of the shape a fetch mints, for the outcome arms."""
    return SemanticMemory(
        id="r1",
        content="text",
        fact="text",
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=_WHEN,
            attestation=Attestation(reported_by="files", reported_at=_WHEN),
        ),
    )


# --- the outcome (ADR-0230 §4) ----------------------------------------------


def test_an_outcome_carrying_both_a_record_and_a_refusal_is_refused() -> None:
    """ "Neither both nor neither" is enforced by the model rather than by a caller."""
    with pytest.raises(ValidationError, match="never both"):
        FetchOutcome(record=_record(), refusal=FetchRefusal.UNREADABLE)


def test_an_outcome_carrying_neither_is_refused() -> None:
    """The one outcome §6 says a fetch never has: "neither succeeding nor failing"."""
    with pytest.raises(ValidationError, match="never neither"):
        FetchOutcome()


# --- what each value carries, and what it may not ---------------------------


def test_a_listing_entry_carries_a_handle_and_no_path() -> None:
    """§4: an entry "carries **no path, no root and no directory component**"."""
    assert set(SourceListingEntry.model_fields) == {
        "name",
        "size_bytes",
        "modified_at",
        "handle",
    }


@pytest.mark.parametrize("model", [SourceListingEntry, SourceListing, FetchOutcome])
def test_every_value_this_decision_adds_refuses_an_unknown_field(model: type[BaseModel]) -> None:
    """``extra="forbid"`` on each, which is also what §12's version move turns on."""
    with pytest.raises(ValidationError):
        model.model_validate({"invented": 1})


def test_a_listing_entry_refuses_mutation_after_construction() -> None:
    """§14 item 17's frozen arm: a value a caller could edit after it was verified.

    ``fetch`` verifies a handle against a name; a caller able to change the name
    afterwards would hold a verified value that no longer says what was verified.
    """
    entry = _entry()

    with pytest.raises(ValidationError):
        entry.name = "other.md"


def test_a_listing_entry_refuses_a_blank_name_and_a_negative_size() -> None:
    """The two field domains §4 states, asserted where they are decided."""
    with pytest.raises(ValidationError):
        _entry(name="   ")
    with pytest.raises(ValidationError):
        _entry(size_bytes=-1)


def test_a_listing_refuses_a_naive_instant() -> None:
    """``read_at`` is tz-aware, which ADR-0026 §1 governs and the suite asserts."""
    with pytest.raises(ValidationError):
        SourceListing(source="files", read_at=_NAIVE, token=_TOKEN)  # a naive instant


def test_an_empty_listing_is_constructible_and_carries_its_token() -> None:
    """§6: an empty listing is a **success**, not a degenerate value."""
    listing = SourceListing(source="files", read_at=_WHEN, token=_TOKEN)

    assert listing.entries == ()


def test_the_refusal_enumeration_is_closed_at_five_members() -> None:
    """§6: "The enumeration is closed and no lane adds a sixth without the ADR".

    Pinned by value as well as by name, because a refusal's class is what §9's audit
    records and a renamed member would silently reinterpret every recorded turn.
    """
    assert {member.value for member in FetchRefusal} == {
        "not_found",
        "not_a_file",
        "unreadable",
        "too_large",
        "extraction_failed",
    }
