"""Tests for the context sources (the clock source and the internal seam)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_assistant.context import ClockContextSource, ContextSource
from ai_assistant.core.errors import ConfigurationError, ContextError
from ai_assistant.core.types import TimeOfDay

# 2026-01-01 is a Thursday; 01-03 a Saturday. Anchors for weekday/weekend checks.
_THU = datetime(2026, 1, 1, tzinfo=UTC)


def _at(hour: int) -> datetime:
    return _THU.replace(hour=hour)


def _clock(instant: datetime, **kwargs: object) -> ClockContextSource:
    return ClockContextSource(now=lambda: instant, **kwargs)  # type: ignore[arg-type]


def test_conforms_to_source_protocol() -> None:
    assert isinstance(ClockContextSource(), ContextSource)


async def test_contributes_the_temporal_fields() -> None:
    source = _clock(_at(14))  # Thursday 14:00 UTC

    contribution = await source.contribute()

    assert contribution == {
        "now": _at(14),
        "time_of_day": TimeOfDay.AFTERNOON,
        "is_weekend": False,
        "within_working_hours": True,  # default window 9-17
    }


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (5, TimeOfDay.MORNING),
        (8, TimeOfDay.MORNING),
        (12, TimeOfDay.AFTERNOON),
        (16, TimeOfDay.AFTERNOON),
        (17, TimeOfDay.EVENING),
        (20, TimeOfDay.EVENING),
        (21, TimeOfDay.NIGHT),
        (3, TimeOfDay.NIGHT),
    ],
)
async def test_time_of_day_buckets(hour: int, expected: TimeOfDay) -> None:
    contribution = await _clock(_at(hour)).contribute()
    assert contribution["time_of_day"] is expected


async def test_weekend_detection() -> None:
    saturday = datetime(2026, 1, 3, 10, tzinfo=UTC)
    assert (await _clock(saturday).contribute())["is_weekend"] is True
    assert (await _clock(_at(10)).contribute())["is_weekend"] is False  # Thursday


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(8, False), (9, True), (16, True), (17, False)],
)
async def test_within_working_hours_default_window(hour: int, *, expected: bool) -> None:
    contribution = await _clock(_at(hour)).contribute()
    assert contribution["within_working_hours"] is expected


async def test_custom_working_hours_window() -> None:
    contribution = await _clock(_at(20), working_hours_start=18, working_hours_end=22).contribute()
    assert contribution["within_working_hours"] is True


async def test_timezone_shifts_local_day_and_hour() -> None:
    # 02:00 UTC Saturday is 21:00 EST Friday — the local day and hour differ.
    instant = datetime(2026, 1, 3, 2, tzinfo=UTC)
    contribution = await _clock(instant, timezone="America/New_York").contribute()

    assert contribution["is_weekend"] is False  # Friday locally, not Saturday
    assert contribution["time_of_day"] is TimeOfDay.NIGHT  # 21:00 local
    assert contribution["now"] == instant  # the reference instant is unchanged


async def test_a_naive_clock_is_a_wiring_bug_not_an_attributed_instant() -> None:
    """Inverted by ADR-0026: this used to yield a UTC-attributed context.

    ``core`` no longer attributes an offset and neither does this source, so the
    naive reading is refused at the producer — loudly, naming the seam — rather
    than resolved silently in the fabricating direction (ADR-0023 §3).
    """
    source = ClockContextSource(now=lambda: datetime(2026, 1, 1, 14))  # noqa: DTZ001  naive
    with pytest.raises(ContextError, match="ClockContextSource"):
        await source.contribute()


def test_unknown_timezone_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="unknown timezone"):
        ClockContextSource(timezone="Mars/Olympus_Mons")


@pytest.mark.parametrize(
    ("start", "end"),
    [(17, 9), (9, 9), (0, 25), (-1, 8)],
)
def test_invalid_working_hours_window_raises(start: int, end: int) -> None:
    with pytest.raises(ConfigurationError, match="working-hours window"):
        ClockContextSource(working_hours_start=start, working_hours_end=end)
