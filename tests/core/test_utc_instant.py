"""Behaviour of the shared instant type (ADR-0023 §§2-3).

``tests/core/test_instant_coverage.py`` checks *structure* — that every ``core``
datetime field uses this type. It cannot check what the type does, so an
implementation could pass that gate while rejecting naive values and quietly
failing to convert aware ones. This module pins the behaviour instead, on a
throwaway model rather than on any one field, because the guarantee belongs to
the type.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from ai_assistant.core.types import UtcInstant


class _Instant(BaseModel):
    """A minimal carrier, so the tests are about the type and not about a field."""

    when: UtcInstant


class _NoOffset(tzinfo):
    """Set, but indeterminate — issue #36's case. Not aware, by ADR-0023 §5."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "indeterminate"


class _RaisingOffset(tzinfo):
    """A ``tzinfo`` whose ``utcoffset()`` raises rather than answering."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        msg = "no offset available"
        raise RuntimeError(msg)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "raises"


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
        _Instant(when=datetime(2026, 1, 1, 9, tzinfo=_NoOffset()))


def test_a_raising_tzinfo_becomes_a_validation_error_not_a_crash() -> None:
    """Pydantic reports a ``ValueError`` as a validation failure; a ``RuntimeError``
    escapes as a crash from wherever the model happened to be constructed.
    """
    with pytest.raises(ValidationError, match="its tzinfo failed"):
        _Instant(when=datetime(2026, 1, 1, 9, tzinfo=_RaisingOffset()))


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


class _LyingConversion(datetime):
    """Aware and well-behaved, until it is asked to convert itself."""

    # Violating `astimezone`'s `Self` return is the whole point of this double:
    # it is the hostile subclass the validator must not trust.
    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1)  # noqa: DTZ001 — returning a naive value is the subject


class _NonUtcConversion(datetime):
    """Converts, but not to UTC."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))


class _MutableOffset(tzinfo):
    """Reports UTC when asked at validation time, and something else later."""

    shift = timedelta(0)

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return _MutableOffset.shift

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "mutable"


class _ZeroButNotUtcConversion(datetime):
    """Converts to a zero *offset* that is not the ``UTC`` object."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1, tzinfo=_MutableOffset())


class _NotADatetimeConversion(datetime):
    """Converts to something that merely *looks* like it carries a timezone."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return cast("datetime", SimpleNamespace(tzinfo=UTC))


class _NoneConversion(datetime):
    """Converts to nothing at all."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return cast("datetime", None)


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param(_LyingConversion(2026, 1, 2, tzinfo=UTC), id="returns-naive"),
        pytest.param(_NonUtcConversion(2026, 1, 2, tzinfo=UTC), id="returns-non-utc"),
        pytest.param(_ZeroButNotUtcConversion(2026, 1, 2, tzinfo=UTC), id="returns-zero-not-utc"),
        pytest.param(_NotADatetimeConversion(2026, 1, 2, tzinfo=UTC), id="returns-non-datetime"),
        pytest.param(_NoneConversion(2026, 1, 2, tzinfo=UTC), id="returns-none"),
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


class _UnreprableOffset(tzinfo):
    """A ``tzinfo`` that raises from ``utcoffset()`` *and* from ``__repr__``."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        msg = "no offset available"
        raise RuntimeError(msg)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "hostile"

    def __repr__(self) -> str:
        msg = "repr is hostile too"
        raise RuntimeError(msg)


def test_a_value_that_cannot_describe_itself_still_yields_a_validation_error() -> None:
    """The diagnostic must not be able to destroy the diagnosis.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so interpolating the offending
    value with ``!r`` lets a hostile ``tzinfo`` raise from *inside* the ``except``
    block that was reporting it — replacing the field-naming ``ValueError`` with
    whatever ``__repr__`` threw.
    """
    with pytest.raises(ValidationError, match="when must be timezone-aware"):
        _Instant(when=datetime(2026, 1, 1, tzinfo=_UnreprableOffset()))


class _ShiftySubclass(datetime):
    """Returns *itself* from ``astimezone``, and overrides ``utcoffset`` to lie."""

    lie = timedelta(0)

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return self

    def utcoffset(self) -> timedelta | None:
        return _ShiftySubclass.lie


class _FlipDuringComponentRead(datetime):
    """Flips its offset from inside ``__getattribute__``, as its digits are read."""

    lie = timedelta(0)

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return self

    def utcoffset(self) -> timedelta | None:
        return _FlipDuringComponentRead.lie

    def __getattribute__(self, name: str) -> object:
        if name == "year":
            _FlipDuringComponentRead.lie = timedelta(hours=2)
        return object.__getattribute__(self, name)


@pytest.mark.parametrize(
    "subclass",
    [
        pytest.param(_ShiftySubclass, id="flips-after-validation"),
        pytest.param(_FlipDuringComponentRead, id="flips-during-component-read"),
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


def test_a_plain_datetime_is_still_canonicalised_to_a_plain_datetime() -> None:
    """The path everything real takes: parsed input is always a base datetime."""
    stored = _Instant(when=datetime(2026, 1, 2, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))).when

    assert type(stored) is datetime
    assert stored == datetime(2026, 1, 2, 8, 0, tzinfo=UTC)


class _FlipOnConvert(datetime):
    """Flips its overridden offset *during* ``astimezone``, then returns itself."""

    lie = timedelta(0)

    def utcoffset(self) -> timedelta | None:
        return _FlipOnConvert.lie

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        _FlipOnConvert.lie = timedelta(hours=2)
        return self


def test_a_value_that_flips_its_offset_during_conversion_is_rejected() -> None:
    """Wall-clock digits denote an instant only together with an offset.

    This value passes the opening awareness check at zero, changes its offset
    while converting, and returns itself still carrying ``tzinfo is UTC``.
    Copying its components at that point would stamp ``09:00`` as ``09:00Z``
    when the value was, on its own account, ``07:00Z`` — so the offset is
    re-read at the moment of the copy, and this is refused instead.
    """
    _FlipOnConvert.lie = timedelta(0)
    try:
        with pytest.raises(ValidationError, match="when did not convert to UTC"):
            _Instant(when=_FlipOnConvert(2026, 1, 2, 9, 0, tzinfo=UTC))
    finally:
        _FlipOnConvert.lie = timedelta(0)


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
    _MutableOffset.shift = timedelta(0)
    try:
        with pytest.raises(ValidationError, match="when did not convert to UTC"):
            _Instant(when=_ZeroButNotUtcConversion(2026, 1, 2, tzinfo=UTC))
    finally:
        _MutableOffset.shift = timedelta(0)


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
