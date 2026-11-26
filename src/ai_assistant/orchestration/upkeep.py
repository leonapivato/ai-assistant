"""The domains the upkeep jobs tend, and the budget one firing of a row shares (ADR-0384).

ADR-0384 covers three upkeep jobs (§2:1): the scheduled story tidy-up, the matters pass
and the notification reconsideration. Each run of one **tends one domain** (§3:1, §5:1):
it is handed that domain, a :class:`~ai_assistant.core.types.RecordHome` set here by
code and never by a model, and writes only there (§4). This module holds the two facts
the jobs share, so neither job keeps its own copy of them.

**Which domains** (§1:3). A hub with one person has two: the owner's domain and the
hub's shared things. :data:`UPKEEP_DOMAINS` is both, in the order one firing of a row
tends them: the owner's first, since it holds nearly every record, so a run of the
shared things that finds nothing due takes nothing from it. The reconsideration tends
the owner's domain alone (:data:`RECONSIDERED`, §3:4): a held notification of another
domain is left to the decision that rules whom it goes to.

**One budget to a firing** (§10 leaves the share to the build). A row's firing runs the
job once for each domain, and the runs share one ``scheduler_run_budget``
(:class:`FiringBudget`), so the firing holds the scheduler's serial loop no longer than
one run did before. The budget starts once a run of the firing has found something to
do, never before, so a run that finds nothing due makes no model call and spends none
of it. Each run's bound on what it starts is its own, as ADR-0358 §4:3 and ADR-0302 §5
bound "one run", and each run always starts its first due item, as one run always has,
so a domain whose run comes second is never starved by the first. A firing therefore
overruns its budget by at most one item's work for each domain.

**Tending a domain makes no job a work** (§3:3). Nothing here records a fact of
ADR-0368 §2, starts an activation, records an episode or makes a call the check runs:
it names domains and measures time, and each job stays what its own decisions make it.

**What the runs read is unchanged** (§1:2). A run's write half takes effect now that
records carry their domain; its reads go through the filter once ADR-0369 §10's filter
decides reads, and until then each job reads its stores as before.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import RecordHome

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

__all__ = ["RECONSIDERED", "UPKEEP_DOMAINS", "FiringBudget"]

#: The two domains of a hub with one person (ADR-0384 §1:3), in the order one firing of
#: the scheduled tidy-up's row and of the matters pass's row tends them (§5:1, §10).
UPKEEP_DOMAINS: Final[tuple[RecordHome, ...]] = (RecordHome.owners(), RecordHome.shared())

#: The one domain the notification reconsideration tends (ADR-0384 §3:4): the owner's.
RECONSIDERED: Final = RecordHome.owners()


class FiringBudget:
    """One ``scheduler_run_budget`` shared by the runs of one firing of a row.

    It starts the first time a run of the firing says it has found something to do,
    and is spent once that much time has passed since. A firing whose runs find
    nothing never starts it.
    """

    __slots__ = ("_budget", "_clock", "_deadline")

    def __init__(self, budget: timedelta, *, clock: Callable[[], float] | None = None) -> None:
        """Hold the firing's budget, not yet started.

        Args:
            budget: How long the firing's runs may spend, together, once one of them
                has found something to do.
            clock: A monotonic clock in seconds; the running event loop's when
                ``None``, as each job's run measured its budget before.
        """
        self._budget = budget
        self._clock = clock
        self._deadline: float | None = None

    def _time(self) -> float:
        return asyncio.get_running_loop().time() if self._clock is None else self._clock()

    def start(self) -> None:
        """Start the budget, unless a run of this firing already started it."""
        if self._deadline is None:
            self._deadline = self._time() + self._budget.total_seconds()

    def spent(self) -> bool:
        """Whether the budget has started and its time has passed."""
        return self._deadline is not None and self._time() >= self._deadline
