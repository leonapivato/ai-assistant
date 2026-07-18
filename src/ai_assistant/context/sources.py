"""Context sources — the internal, composable seam of the context subsystem.

A ``ContextSource`` contributes part of the situational context. This seam is
**internal to `context/`** (ADR-0008 §2): it is not a cross-subsystem contract,
so its partial ``Mapping`` contributions never cross a boundary — only the
assembled :class:`~ai_assistant.core.types.CurrentContext` does.

``ClockContextSource`` is the one source today: it derives the temporal context
(time of day, weekend, working hours) from an injected clock and configured
locale.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ai_assistant.core.errors import ConfigurationError
from ai_assistant.core.types import TimeOfDay

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


def _utcnow() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class ContextSource(Protocol):
    """A single contributor to the situational context (internal to `context`)."""

    @property
    def name(self) -> str:
        """A stable identifier, used for collision reporting and logging."""
        ...

    async def contribute(self) -> Mapping[str, object]:
        """Return this source's partial set of ``CurrentContext`` fields."""
        ...


def _time_of_day(hour: int) -> TimeOfDay:
    """Bucket a local 24h ``hour`` into a coarse time of day."""
    if 5 <= hour < 12:  # noqa: PLR2004  boundary hours are self-evident
        return TimeOfDay.MORNING
    if 12 <= hour < 17:  # noqa: PLR2004
        return TimeOfDay.AFTERNOON
    if 17 <= hour < 21:  # noqa: PLR2004
        return TimeOfDay.EVENING
    return TimeOfDay.NIGHT


class ClockContextSource:
    """Contributes the temporal context from a clock and configured locale.

    Structurally implements :class:`ContextSource`. It performs no I/O, so it
    does not fail per request — the temporal core of the context is always
    available (ADR-0008 §4).
    """

    def __init__(
        self,
        *,
        timezone: str = "UTC",
        working_hours_start: int = 9,
        working_hours_end: int = 17,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        """Initialise the source, validating the locale at construction (startup).

        Args:
            timezone: IANA timezone name for local-time computation.
            working_hours_start: First hour of the working window (local, 0-23).
            working_hours_end: End hour of the working window (local, exclusive).
            now: Clock returning the reference instant; injectable for tests.

        Raises:
            ConfigurationError: If the timezone is unknown or the working-hours
                window is not a valid, non-empty range.
        """
        try:
            self._zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"unknown timezone {timezone!r}"
            raise ConfigurationError(msg) from exc
        if not 0 <= working_hours_start < working_hours_end <= 24:  # noqa: PLR2004
            msg = (
                f"invalid working-hours window: start={working_hours_start}, "
                f"end={working_hours_end} (require 0 <= start < end <= 24)"
            )
            raise ConfigurationError(msg)
        self._working_start = working_hours_start
        self._working_end = working_hours_end
        self._now = now

    @property
    def name(self) -> str:
        """This source's stable identifier."""
        return "clock"

    async def contribute(self) -> Mapping[str, object]:
        """Contribute ``now``, ``time_of_day``, ``is_weekend``, ``within_working_hours``."""
        instant = self._now()
        if instant.tzinfo is None:  # assume UTC for a naive clock, as elsewhere
            instant = instant.replace(tzinfo=UTC)
        local = instant.astimezone(self._zone)
        return {
            "now": instant,
            "time_of_day": _time_of_day(local.hour),
            "is_weekend": local.weekday() >= 5,  # noqa: PLR2004  Sat=5, Sun=6
            "within_working_hours": self._working_start <= local.hour < self._working_end,
        }
