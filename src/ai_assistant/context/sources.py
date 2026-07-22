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

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import ConfigurationError, ContextError
from ai_assistant.core.types import TimeOfDay

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.clock import Clock


def _utcnow() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class ContextSource(Protocol):
    """A single contributor to the situational context (internal to `context`).

    A source may additionally carry a ``required`` attribute. It is deliberately
    **not** declared here (ADR-0026 §4): a ``Protocol`` member is mandatory for
    structural conformance and supplies no default, so declaring it would make
    every existing source non-conforming and a bare ``source.required`` would
    raise ``AttributeError`` inside the very degradation path it selects. The
    assembler reads it as ``getattr(source, "required", False)``; absent means
    optional, which is both the safe default and the one that keeps this seam
    additive.
    """

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

    Structurally implements :class:`ContextSource`. It performs no I/O, so a
    *conforming* clock cannot fail per request and the temporal core of the
    context is always available (ADR-0008 §4, as amended by ADR-0026 §6). A
    reading that is naive, indeterminate or outside the localizable range is a
    wiring bug, not degradation: it raises ``ContextError`` and, because this
    source is :attr:`required`, that failure reaches the caller rather than
    leaving the facet absent.
    """

    def __init__(
        self,
        *,
        timezone: str = "UTC",
        working_hours_start: int = 9,
        working_hours_end: int = 17,
        now: Clock = _utcnow,
    ) -> None:
        """Initialise the source, validating the locale at construction (startup).

        Args:
            timezone: IANA timezone name for local-time computation.
            working_hours_start: First hour of the working window (local, 0-23).
            working_hours_end: End hour of the working window (local, exclusive).
            now: Clock returning the reference instant; injectable for tests.
                Guarded by :func:`~ai_assistant.core.clock.checked_clock`, so a
                naive, indeterminate or unlocalizable reading is a wiring bug
                rather than a fabricated UTC instant (ADR-0026 §2).

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
        self._now = checked_clock(now, owner="ClockContextSource")

    @property
    def name(self) -> str:
        """This source's stable identifier."""
        return "clock"

    @property
    def required(self) -> bool:
        """Always ``True``: the temporal core cannot be degraded away.

        ADR-0008 §4 skips a failing *optional* source and leaves its facet
        ``None``. ``now`` has no ``None`` to fall back to — ``CurrentContext``
        could not be constructed without it — so a broken clock here is a wiring
        bug that must reach the caller with its cause intact, not a facet that
        quietly goes absent (ADR-0026 §4). Read by
        :class:`~ai_assistant.context.provider.AssemblingContextProvider` as
        ``getattr(source, "required", False)``; every other source omits it and
        is therefore optional.
        """
        return True

    async def contribute(self) -> Mapping[str, object]:
        """Contribute ``now``, ``time_of_day``, ``is_weekend``, ``within_working_hours``.

        Raises:
            ContextError: If the injected clock's reading is not a conforming
                one — naive, indeterminate, or outside the localizable range.
                ``core`` raises ``ValueError``; translating it here is `context`
                declaring its own boundary error for a wiring bug (ADR-0026 §4).
                It is *not* degradation: see :attr:`required`.
        """
        try:
            instant = self._now()
        except ClockReadingError as exc:
            raise ContextError(str(exc)) from exc
        local = instant.astimezone(self._zone)
        return {
            "now": instant,
            "time_of_day": _time_of_day(local.hour),
            "is_weekend": local.weekday() >= 5,  # noqa: PLR2004  Sat=5, Sun=6
            "within_working_hours": self._working_start <= local.hour < self._working_end,
        }
