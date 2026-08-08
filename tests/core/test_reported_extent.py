"""``ReportedExtent`` and the attestation field that carries it (ADR-0117 §2).

Three things are contract and the rest is spelling. The **domain** — a half-open
pair of ``UtcInstant | None`` — because ADR-0117 §2 pins it for ADR-0103 §9's
test: two lanes reading an extent as instants and as dates or source cursors give
different answers to ADR-0110 §3's containment question while each claims
compliance. The **invariant**, both-set implying end after start, because an
extent admitting no instant would be contained by every coverage and demotable by
any reading at all. And the **placement**, inside :class:`Attestation`, because
that is what makes the absence close structurally unreachable outside the
attested band rather than excluded by a rule.

The optionality gets its own cases because it is the whole migration story: the
field is additive, so every construction site, every fixture and every record
already in a store stays valid and simply states no position.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_assistant.core.types import (
    Attestation,
    MemorySource,
    PreferenceMemory,
    Provenance,
    ReportedExtent,
    Validity,
)

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(days=30)


# --- §2: the domain and the invariant ---------------------------------------


def test_both_ends_default_to_unbounded() -> None:
    """An extent naming neither end states no position, which §3 relies on."""
    extent = ReportedExtent()

    assert extent.extends_from is None
    assert extent.extends_until is None


def test_an_inverted_extent_is_refused() -> None:
    with pytest.raises(ValueError, match="extends_until must be after extends_from"):
        ReportedExtent(extends_from=_LATER, extends_until=_NOW)


def test_a_zero_width_extent_is_refused() -> None:
    """The tie is refused too, and the refusal is what makes declining necessary.

    ``[F, F)`` admits no instant, so it would be contained by *every* coverage and
    the record carrying it would be absence-demotable by any reading at all — the
    unsound direction. ADR-0117 §6 makes an instantaneous calendar entry decline
    the extent for exactly this reason, rather than widening its span by an
    invented epsilon to make it representable.
    """
    with pytest.raises(ValueError, match="extends_until must be after extends_from"):
        ReportedExtent(extends_from=_NOW, extends_until=_NOW)


def test_a_naive_endpoint_is_refused() -> None:
    """``UtcInstant`` is the ruled endpoint type, and it rejects a naive value.

    Pinned to the same annotation ``ReadCoverage`` uses, so §3's containment
    compares the two directly: a comparison across two annotations would be a
    conversion for nothing, and a conversion is where a timezone is lost.
    """
    with pytest.raises(ValueError, match=r"(?i)timezone|aware|utc"):
        ReportedExtent(extends_until=datetime(2026, 6, 1))  # noqa: DTZ001 — the point of the case


def test_an_extent_is_frozen() -> None:
    extent = ReportedExtent(extends_until=_LATER)

    with pytest.raises(ValueError, match=r"(?i)frozen|immutable"):
        extent.extends_until = _NOW


def test_one_end_alone_is_a_perfectly_good_extent() -> None:
    """Unbounded at one end is a statement, and §3 answers it without a special case."""
    assert ReportedExtent(extends_from=_NOW).extends_until is None
    assert ReportedExtent(extends_until=_LATER).extends_from is None


# --- §2: the placement, and the optionality ---------------------------------


def _attestation(*, extent: ReportedExtent | None = None) -> Attestation:
    return Attestation(reported_by="calendar", reported_at=_NOW, extent=extent)


def test_an_attestation_states_no_extent_by_default() -> None:
    """The additive shape ADR-0093 §3 established: every prior site stays valid.

    And the default is the safe one: a record stating no position is demotable by
    no reading, so nothing that existed before this field acquires a new way to be
    retired (ADR-0117 §9).
    """
    assert _attestation().extent is None


def test_an_attestation_carries_a_declared_extent_whole() -> None:
    extent = ReportedExtent(extends_from=_NOW, extends_until=_LATER)

    assert _attestation(extent=extent).extent == extent


def test_a_stored_attestation_without_the_field_still_parses() -> None:
    """The migration story: a belief serialised before ADR-0117 stays readable.

    ADR-0109 §2's test for a ``core`` validator — "does it refuse something that
    already worked" — comes out the same way here as it did there. A record in a
    running deployment's store decodes with no extent and is simply never
    absence-demotable, which needs no migration at all.
    """
    before = {"reported_by": "calendar", "reported_at": _NOW.isoformat()}

    attestation = Attestation.model_validate(before)

    assert attestation.extent is None


def test_a_stored_extent_round_trips_through_the_record() -> None:
    """It survives the whole envelope, which is what the writer's consumer reads."""
    extent = ReportedExtent(extends_from=_NOW, extends_until=_LATER)
    record = PreferenceMemory(
        id="meeting",
        content="a meeting",
        preference="a meeting",
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=_NOW,
            attestation=_attestation(extent=extent),
        ),
    )

    restored = PreferenceMemory.model_validate(record.model_dump(mode="json"))

    assert restored.provenance.attestation is not None
    assert restored.provenance.attestation.extent == extent


def test_the_extent_is_independent_of_the_records_envelope_window() -> None:
    """ADR-0117 §4: the operational window keeps its one job, and states no position.

    The pairing this case builds is the ordinary one for a forward-looking source
    and would have been unconstructable under ADR-0110 §3's reading: the belief is
    live now and unbounded — so retrievable, enumerable and visible to the fold —
    while stating that its entry lies a month out.
    """
    record = PreferenceMemory(
        id="thursday",
        content="a meeting on Thursday",
        preference="a meeting on Thursday",
        validity=Validity(),
        provenance=Provenance(
            source=MemorySource.EXTERNAL,
            confidence=0.9,
            last_updated=_NOW,
            attestation=_attestation(
                extent=ReportedExtent(
                    extends_from=_LATER, extends_until=_LATER + timedelta(hours=1)
                )
            ),
        ),
    )

    assert record.validity.live_at(_NOW), "the belief is on the read path today"
    assert record.provenance.attestation is not None
    assert record.provenance.attestation.extent is not None
    assert record.provenance.attestation.extent.extends_from == _LATER


def test_an_extent_needs_no_attestation_of_its_own_to_be_unreachable() -> None:
    """§2's placement is what makes ADR-0110 §3 band-scoped structurally.

    An attestation is present exactly when the band is ``ATTESTED`` (ADR-0092 §1),
    so a belief outside that band has nowhere to put an extent. #729's "``ASSERTED``
    is never auto-demotable" therefore holds by construction rather than by a check
    the two writers each have to remember — the stronger form ADR-0080 §2 preferred.
    """
    with pytest.raises(ValidationError):
        Provenance(
            source=MemorySource.USER_ASSERTED,
            confidence=1.0,
            last_updated=_NOW,
            attestation=_attestation(extent=ReportedExtent(extends_from=_NOW)),
        )
