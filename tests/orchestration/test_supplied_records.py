"""ADR-0204 §2's value over what a phases activation held (ADR-0309 §5:10).

:class:`~ai_assistant.orchestration.supplied_records.SuppliedRecords` on its own: the two
terms over every record handed in, and the windows' records left out on a pass of
unbounded audience and counted on any other, case by case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.types import (
    Attestation,
    BeliefBand,
    MemorySource,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    SemanticMemory,
)
from ai_assistant.orchestration.disclosure import BoundedAudienceSupply, UnboundedAudienceSupply
from ai_assistant.orchestration.supplied_records import SuppliedRecords
from ai_assistant.testing.memories import memory_in_band

if TYPE_CHECKING:
    from ai_assistant.core.types import SuppliedRecord
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


#: Each kind of record ADR-0199 §3 withholds from a channel of unbounded audience, and
#: one already stamped (ADR-0204 §2's second term, as ADR-0217 §1:3 carries it).
_WITHHELD: Final = {
    "about someone else": _record(about_person="Sam"),
    "an unplaced attested source": _record(source=MemorySource.EXTERNAL, reported_by="mail"),
    "already stamped": _record(placement=_STAMPED),
    # A memory is placed by its band (ADR-0328 §12): one from an unconfigured source,
    # and one about someone else, are withheld as a minted record would be.
    "a memory from an unplaced source": memory_in_band(
        "mem-mail",
        "the user's flight is at noon",
        BeliefBand.ATTESTED,
        attestation=Attestation(reported_by="mail", reported_at=_AT),
    ),
    "a memory about someone else": memory_in_band(
        "mem-sam", "Sam is allergic to nuts", about_person="Sam"
    ),
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
    memory_in_band("mem-said", "the user likes green tea"),
    memory_in_band("mem-inferred", "the user drinks tea daily", BeliefBand.DERIVED),
    memory_in_band(
        "mem-calendar",
        "the dentist is on Tuesday",
        BeliefBand.ATTESTED,
        attestation=Attestation(reported_by=_CALENDAR, reported_at=_AT),
    ),
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
    record: SuppliedRecord, audience: TurnSupply
) -> None:
    """§2:2's two terms, over a record recall kept or a call returned, on every pass."""
    held = SuppliedRecords()
    held.obtained([*_PLACED, record])

    assert held.withheld(audience)


@pytest.mark.parametrize("record", _WITHHELD.values(), ids=_WITHHELD.keys())
def test_a_window_record_counts_on_a_bounded_pass_and_not_an_unbounded_one(
    record: SuppliedRecord,
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


def _any_withheld(records: tuple[SuppliedRecord, ...]) -> bool:
    """Whether any of ``records`` is one of :data:`_WITHHELD`'s, by identity."""
    return any(one is withheld for one in records for withheld in _WITHHELD.values())


@pytest.mark.parametrize("records", _CASES)
def test_the_bounded_value_ranges_over_every_record_held(
    records: tuple[SuppliedRecord, ...],
) -> None:
    """ADR-0210 §1:5: on a pass of bounded audience nothing is left out, windows included."""
    held = SuppliedRecords()
    held.windows(records[:1])
    held.obtained(records[1:])

    assert held.withheld(_BOUNDED) is _any_withheld(records)


@pytest.mark.parametrize("records", _CASES)
def test_the_unbounded_value_leaves_the_windows_out(
    records: tuple[SuppliedRecord, ...],
) -> None:
    """ADR-0210 §1:1: the windows set nothing, exactly as the conversation's tail does."""
    window, rest = records[:1], records[1:]
    held = SuppliedRecords()
    held.windows(window)
    held.obtained(rest)

    assert held.withheld(_UNBOUNDED) is _any_withheld(rest)
