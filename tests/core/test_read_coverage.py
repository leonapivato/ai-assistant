"""``ReadCoverage`` and the reading field that carries it (ADR-0110 §2, §10).

Two things are contract here and the rest is spelling: the **endpoint type and
the invariant** (§2 pins them because a lane reading coverage as dates, indices
or an opaque source cursor would give a different answer to §3's containment
question while claiming compliance), and the **containment rule** itself, which
§3 states "so no lane has to derive it".

**The rule's operand is the extent, not the window** (ADR-0117 §3). ADR-0110 §3
asked containment of a record's envelope validity window and ADR-0117 partially
supersedes it there: the cases below are §3's own, restated over
:class:`ReportedExtent`, because the rule is unchanged in content and only its
subject moved. ``ReportedExtent``'s own cases live in
``tests/core/test_reported_extent.py``.

The field's optionality gets its own cases because the additive shape is what
lets every reading that predates ADR-0110 stay valid.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import get_type_hints

import pytest

from ai_assistant.core.types import ReadCoverage, ReportedExtent, SourceReading, Validity

_NOW = datetime(2026, 6, 1, tzinfo=UTC)
_LATER = _NOW + timedelta(days=30)


# --- §2: the endpoint type and the invariant --------------------------------


def test_both_ends_default_to_unbounded() -> None:
    """A coverage naming neither end covers everything, which §3 relies on."""
    coverage = ReadCoverage()

    assert coverage.covers_from is None
    assert coverage.covers_until is None


def test_an_inverted_coverage_is_refused() -> None:
    with pytest.raises(ValueError, match="covers_until must be after covers_from"):
        ReadCoverage(covers_from=_LATER, covers_until=_NOW)


def test_an_empty_coverage_is_refused() -> None:
    """The tie is refused too: ``[F, F)`` exhausted no instant."""
    with pytest.raises(ValueError, match="covers_until must be after covers_from"):
        ReadCoverage(covers_from=_NOW, covers_until=_NOW)


def test_a_naive_endpoint_is_refused() -> None:
    """``UtcInstant`` is the ruled endpoint type, and it rejects a naive value.

    §2 pins the domain rather than leaving it to the lane precisely so that
    ``covers_*`` compares directly against the extent's two ends — "a comparison
    across two different annotations would be a conversion for nothing, and a
    conversion is where a timezone is lost". ADR-0117 §2 pins the extent's domain
    for the same reason and to the same value, so the comparison stays direct.
    """
    with pytest.raises(ValueError, match=r"(?i)timezone|aware|utc"):
        ReadCoverage(covers_until=datetime(2026, 6, 1))  # noqa: DTZ001 — the point of the case


def test_a_coverage_is_frozen() -> None:
    coverage = ReadCoverage(covers_until=_LATER)

    with pytest.raises(ValueError, match=r"(?i)frozen|immutable"):
        coverage.covers_until = _NOW


# --- §3: containment, stated once so no lane derives it ---------------------


@pytest.mark.parametrize(
    ("coverage", "extent", "contained", "why"),
    [
        (ReadCoverage(), ReportedExtent(), True, "unbounded coverage contains an open extent"),
        (
            ReadCoverage(covers_until=_LATER),
            ReportedExtent(),
            False,
            "an unbounded extent end needs an unbounded coverage end",
        ),
        (
            ReadCoverage(covers_until=_LATER),
            ReportedExtent(extends_until=_LATER),
            True,
            "the exclusive ends may coincide",
        ),
        (
            ReadCoverage(covers_until=_LATER),
            ReportedExtent(extends_until=_LATER + timedelta(seconds=1)),
            False,
            "one second of overhang is still an overhang",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            ReportedExtent(extends_from=_NOW),
            True,
            "the inclusive starts may coincide",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            ReportedExtent(extends_from=_NOW - timedelta(seconds=1)),
            False,
            "an entry starting before the coverage is not inside it",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            ReportedExtent(),
            False,
            "an unbounded extent start needs an unbounded coverage start",
        ),
        (
            ReadCoverage(covers_from=_NOW, covers_until=_LATER),
            ReportedExtent(extends_from=_NOW, extends_until=_LATER),
            True,
            "an extent may fill its coverage exactly",
        ),
    ],
)
def test_containment_of_an_extent_in_a_coverage(
    coverage: ReadCoverage, extent: ReportedExtent, contained: bool, why: str
) -> None:
    assert coverage.contains(extent) is contained, why


def test_a_fully_open_extent_is_contained_only_by_a_fully_open_coverage() -> None:
    """§3's decisive property, stated as its own case because §3 turns on it.

    A source that states no bound at either end has said nothing a bounded reading
    could have exhausted, so such a record is never absence-demotable by one —
    which is what separates the bounded read from the deletion, and is the whole
    content of the decision.
    """
    open_extent = ReportedExtent()

    assert ReadCoverage().contains(open_extent)
    assert not ReadCoverage(covers_from=_NOW).contains(open_extent)
    assert not ReadCoverage(covers_until=_LATER).contains(open_extent)


def test_containment_takes_the_extent_and_never_a_validity() -> None:
    """ADR-0117 §3's change of operand, pinned where the rule lives.

    The carrier is a property of the predicate's *type* rather than a convention
    each of the two writers keeps, which is what "one rule, one place" buys here:
    a writer still reading ``record.validity`` cannot reach this method at all.
    ADR-0110 §3 named ``Validity`` and ADR-0117 §1 found it unusable — a record's
    operational window and its source's testimony are different subjects, and this
    signature is where the corpus stops confusing them.
    """
    hints = get_type_hints(ReadCoverage.contains)

    assert hints["extent"] is ReportedExtent
    assert Validity not in hints.values()


# --- §10: the field is optional, and its absence is load-bearing -------------


def test_a_reading_declares_no_coverage_by_default() -> None:
    """The additive shape ADR-0093 §3 established: every prior construction site stays valid."""
    reading = SourceReading(source="calendar:work", read_at=_NOW)

    assert reading.coverage is None


def test_a_reading_that_declares_coverage_carries_it_whole() -> None:
    coverage = ReadCoverage(covers_until=_LATER)

    reading = SourceReading(source="calendar:work", read_at=_NOW, coverage=coverage)

    assert reading.coverage == coverage


def test_a_stored_reading_without_the_field_still_parses() -> None:
    """The migration story: a reading serialised before ADR-0110 stays readable."""
    before = {"source": "calendar:work", "read_at": _NOW.isoformat(), "proposals": []}

    reading = SourceReading.model_validate(before)

    assert reading.coverage is None
