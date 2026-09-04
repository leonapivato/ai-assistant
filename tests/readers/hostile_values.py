"""One hostile ``__repr__``, shared by the guard suites of both readers.

``readers/calendar.py`` and ``readers/email.py`` state the same discipline in
their guards' docstrings: a constructor guard reached by a value of *arbitrary*
type builds its refusal from ``type(value).__name__``, never ``repr``. The
refused object's own ``__repr__`` runs inside the message that refuses it, so a
hostile one raises straight past the guard — turning the wrong-exception-class
defect the guard exists to fix into a different one (#1978).

Four suites assert that across two readers and both kinds of guard — the
durations and the integers — so the probe lives here rather than being redefined
in each. A definition per suite is four chances for one of them to drift into a
class that no longer raises, and a probe that cannot fail is worse than no probe.

**The class name is load-bearing.** Every refusal these suites match on ends
``got Hostile``, and that tail is the whole assertion: it says the guard reported
the value's *type* and never asked the value about itself.
"""

from __future__ import annotations


class Hostile:
    """An object whose ``__repr__`` raises rather than answering."""

    def __repr__(self) -> str:
        raise RuntimeError("a hostile __repr__ must not raise past a guard")
