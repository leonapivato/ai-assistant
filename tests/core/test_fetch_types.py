"""The five values and one enumeration ADR-0230 §4 adds, and what each refuses.

§14 item 17 asks that "the models refuse what §1 says they refuse", arm for arm, and
this file is the half of that item which lives in `core`: the ``ReadAsk`` validator's
three arms, ``ReadRequest``'s at-most-one-of-each-kind rule over the new member, and
``FetchOutcome``'s exactly-one rule. The rest of item 17 — that a plan carrying two
``LOCAL_FILE`` asks is not an emission this corpus admits, asserted through a planner
— is Lane C2's.

**Mutation after construction is asserted here too**, because every model ADR-0230
adds is frozen and item 17 names that as an arm of its own: a value a servicer could
edit after verifying it is a value whose verification means nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import (
    Attestation,
    FetchOutcome,
    FetchRefusal,
    MemorySource,
    Provenance,
    ReadAsk,
    ReadKind,
    ReadRequest,
    SemanticMemory,
    ShownFile,
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


# --- the LOCAL_FILE ask (ADR-0230 §1) ---------------------------------------


def test_a_local_file_ask_carries_one_entry_label() -> None:
    """The positive arm, so the refusals below are not vacuous."""
    ask = ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F2")

    assert (ask.entry, ask.query, ask.labels) == ("F2", None, ())


@pytest.mark.parametrize("entry", [None, "", "   ", "\n\t"])
def test_a_local_file_ask_without_a_non_blank_entry_is_refused(entry: str | None) -> None:
    """§1: "a ``LOCAL_FILE`` ask carries a non-blank ``entry``".

    ``None`` and a whitespace-only string are different mistakes and only one of them
    is "this kind's argument is missing", which is why the model decides both here
    rather than leaving the second to a field annotation that would name neither.
    """
    with pytest.raises(ValidationError, match="non-blank entry"):
        ReadAsk(kind=ReadKind.LOCAL_FILE, entry=entry)


def test_a_local_file_ask_carrying_a_query_is_refused() -> None:
    """An ask carrying two kinds' arguments is two asks wearing one kind's name."""
    with pytest.raises(ValidationError, match="must not carry a query"):
        ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1", query="what did it say")


def test_a_local_file_ask_carrying_labels_is_refused() -> None:
    """``entry`` and ``labels`` index **different sequences** (§1).

    A ``CITATION_HOP`` label is an ordinal into the ``memories`` sequence; a
    ``LOCAL_FILE`` label is an ordinal into the *listing*. An ask carrying both would
    make the model's output ambiguous at exactly the seam ADR-0226 §3 exists to keep
    unambiguous.
    """
    with pytest.raises(ValidationError, match="must not carry labels"):
        ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1", labels=("M1",))


@pytest.mark.parametrize(
    ("kind", "argument"),
    [(ReadKind.SIGHTED_QUERY, {"query": "q"}), (ReadKind.CITATION_HOP, {"labels": ("M1",)})],
)
def test_an_older_kinds_ask_carrying_an_entry_is_refused(
    kind: ReadKind, argument: dict[str, Any]
) -> None:
    """§1: "a ``SIGHTED_QUERY`` and a ``CITATION_HOP`` ask carry no ``entry``".

    The arm that keeps every arm of the validator uniform: each kind carries exactly
    its own argument and refuses the others, so a reader never has to consult ``kind``
    to know which field is meaningful.
    """
    with pytest.raises(ValidationError, match="must not carry an entry"):
        ReadAsk(kind=kind, entry="F1", **argument)


def test_a_request_naming_two_local_file_asks_is_refused() -> None:
    """ADR-0226 §2's at-most-one-of-each-kind rule, binding unchanged on the new member.

    ADR-0230 §1: "one emission carries at most one ``LOCAL_FILE`` ask, and a request
    naming two is not an emission this corpus admits". A turn that revises may emit a
    second on its *second* plan, which is ADR-0228 §3 applied and not widened.
    """
    ask = ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1")

    with pytest.raises(ValidationError, match="at most one ask of each kind"):
        ReadRequest(asks=(ask, ask))


def test_a_request_may_carry_a_local_file_ask_beside_each_other_kind() -> None:
    """The positive arm: three kinds, one of each, is the widest emission admitted."""
    request = ReadRequest(
        asks=(
            ReadAsk(kind=ReadKind.SIGHTED_QUERY, query="q"),
            ReadAsk(kind=ReadKind.CITATION_HOP, labels=("M1",)),
            ReadAsk(kind=ReadKind.LOCAL_FILE, entry="F1"),
        )
    )

    assert {ask.kind for ask in request.asks} == set(ReadKind)


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


def test_a_shown_file_has_no_field_a_capability_could_sit_in() -> None:
    """§4's containment is a property of the type (§14 item 20's structural half).

    "A ``Planner`` receives no ``handle``, no ``token`` and no ``SourceListing``, so an
    implementation that rendered every field of every value it was handed, logged them,
    or returned them discloses no capability, because there is none on the value to
    disclose."

    Asserted over the field *set* rather than by naming the two absentees, so a field
    added tomorrow fails here on the day it is added.
    """
    assert set(ShownFile.model_fields) == {"name", "size_bytes", "modified_at"}


def test_a_listing_entry_carries_a_handle_and_no_path() -> None:
    """§4: an entry "carries **no path, no root and no directory component**"."""
    assert set(SourceListingEntry.model_fields) == {
        "name",
        "size_bytes",
        "modified_at",
        "handle",
    }


@pytest.mark.parametrize("model", [SourceListingEntry, ShownFile, SourceListing, FetchOutcome])
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
