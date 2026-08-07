"""``ReadCoverage`` and the reading field that carries it (ADR-0110 §2, §10).

Two things are contract here and the rest is spelling: the **endpoint type and
the invariant** (§2 pins them because a lane reading coverage as dates, indices
or an opaque source cursor would give a different answer to §3's containment
question while claiming compliance), and the **containment rule** itself, which
§3 states "so no lane has to derive it".

The field's optionality gets its own cases because it is what keeps this ADR from
being a behaviour change: no reader in the tree declares coverage, so no window
closes until a reader lane opts in, and ADR-0093 §4's refusal stays the operative
behaviour of every reader that exists.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_assistant.core.types import ReadCoverage, SourceReading, Validity

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
    ``covers_*`` compares directly against ``Validity``'s two ends — "a comparison
    across two different annotations would be a conversion for nothing, and a
    conversion is where a timezone is lost".
    """
    with pytest.raises(ValueError, match=r"(?i)timezone|aware|utc"):
        ReadCoverage(covers_until=datetime(2026, 6, 1))  # noqa: DTZ001 — the point of the case


def test_a_coverage_is_frozen() -> None:
    coverage = ReadCoverage(covers_until=_LATER)

    with pytest.raises(ValueError, match=r"(?i)frozen|immutable"):
        coverage.covers_until = _NOW


# --- §3: containment, stated once so no lane derives it ---------------------


@pytest.mark.parametrize(
    ("coverage", "window", "contained", "why"),
    [
        (ReadCoverage(), Validity(), True, "unbounded coverage contains an open window"),
        (
            ReadCoverage(covers_until=_LATER),
            Validity(),
            False,
            "an unbounded record end needs an unbounded coverage end",
        ),
        (
            ReadCoverage(covers_until=_LATER),
            Validity(valid_until=_LATER),
            True,
            "the exclusive ends may coincide",
        ),
        (
            ReadCoverage(covers_until=_LATER),
            Validity(valid_until=_LATER + timedelta(seconds=1)),
            False,
            "one second of overhang is still an overhang",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            Validity(valid_from=_NOW),
            True,
            "the inclusive starts may coincide",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            Validity(valid_from=_NOW - timedelta(seconds=1)),
            False,
            "a record starting before the coverage is not inside it",
        ),
        (
            ReadCoverage(covers_from=_NOW),
            Validity(),
            False,
            "an unbounded record start needs an unbounded coverage start",
        ),
        (
            ReadCoverage(covers_from=_NOW, covers_until=_LATER),
            Validity(valid_from=_NOW, valid_until=_LATER),
            True,
            "a window may fill its coverage exactly",
        ),
    ],
)
def test_containment_of_a_window_in_a_coverage(
    coverage: ReadCoverage, window: Validity, contained: bool, why: str
) -> None:
    assert coverage.contains(window) is contained, why


def test_a_fully_open_window_is_contained_only_by_a_fully_open_coverage() -> None:
    """§3's decisive property, stated as its own case because §3 turns on it.

    A record with a fully open window states no position in the source's world, so
    it is never absence-demotable by a bounded reading — which is what separates
    the bounded read from the deletion, and is the whole content of the decision.
    """
    open_window = Validity()

    assert ReadCoverage().contains(open_window)
    assert not ReadCoverage(covers_from=_NOW).contains(open_window)
    assert not ReadCoverage(covers_until=_LATER).contains(open_window)


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
