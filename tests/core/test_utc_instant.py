"""Behaviour of the shared instant type (ADR-0023 §§2-3).

``tests/core/test_instant_coverage.py`` checks *structure* — that every ``core``
datetime field uses this type. It cannot check what the type does, so an
implementation could pass that gate while rejecting naive values and quietly
failing to convert aware ones. This module pins the behaviour instead, on a
throwaway model rather than on any one field, because the guarantee belongs to
the type.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest
from hostile_instants import (
    HOSTILE_IDS,
    HOSTILE_INSTANTS,
    BaseDatetimeConversion,
    FlipDuringComponentRead,
    FlipOnConvert,
    LyingConversion,
    MutableOffset,
    NoneConversion,
    NonUtcConversion,
    NoOffset,
    NotADatetimeConversion,
    RaisingOffset,
    ShiftySubclass,
    UnreprableOffset,
    ZeroButNotUtcConversion,
)
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import UtcInstant

if TYPE_CHECKING:
    from hostile_instants import HostileInstant


class _Instant(BaseModel):
    """A minimal carrier, so the tests are about the type and not about a field."""

    when: UtcInstant


def test_a_naive_value_is_rejected_and_the_field_is_named() -> None:
    """ADR-0023 §3: `core` cannot know the provenance, so it may not guess."""
    with pytest.raises(ValidationError, match="when must be timezone-aware"):
        _Instant(when=datetime(2026, 1, 1, 9))  # noqa: DTZ001 — a naive value is the subject


def test_an_indeterminate_offset_is_rejected() -> None:
    """ "Aware" means ``utcoffset()`` returns a value (ADR-0023 §5, issue #36).

    ``tzinfo is not None`` was always the wrong spelling: it accepts this value,
    which then raises on the first aware comparison downstream.
    """
    with pytest.raises(ValidationError, match="when must be timezone-aware"):
        _Instant(when=datetime(2026, 1, 1, 9, tzinfo=NoOffset()))


def test_a_raising_tzinfo_becomes_a_validation_error_not_a_crash() -> None:
    """Pydantic reports a ``ValueError`` as a validation failure; a ``RuntimeError``
    escapes as a crash from wherever the model happened to be constructed.
    """
    with pytest.raises(ValidationError, match="its tzinfo failed"):
        _Instant(when=datetime(2026, 1, 1, 9, tzinfo=RaisingOffset()))


def test_an_aware_non_utc_value_is_converted_not_merely_accepted() -> None:
    """The half that is easy to omit, and the half ADR-0023 §2 is really about."""
    made = _Instant(when=datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("America/New_York")))

    assert made.when.tzinfo is UTC
    assert made.when.utcoffset() == timedelta(0)
    assert made.when == datetime(2026, 1, 1, 14, tzinfo=UTC)


def test_conversion_preserves_the_instant() -> None:
    """Conversion is information-*preserving*; only the representation changes."""
    original = datetime(
        2026, 6, 1, 12, 34, 56, 789, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )

    assert _Instant(when=original).when == original
    assert _Instant(when=original).when.timestamp() == original.timestamp()


def test_utc_values_survive_unchanged() -> None:
    already = datetime(2026, 6, 1, 12, tzinfo=UTC)
    assert _Instant(when=already).when == already


def test_conversion_makes_a_dst_repeated_hour_order_by_instant() -> None:
    """Why §2 makes conversion mandatory rather than merely tidy.

    Python compares two aware datetimes sharing a ``tzinfo`` by their naive
    wall-clock values, ignoring ``fold`` — so the later instant compares as the
    earlier one. Converting to UTC makes same-``tzinfo`` comparison identical to
    instant comparison.
    """
    zone = ZoneInfo("America/New_York")
    earlier = datetime(2026, 11, 1, 1, 45, tzinfo=zone, fold=0)  # 05:45 UTC
    later = datetime(2026, 11, 1, 1, 15, tzinfo=zone, fold=1)  # 06:15 UTC

    assert later < earlier  # the bug, as stored values with a shared tzinfo
    assert _Instant(when=earlier).when < _Instant(when=later).when  # fixed by conversion


@pytest.mark.parametrize(
    "boundary",
    [
        pytest.param(
            datetime.min.replace(tzinfo=timezone(timedelta(hours=1))), id="min-at-plus-one"
        ),
        pytest.param(
            datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))), id="max-at-minus-one"
        ),
    ],
)
def test_a_value_with_no_utc_representation_is_rejected(boundary: datetime) -> None:
    """Aware, in range, and still unconvertible — ``astimezone`` overflows.

    ``OverflowError`` is not a ``ValueError``, so pydantic would let it escape as
    a crash rather than reporting it as a validation failure: the "accepted, then
    unusable" shape a validator exists to close.
    """
    with pytest.raises(ValidationError, match="when has no UTC representation"):
        _Instant(when=boundary)


def test_a_json_round_trip_keeps_utc() -> None:
    """The type has to survive serialisation, since that is how stores use it."""
    made = _Instant(when=datetime(2026, 1, 1, 9, tzinfo=ZoneInfo("America/New_York")))
    restored = _Instant.model_validate_json(made.model_dump_json())

    assert restored.when == made.when
    assert restored.when.utcoffset() == timedelta(0)


def test_a_naive_iso_string_is_rejected_on_the_way_in() -> None:
    """Deserialisation is where naive values actually arrive, not construction.

    ``DTZ`` lint stops a bare ``datetime.now()`` in first-party code; it sees
    nothing of a JSON payload whose timestamp lost its offset.
    """
    with pytest.raises(ValidationError, match="when must be timezone-aware"):
        _Instant.model_validate_json('{"when": "2026-01-01T09:00:00"}')


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param(LyingConversion(2026, 1, 2, tzinfo=UTC), id="returns-naive"),
        pytest.param(NonUtcConversion(2026, 1, 2, tzinfo=UTC), id="returns-non-utc"),
        pytest.param(ZeroButNotUtcConversion(2026, 1, 2, tzinfo=UTC), id="returns-zero-not-utc"),
        pytest.param(NotADatetimeConversion(2026, 1, 2, tzinfo=UTC), id="returns-non-datetime"),
        pytest.param(NoneConversion(2026, 1, 2, tzinfo=UTC), id="returns-none"),
    ],
)
def test_a_conversion_that_does_not_produce_utc_is_rejected(hostile: datetime) -> None:
    """Re-checking the result is the only step that can check itself.

    ``astimezone`` is overridable, and pydantic does not re-validate what an
    ``AfterValidator`` returns — so trusting the conversion would let this type
    certify exactly the naive value it exists to reject, with the ``TypeError``
    surfacing at the first comparison inside a store instead of here.
    """
    assert hostile.utcoffset() == timedelta(0)  # it passes every earlier check

    with pytest.raises(ValidationError, match="when did not convert to UTC"):
        _Instant(when=hostile)


def test_a_value_that_cannot_describe_itself_still_yields_a_validation_error() -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so interpolating the offending
    value with ``!r`` lets a hostile ``tzinfo`` raise from *inside* the ``except``
    block that was reporting it — replacing the field-naming ``ValueError`` with
    whatever ``__repr__`` threw.
    """
    with pytest.raises(ValidationError, match="when must be timezone-aware"):
        _Instant(when=datetime(2026, 1, 1, tzinfo=UnreprableOffset()))


@pytest.mark.parametrize(
    "subclass",
    [
        pytest.param(ShiftySubclass, id="flips-after-validation"),
        pytest.param(FlipDuringComponentRead, id="flips-during-component-read"),
    ],
)
def test_a_conversion_returning_a_subclass_is_refused_outright(
    subclass: type[datetime],
) -> None:
    """Why the canonicaliser requires an *exact* ``datetime``, not an instance of one.

    A subclass can override ``utcoffset()``, ``astimezone()``, the component
    properties and ``__getattribute__``, so it executes code between any two
    checks made on it: verify the offset and it flips while the digits are read;
    verify it again mid-read and it flips between two of them. No ordering of
    checks wins. Refusing the subclass makes every subsequent read the C
    implementation, which cannot be intercepted — so the offset and the
    components are necessarily one snapshot.
    """
    subclass.lie = timedelta(0)  # type: ignore[attr-defined]
    try:
        with pytest.raises(ValidationError, match="when did not convert to UTC"):
            _Instant(when=subclass(2026, 1, 2, 9, 0, tzinfo=UTC))
    finally:
        subclass.lie = timedelta(0)  # type: ignore[attr-defined]


def test_even_a_well_behaved_subclass_is_refused_and_that_is_the_trade() -> None:
    """Stating the cost rather than implying there is none.

    ``astimezone`` *preserves* the subclass, so the rule refuses every
    ``datetime`` subclass and not only a hostile one. Pinned deliberately: this
    is the behaviour a future caller will meet, and the alternative — trusting a
    subclass and checking it — is the thing shown above to be uncheckable.
    """

    class _WellBehaved(datetime):
        pass

    with pytest.raises(ValidationError, match="when did not convert to UTC"):
        _Instant(when=_WellBehaved(2026, 1, 2, 9, 0, tzinfo=ZoneInfo("Europe/Berlin")))


def test_a_subclass_converting_to_a_base_datetime_is_accepted() -> None:
    """ADR-0030 §1: the rule is on the value handed on, not the value received.

    "Refuses every subclass" is a *consequence* of ``astimezone`` preserving the
    subclass, not the rule — so the rare subclass whose conversion does yield an
    exact base ``datetime`` in UTC is accepted, and what is stored is rebuilt
    from that conversion rather than from the received value's own components.
    Pinned deliberately: this is the one case that separates the output-side
    rule from an input-side "refuse every subclass" test, which would satisfy
    every other case in this module while contradicting the decision.
    """
    stored = _Instant(when=BaseDatetimeConversion(2026, 7, 21, 12, tzinfo=UTC)).when

    assert type(stored) is datetime
    assert stored.tzinfo is UTC
    assert stored == BaseDatetimeConversion.converted  # the conversion, not the input
    assert stored is not BaseDatetimeConversion.converted  # rebuilt, not returned


def test_a_plain_datetime_is_still_canonicalised_to_a_plain_datetime() -> None:
    """The path everything real takes: parsed input is always a base datetime."""
    stored = _Instant(when=datetime(2026, 1, 2, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))).when

    assert type(stored) is datetime
    assert stored == datetime(2026, 1, 2, 8, 0, tzinfo=UTC)


def test_a_value_that_flips_its_offset_during_conversion_is_rejected() -> None:
    """Wall-clock digits denote an instant only together with an offset.

    This value passes the opening awareness check at zero, changes its offset
    while converting, and returns itself still carrying ``tzinfo is UTC``.
    Copying its components at that point would stamp ``09:00`` as ``09:00Z``
    when the value was, on its own account, ``07:00Z`` — so the offset is
    re-read at the moment of the copy, and this is refused instead.
    """
    FlipOnConvert.lie = timedelta(0)
    try:
        with pytest.raises(ValidationError, match="when did not convert to UTC"):
            _Instant(when=FlipOnConvert(2026, 1, 2, 9, 0, tzinfo=UTC))
    finally:
        FlipOnConvert.lie = timedelta(0)


def test_canonicalisation_preserves_the_instant_exactly() -> None:
    """Rebuilding must not round or drop precision — microseconds included."""
    precise = datetime(2026, 6, 1, 12, 34, 56, 987654, tzinfo=timezone(timedelta(hours=-3)))

    assert _Instant(when=precise).when == precise
    assert _Instant(when=precise).when.microsecond == 987654


def test_a_zero_offset_that_is_not_utc_cannot_change_its_mind_later() -> None:
    """Why the result is checked by ``tzinfo is UTC`` and not by a zero offset.

    ``utcoffset()`` is a method on an arbitrary object and need not answer the
    same way twice. An offset test would pass here and leave a *validated* model
    holding a value that becomes ``+02:00`` afterwards — the shared type's
    "stored as UTC" guarantee broken after the fact, with no comparison left to
    catch it.
    """
    MutableOffset.shift = timedelta(0)
    try:
        with pytest.raises(ValidationError, match="when did not convert to UTC"):
            _Instant(when=ZeroButNotUtcConversion(2026, 1, 2, tzinfo=UTC))
    finally:
        MutableOffset.shift = timedelta(0)


def test_every_genuine_conversion_yields_the_utc_object_itself() -> None:
    """The identity check is exact, not merely strict — it rejects nothing real.

    ``astimezone(tz)`` sets the result's ``tzinfo`` to the ``tz`` it was given,
    so only an overridden ``astimezone`` can fail it.
    """
    for zone in (
        ZoneInfo("America/New_York"),
        ZoneInfo("UTC"),
        timezone(timedelta(hours=2)),
        timezone(timedelta(0)),
        UTC,
    ):
        assert _Instant(when=datetime(2026, 1, 1, tzinfo=zone)).when.tzinfo is UTC


@pytest.mark.parametrize("case", HOSTILE_INSTANTS, ids=HOSTILE_IDS)
def test_the_shared_adversarial_table_holds_at_the_field_seam(case: HostileInstant) -> None:
    """ADR-0030 §4's shared table, asserted here and identically in ``test_clock.py``.

    The tests above pin each case with its own reasoning; this one exists so the
    *list* is shared. `core` has one canonicaliser, and a rule in two places with
    two test suites is two rules waiting to diverge — so a case added for one
    seam is automatically owed by the other, and a change to one that the other
    does not follow fails the gate rather than passing quietly.
    """
    case.reset()
    try:
        if case.accepted:
            stored = _Instant(when=case.make()).when
            assert type(stored) is datetime
            assert stored.tzinfo is UTC
            assert stored == case.canonical
        else:
            with pytest.raises(ValidationError):
                _Instant(when=case.make())
    finally:
        case.reset()
