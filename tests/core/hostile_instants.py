"""One adversarial table, asserted against **both** validating instant seams.

ADR-0030 §4 makes this a required artifact, not a convenience: `core` has one
canonicaliser, reached by ``UtcInstant``'s field validator
(``tests/core/test_utc_instant.py``) and by ``checked_clock``
(``tests/core/test_clock.py``). A rule in two places with two test suites is two
rules waiting to diverge — the condition issues #174 and #152 exist to prevent —
so the hostile values live here and both suites parametrize over the same list.
A change to one seam that the other does not follow fails the gate.

Every entry is a *value*, plus what the seams must do with it. The doubles carry
class-level mutable state (that is how several of them lie), so each entry knows
how to reset itself and how to build a fresh instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable


class NoOffset(tzinfo):
    """Set, but indeterminate — issue #36's case. Not aware, by ADR-0023 §5."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "indeterminate"


class RaisingOffset(tzinfo):
    """A ``tzinfo`` whose ``utcoffset()`` raises rather than answering."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        msg = "no offset available"
        raise RuntimeError(msg)

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "raises"


class UnreprableOffset(RaisingOffset):
    """Raises from ``utcoffset()`` *and* from ``__repr__``.

    ``datetime.__repr__`` embeds ``repr(tzinfo)``, so building the message that
    reports this value is itself a call into hostile code. The diagnostic must
    not be able to destroy the diagnosis.
    """

    def tzname(self, dt: datetime | None) -> str | None:
        return "hostile"

    def __repr__(self) -> str:
        msg = "repr is hostile too"
        raise RuntimeError(msg)


class MutableOffset(tzinfo):
    """Reports UTC when asked at validation time, and something else later."""

    shift = timedelta(0)

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return MutableOffset.shift

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "mutable"


# Violating `astimezone`'s `Self` return is the whole point of these doubles:
# they are the hostile subclasses a seam must not trust.
class LyingConversion(datetime):
    """Aware and well-behaved, until it is asked to convert itself."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1)  # noqa: DTZ001 — returning a naive value is the subject


class NonUtcConversion(datetime):
    """Converts, but not to UTC."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))


class ZeroButNotUtcConversion(datetime):
    """Converts to a zero *offset* that is not the ``UTC`` object."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return datetime(2026, 1, 1, tzinfo=MutableOffset())


class NotADatetimeConversion(datetime):
    """Converts to something that merely *looks* like it carries a timezone."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return cast("datetime", SimpleNamespace(tzinfo=UTC))


class NoneConversion(datetime):
    """Converts to nothing at all."""

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return cast("datetime", None)


class ShiftySubclass(datetime):
    """Returns *itself* from ``astimezone``, and overrides ``utcoffset`` to lie."""

    lie = timedelta(0)

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return self

    def utcoffset(self) -> timedelta | None:
        return ShiftySubclass.lie


class FlipDuringComponentRead(datetime):
    """Flips its offset from inside ``__getattribute__``, as its digits are read."""

    lie = timedelta(0)

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return self

    def utcoffset(self) -> timedelta | None:
        return FlipDuringComponentRead.lie

    def __getattribute__(self, name: str) -> object:
        if name == "year":
            FlipDuringComponentRead.lie = timedelta(hours=2)
        return object.__getattribute__(self, name)


class FlipOnConvert(datetime):
    """Flips its overridden offset *during* ``astimezone``, then returns itself."""

    lie = timedelta(0)

    def utcoffset(self) -> timedelta | None:
        return FlipOnConvert.lie

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        FlipOnConvert.lie = timedelta(hours=2)
        return self


class WellBehavedSubclass(datetime):
    """Adds nothing and lies about nothing — and is refused all the same."""


class BaseDatetimeConversion(datetime):
    """Converts to an exact base ``datetime`` in UTC, unlike every subclass above."""

    converted = datetime(1970, 1, 1, tzinfo=UTC)

    def astimezone(self, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return BaseDatetimeConversion.converted


def _reset_shifty() -> None:
    ShiftySubclass.lie = timedelta(0)


def _reset_flip_read() -> None:
    FlipDuringComponentRead.lie = timedelta(0)


def _reset_flip_convert() -> None:
    FlipOnConvert.lie = timedelta(0)


def _reset_mutable() -> None:
    MutableOffset.shift = timedelta(0)


def _noop() -> None:
    """Nothing to reset: this entry's double carries no mutable state."""


@dataclass(frozen=True)
class HostileInstant:
    """One adversarial value and what both seams must do with it.

    Attributes:
        label: The pytest id, so a failure names the case rather than a number.
        make: Builds a fresh instance — several doubles are stateful, so a shared
            instance would carry one test's mutation into the next.
        reset: Restores the double's class-level state, run before *and* after.
        accepted: Whether the seam must accept the value. Exactly one entry is
            accepted, and it is the one that separates ADR-0030 §1's output-side
            rule from an input-side "refuse every subclass" test — which would
            satisfy every other entry while contradicting the decision.
        canonical: What an accepted value must canonicalise to.
    """

    label: str
    make: Callable[[], datetime]
    reset: Callable[[], None] = _noop
    accepted: bool = False
    canonical: datetime | None = None


#: The table. Every seam that canonicalises an instant asserts against all of it.
HOSTILE_INSTANTS = [
    HostileInstant(
        "naive",
        lambda: datetime(2026, 1, 2, 9),  # noqa: DTZ001 — the naive value is the subject
    ),
    HostileInstant("indeterminate-tzinfo", lambda: datetime(2026, 1, 2, 9, tzinfo=NoOffset())),
    HostileInstant("raising-tzinfo", lambda: datetime(2026, 1, 2, 9, tzinfo=RaisingOffset())),
    HostileInstant("unreprable-tzinfo", lambda: datetime(2026, 1, 2, 9, tzinfo=UnreprableOffset())),
    HostileInstant("conversion-returns-naive", lambda: LyingConversion(2026, 1, 2, tzinfo=UTC)),
    HostileInstant("conversion-returns-non-utc", lambda: NonUtcConversion(2026, 1, 2, tzinfo=UTC)),
    HostileInstant(
        "conversion-returns-zero-not-utc",
        lambda: ZeroButNotUtcConversion(2026, 1, 2, tzinfo=UTC),
        _reset_mutable,
    ),
    HostileInstant(
        "conversion-returns-non-datetime",
        lambda: NotADatetimeConversion(2026, 1, 2, tzinfo=UTC),
    ),
    HostileInstant("conversion-returns-none", lambda: NoneConversion(2026, 1, 2, tzinfo=UTC)),
    HostileInstant(
        "subclass-preserving-its-type",
        lambda: ShiftySubclass(2026, 1, 2, 9, tzinfo=UTC),
        _reset_shifty,
    ),
    HostileInstant(
        "flips-during-component-read",
        lambda: FlipDuringComponentRead(2026, 1, 2, 9, tzinfo=UTC),
        _reset_flip_read,
    ),
    HostileInstant(
        "flips-its-offset-during-conversion",
        lambda: FlipOnConvert(2026, 1, 2, 9, tzinfo=UTC),
        _reset_flip_convert,
    ),
    HostileInstant("well-behaved-subclass", lambda: WellBehavedSubclass(2026, 1, 2, 9, tzinfo=UTC)),
    HostileInstant(
        "subclass-converting-to-a-base-datetime",
        lambda: BaseDatetimeConversion(2026, 7, 21, 12, tzinfo=UTC),
        accepted=True,
        canonical=BaseDatetimeConversion.converted,
    ),
]

#: pytest ``ids`` for :data:`HOSTILE_INSTANTS`, so both suites label them alike.
HOSTILE_IDS = [case.label for case in HOSTILE_INSTANTS]
