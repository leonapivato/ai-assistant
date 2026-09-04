"""The hostile values both readers' guard suites refuse, defined once.

``readers/calendar.py`` and ``readers/email.py`` state the same discipline in
their guards' docstrings: a constructor guard reached by a value of *arbitrary*
type builds its refusal from the value's type name, never from ``repr``. The
refused object's own ``__repr__`` runs inside the message that refuses it, so a
hostile one raises straight past the guard — turning the wrong-exception-class
defect the guard exists to fix into a different one (#1978).

Reaching for the type name is then the same problem one level in, so the probes
here come in both shapes: an object that will not render itself, and a type that
will not say what it is called.

A guard's *accepted* type is the third shape, and it is why :class:`HostilePath`
and :class:`HostileZone` are here too. Proving ``isinstance`` proves nothing about
a subclass's overrides, so a message rendered below the type test still asks the
refused value about itself — and an overridden predicate answers the guard's own
question with whatever the subclass prefers. The readers answer that by rebuilding
the accepted value into a built-in, which is #1979's answer for the durations at
the other guards (#2101, #2104).

The suites assert this across two readers and every kind of guard — the paths, the
zone, the durations and the integers — so the probes live here rather than being
redefined in each. A definition per suite is one more chance for one of them to
drift into a class that no longer raises, and a probe that cannot fail is worse
than no probe.

**:class:`Hostile`'s name is load-bearing.** Every refusal the duration suites
match on ends ``got Hostile``, and that tail is the whole assertion: it says the
guard reported the value's *type* and never asked the value about itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class Hostile:
    """An object whose ``__repr__`` raises rather than answering."""

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __repr__ must not raise past a guard")


class Unnameable(type):
    """A metaclass whose ``__name__`` raises when a guard reaches for it.

    The half of #1978 that survives substituting ``repr``: a refusal that names
    ``type(value).__name__`` still calls into the refused object's class, so a
    guard that distrusts the value and trusts its type has moved the escape
    rather than closed it. Built as a metaclass rather than as a plain class
    because ``__name__`` is read on the *type*.
    """

    def __getattribute__(cls, name: str) -> object:
        if name == "__name__":
            raise RuntimeError("a hostile __name__ must not raise past a guard")
        return super().__getattribute__(name)


class NumericName(type):
    """A metaclass answering ``__name__`` with something that is not a ``str``."""

    @property
    def __name__(cls) -> Any:  # type: ignore[override]  # the hostile case, on purpose
        return 42


class HostilePath(Path):
    """A ``Path`` subclass that lies about its shape and will not render itself.

    ``isinstance(value, Path)`` proves the type and nothing about the overrides,
    so both halves of a path guard are still reachable through one: the predicate
    it asks — ``is_absolute`` — is answered by the subclass, and the message that
    would report the answer asks the value to render itself.

    The three renderings are overridden together because a guard has three ways to
    reach for one: ``str(value)``, ``os.fspath(value)`` and ``repr(value)``. Any
    that is left honest would let a guard pass this probe by taking a different
    route to the same defect.
    """

    def is_absolute(self) -> bool:
        """``True``, whatever the location actually is."""
        return True

    def __str__(self) -> str:
        raise RuntimeError("a hostile __str__ must not raise past a guard")

    def __fspath__(self) -> str:
        raise RuntimeError("a hostile __fspath__ must not raise past a guard")

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __repr__ must not raise past a guard")


class HostileZone(str):
    """A ``str`` subclass whose renderings raise rather than answering.

    :class:`HostilePath`'s shape at the zone guard: ``isinstance(value, str)``
    admits it, and the refusal below — which reports a zone the platform does not
    know — renders the value it was handed.
    """

    def __str__(self) -> str:
        raise RuntimeError("a hostile __str__ must not raise past a guard")

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __repr__ must not raise past a guard")
