"""The clock a benchmark run happens on: the corpus's time, not the wall's.

**A long-term-memory benchmark measured against the wall clock measures the wrong
thing.** LoCoMo's ten dialogues span more than a year; LongMemEval's haystacks span
months and then ask "which did I do first?" and "how long after X?". Capturing every
one of those turns at ``datetime.now()`` collapses that span to an instant, and the
axis #1029's P2 is entirely about stops existing before a single question is asked.
Worse, it is silent: nothing fails, the scores simply come out of a system that was
shown a history it never had.

So the harness runs on a clock it moves: set to a session's stated instant while that
session is captured and distilled, and to the question's stated instant while it is
answered. Every seam that takes an injectable clock is given this one — capture,
the memory store's liveness axes, the ingestor, and the observer — so a run has one
notion of "now" rather than four.

**Two clocks stay on the wall, deliberately.** ``SqliteMemoryStore``'s ``traces_now``
is separate from its ``now`` for a reason ADR-0119 §5 states — a trace must not change
the read it observes — and a trace stream ordered by a clock that jumps backwards
between cases would be unreadable. And nothing here touches the trace store's own
insertion order, which is what a walk is ordered by.

**What this does not do is make a run reproducible.** The clock is deterministic; the
model is not. Reproducibility of the *selection* is what the corpus pins and the slice
seed buy; reproducibility of the answers is not something a benchmark of a language
model gets.
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["BenchmarkClock"]


class BenchmarkClock:
    """A clock whose reading the harness sets.

    Satisfies ``ai_assistant.core.clock.Clock`` structurally — a zero-argument
    callable returning a timezone-aware instant — so it goes anywhere the product
    accepts an injected clock.
    """

    def __init__(self, *, start: datetime | None = None) -> None:
        """Create a clock reading ``start``.

        Args:
            start: The initial instant. Defaults to the epoch in UTC rather than to
                the wall clock, so a harness that forgets to set it produces obviously
                wrong timestamps instead of plausible ones.

        Raises:
            ValueError: If ``start`` is naive or carries an indeterminate offset. The
                product's own ``checked_clock`` refuses those at every seam this clock
                is injected into; refusing here means the message names this class.
        """
        self._instant = start if start is not None else datetime(1970, 1, 1, tzinfo=UTC)
        self._check(self._instant)

    def __call__(self) -> datetime:
        """The current reading.

        Returns:
            The instant this clock was last set to.
        """
        return self._instant

    def set(self, instant: datetime) -> None:
        """Move the clock to ``instant``.

        **Moving backwards is permitted**, because a run does it legitimately: each
        case starts a fresh store and a fresh history, so case *n+1*'s first session
        can precede case *n*'s last. Only a monotonicity claim would be violated, and
        nothing here makes one — durations are measured with ``perf_counter`` inside
        the product, never by differencing this.

        Args:
            instant: Where to move to. Timezone-aware, with a determinate offset.

        Raises:
            ValueError: If ``instant`` is naive or its offset is indeterminate.
        """
        self._check(instant)
        self._instant = instant

    @staticmethod
    def _check(instant: datetime) -> None:
        """Refuse an instant the product's clock guard would refuse.

        Args:
            instant: The candidate.

        Raises:
            ValueError: If it is naive, or its offset cannot be determined.
        """
        if instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
            msg = f"a benchmark clock needs a timezone-aware instant, got {instant!r}"
            raise ValueError(msg)
