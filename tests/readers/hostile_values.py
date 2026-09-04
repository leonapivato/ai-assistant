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

Four suites assert this across two readers and both kinds of guard — the
durations and the integers — so the probes live here rather than being redefined
in each. A definition per suite is four chances for one of them to drift into a
class that no longer raises, and a probe that cannot fail is worse than no probe.

**:class:`Hostile`'s name is load-bearing.** Every refusal the duration suites
match on ends ``got Hostile``, and that tail is the whole assertion: it says the
guard reported the value's *type* and never asked the value about itself.
"""

from __future__ import annotations

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
