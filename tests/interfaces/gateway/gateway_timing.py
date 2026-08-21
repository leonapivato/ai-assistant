"""The clock and the timer the gateway is built with, driven by hand.

A plain module rather than a ``conftest.py``, because ``mypy`` refuses a second
module of that name where the test tree carries no packages — and a fixture is
not what these want anyway: each is one line to construct and reads better beside
the subject it drives.

ADR-0168 §4 requires expired sessions "destroyed continuously rather than at a
checkpoint or on the next request that happens to arrive", and §6's refusal
records are collapsed over a `gateway_record_interval`. Both are therefore
*scheduled* acts, and a test that waited them out would wait twelve hours for one
of them. Everything the gateway defers goes through :class:`Timers`, so a test
fires it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class Clock:
    """A wall clock a test moves."""

    reading: datetime = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        """The current reading."""
        return self.reading

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward."""
        self.reading += delta


@dataclass
class Timer:
    """One scheduled callback, and whether it is still armed."""

    delay: float
    callback: Callable[[], None]
    cancelled: bool = False

    def cancel(self) -> None:
        """Call it off."""
        self.cancelled = True


@dataclass
class Timers:
    """Every callback the gateway deferred, in the order it deferred them."""

    scheduled: list[Timer] = field(default_factory=list)

    def __call__(self, delay: float, callback: Callable[[], None]) -> Timer:
        """Take one deferred callback."""
        timer = Timer(delay=delay, callback=callback)
        self.scheduled.append(timer)
        return timer

    @property
    def armed(self) -> list[Timer]:
        """The timers that have neither fired nor been cancelled."""
        return [timer for timer in self.scheduled if not timer.cancelled]

    def fire_all(self) -> None:
        """Fire every armed timer, oldest first.

        Firing marks the timer spent, so a callback that re-arms the same subject
        (a session touched, an interval reopened) does not fire twice in one pass.
        """
        for timer in list(self.armed):
            timer.cancelled = True
            timer.callback()
