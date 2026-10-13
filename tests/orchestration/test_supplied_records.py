"""ADR-0204 §2's value over what a phases activation held (ADR-0309 §5:10).

:class:`~ai_assistant.orchestration.supplied_records.SuppliedRecords` on its own: the two
terms over every record handed in, the windows' records left out on a pass of unbounded
audience and counted on any other, the context facets counted on both, and the predicate
the old path's turn evaluates through its two postures, compared case by case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    CalendarFacet,
    CurrentContext,
    EmailFacet,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
    TimeOfDay,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.supplied_records import SuppliedRecords

if TYPE_CHECKING:
    from ai_assistant.core.types import MemoryRecord
    from ai_assistant.orchestration.disclosure import TurnSupply

_AT: Final = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_CALENDAR: Final = "calendar"
_SOURCES: Final = frozenset({_CALENDAR})
_BOUNDED: Final = BoundedAudienceSupply(speakable_attested_sources=_SOURCES)
_UNBOUNDED: Final = UnboundedAudienceSupply(speakable_attested_sources=_SOURCES)
_STAMPED: Final = Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=_AT)


def _record(  # noqa: PLR0913 — one knob per recorded-origin field a case varies
    record_id: str = "m1",
    *,
    source: MemorySource = MemorySource.OBSERVED,
    about_person: str | None = None,
    reported_by: str | None = None,
    placement: Placement | None = None,
    content: str = "the user likes green tea",
) -> SemanticMemory:
    """One belief, with exactly the fields ADR-0199 §2 and ADR-0217 §1 decide from."""
    return SemanticMemory(
        id=record_id,
        content=content,
        fact=content,
        about_person=about_person,
        provenance=Provenance(
            source=source,
            confidence=1.0 if source is MemorySource.USER_ASSERTED else 0.6,
            last_updated=_AT,
            attestation=(
                None
                if reported_by is None
                else Attestation(reported_by=reported_by, reported_at=_AT)
            ),
        ),
        placement=Placement() if placement is None else placement,
    )


def _context(**facets: object) -> CurrentContext:
    return CurrentContext(
        now=_AT,
        time_of_day=TimeOfDay.AFTERNOON,
        is_weekend=False,
        within_working_hours=True,
        **facets,  # type: ignore[arg-type]  # one facet field per case
    )


class _HealthFacet(CalendarFacet):
    """A facet nobody has placed, standing in for the next source to land."""


#: Each kind of record ADR-0199 §3 withholds from a channel of unbounded audience, and
#: one already stamped (ADR-0204 §2's second term, as ADR-0217 §1:3 carries it).
_WITHHELD: Final = {
    "about someone else": _record(about_person="Sam"),
    "an unplaced attested source": _record(source=MemorySource.EXTERNAL, reported_by="mail"),
    "already stamped": _record(placement=_STAMPED),
    "placed for the owner by the owner": _record(
        placement=Placement(
            reach=PlacementReach.OWNER, set_by=PlacementSetter.OWNER_ACT, set_at=_AT
        )
    ),
}

#: Each kind of record ADR-0199 §3 places as speakable, so none sets the value.
_PLACED: Final = (
    _record("said", source=MemorySource.USER_ASSERTED),
    _record("seen", source=MemorySource.OBSERVED),
    _record("worked out", source=MemorySource.INFERRED),
    _record("calendar", source=MemorySource.EXTERNAL, reported_by=_CALENDAR),
)


def test_nothing_held_is_false_on_either_pass() -> None:
    """ADR-0204 §1:3: ``False`` is the meaning where neither term holds."""
    held = SuppliedRecords()

    assert not held.withheld(_BOUNDED)
    assert not held.withheld(_UNBOUNDED)


@pytest.mark.parametrize("audience", [_BOUNDED, _UNBOUNDED])
def test_records_every_one_of_them_placed_are_false(audience: TurnSupply) -> None:
    """§2:2: ``False`` only where neither term holds of any record held."""
    held = SuppliedRecords()
    held.windows(_PLACED[:2])
    held.obtained(_PLACED)

    assert not held.withheld(audience)


@pytest.mark.parametrize("record", _WITHHELD.values(), ids=_WITHHELD.keys())
@pytest.mark.parametrize("audience", [_BOUNDED, _UNBOUNDED])
def test_an_obtained_record_withheld_or_stamped_is_true(
    record: MemoryRecord, audience: TurnSupply
) -> None:
    """§2:2's two terms, over a record recall kept or a call returned, on every pass."""
    held = SuppliedRecords()
    held.obtained([*_PLACED, record])

    assert held.withheld(audience)


@pytest.mark.parametrize("record", _WITHHELD.values(), ids=_WITHHELD.keys())
def test_a_window_record_counts_on_a_bounded_pass_and_not_an_unbounded_one(
    record: MemoryRecord,
) -> None:
    """ADR-0309 §5:10, ADR-0210 §1:1, §1:5: the windows are left out only when unbounded."""
    held = SuppliedRecords()
    held.windows([record])
    held.obtained(_PLACED)

    assert held.withheld(_BOUNDED)
    assert not held.withheld(_UNBOUNDED)


def test_a_window_record_also_obtained_counts_on_an_unbounded_pass() -> None:
    """ADR-0210 §1:2: a record both a window and a read carry is counted by the read."""
    stamped = _record(placement=_STAMPED)
    held = SuppliedRecords()
    held.windows([stamped])
    held.obtained([stamped])

    assert held.withheld(_UNBOUNDED)


@pytest.mark.parametrize("audience", [_BOUNDED, _UNBOUNDED])
def test_an_unplaced_context_facet_counts_on_either_pass(audience: TurnSupply) -> None:
    """§2:2's first term reaches the facets, which ADR-0210 §1:1 keeps on an unbounded pass."""
    held = SuppliedRecords()
    held.facets(
        _context(
            calendar=_HealthFacet(
                source="health", read_at=_AT, entries_in_progress=1, covers_until=_AT
            )
        )
    )

    assert held.withheld(audience)


def test_placed_context_facets_are_false() -> None:
    """ADR-0199 §3 places the calendar and email facets, so neither sets the value."""
    held = SuppliedRecords()
    held.facets(
        _context(
            calendar=CalendarFacet(
                source=_CALENDAR, read_at=_AT, entries_in_progress=1, covers_until=_AT
            ),
            email=EmailFacet(source="email", read_at=_AT, arrived_in_window=2, covers_from=_AT),
        )
    )

    assert not held.withheld(_BOUNDED)
    assert not held.withheld(_UNBOUNDED)


def test_records_added_later_count_and_nothing_held_is_dropped() -> None:
    """ADR-0309 §5:10: over every round, so a later addition counts and none clears it."""
    held = SuppliedRecords()
    held.obtained(_PLACED)
    assert not held.withheld(_BOUNDED)

    held.obtained([_record(placement=_STAMPED)])
    held.obtained(_PLACED)

    assert held.withheld(_BOUNDED)


def test_no_content_is_read() -> None:
    """ADR-0204 §2:7: the same recorded origin with any words gives the same value."""
    for content in ("my neighbour's diagnosis", "a sunny day"):
        held = SuppliedRecords()
        held.obtained([_record(content=content)])
        assert not held.withheld(_UNBOUNDED)


_CASES: Final = [
    pytest.param((), id="nothing"),
    pytest.param(_PLACED, id="placed"),
    *(pytest.param((*_PLACED, one), id=name) for name, one in _WITHHELD.items()),
]


@pytest.mark.parametrize("records", _CASES)
def test_the_value_is_the_old_paths_bounded_evaluation(records: tuple[MemoryRecord, ...]) -> None:
    """ADR-0204 §2:7: no second decision procedure — the bounded turn's own answer."""
    context = _context()
    old = BoundedAudienceSupply(speakable_attested_sources=_SOURCES)
    old(context, records, frozenset(one.id for one in records))
    held = SuppliedRecords()
    held.windows(records[:1])
    held.obtained(records[1:])
    held.facets(context)

    assert held.withheld(_BOUNDED) is old.withheld


@pytest.mark.parametrize("records", _CASES)
def test_the_value_is_the_old_paths_unbounded_evaluation_with_the_windows_as_its_tail(
    records: tuple[MemoryRecord, ...],
) -> None:
    """ADR-0210 §1:1: the windows set nothing, exactly as the conversation's tail does."""
    context = _context()
    window, rest = records[:1], records[1:]
    old = UnboundedAudienceSupply(speakable_attested_sources=_SOURCES)
    old(context, records, frozenset(one.id for one in rest))
    held = SuppliedRecords()
    held.windows(window)
    held.obtained(rest)
    held.facets(context)

    assert held.withheld(_UNBOUNDED) is old.withheld
