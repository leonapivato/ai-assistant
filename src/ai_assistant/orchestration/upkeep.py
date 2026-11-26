"""The domains the upkeep jobs tend, each run's sight, and a firing's budget (ADR-0384).

ADR-0384 covers three upkeep jobs (§2:1): the scheduled story tidy-up, the matters pass
and the notification reconsideration. Each run of one **tends one domain** (§3:1, §5:1):
it is handed that domain, a :class:`~ai_assistant.core.types.RecordHome` set here by
code and never by a model, and writes only there (§4). This module holds the facts the
jobs share, so no job keeps its own copy of them.

**Which domains** (§1:3). A hub with one person has two: the owner's domain and the
hub's shared things. :data:`UPKEEP_DOMAINS` is both, in the order one firing of a row
tends them: the owner's first, since it holds nearly every record, so a run of the
shared things that finds nothing due takes nothing from it. The reconsideration tends
the owner's domain alone (:data:`RECONSIDERED`, §3:4): a held notification of another
domain is left to the decision that rules whom it goes to. The observer's pin pass, a
run since ADR-0388 §4:1, tends each person domain, never the shared things (§4:3): a pin
is a person's on their own profile (:data:`PERSON_DOMAINS`, the owner's alone). Each is a
constant: no read decides which domains a firing tends.

**A run's sight** (ADR-0383 §6:8, §7:7). Every read a run makes, its finding of what is
due included, is of a store bound to one sight (ADR-0384 §7:1), and :func:`upkeep_run` is
the one place a run's sight is made: once for the run, by code, from the domain it is
handed, :meth:`~ai_assistant.core.types.Sight.of_run` (a one-domain bound for the domain
and a person bound for its person, the owner for the shared things). Each job asks for its
run here, binds its stores to the run's sight through
:class:`~ai_assistant.orchestration.bound_stores.BoundStores`, and neither makes nor
changes a sight (§9:2). So do the two runs ADR-0388 adds, the observer's pin pass (§4) and
the upcoming-event producer's (§7), which are no upkeep jobs of ADR-0384 §2's table: each
asks here for the run of the domain it tends, as ADR-0388 §9 puts their sights where every
run's is.

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
it names domains, makes a run's sight and measures time, and each job stays what its
own decisions make it.

**What a run reads.** Through its bound stores, which in a build whose stores withhold
give back only records of the domain it tends, and in the counting build answer as the
unbound stores do and write one count event each, its reader ``run`` (ADR-0383 §7:10,
§11:1). The checks each job keeps on what it writes, that a record it changes or names is
of its domain (§4:2), take effect in both builds (ADR-0383 §11:4).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import RecordHome, Sight

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

__all__ = [
    "PERSON_DOMAINS",
    "RECONSIDERED",
    "UPKEEP_DOMAINS",
    "FiringBudget",
    "UpkeepRun",
    "upkeep_run",
]

#: The two domains of a hub with one person (ADR-0384 §1:3), in the order one firing of
#: the scheduled tidy-up's row and of the matters pass's row tends them (§5:1, §10).
UPKEEP_DOMAINS: Final[tuple[RecordHome, ...]] = (RecordHome.owners(), RecordHome.shared())

#: The one domain the notification reconsideration tends (ADR-0384 §3:4): the owner's.
RECONSIDERED: Final = RecordHome.owners()

#: The person domains ADR-0384 §1:3 rules, each of which the observer's pin pass is run
#: once for (ADR-0388 §4:1): the owner's alone. Never the shared things (§4:3).
PERSON_DOMAINS: Final[tuple[RecordHome, ...]] = (RecordHome.owners(),)


@dataclass(frozen=True, slots=True)
class UpkeepRun:
    """One run of an upkeep job: the domain it tends and the sight it reads by.

    Attributes:
        tends: The domain the run tends, where everything it writes lands (ADR-0384 §4).
        sight: The run's sight (ADR-0383 §6:8), made from ``tends`` by
            :func:`upkeep_run` alone; every store the run reads or writes is bound to it.
    """

    tends: RecordHome
    sight: Sight


def upkeep_run(domain: RecordHome) -> UpkeepRun:
    """A run tending ``domain``, with its sight: the one place a run's is made (§6:8).

    :meth:`~ai_assistant.core.types.Sight.of_run`, by code from the domain the run is
    handed and from nothing a store holds, once for the run (ADR-0383 §6:10, §9:2).

    Args:
        domain: The domain the run tends: the owner's or the hub's shared things.

    Returns:
        The run.

    Raises:
        ValueError: If ``domain`` is a group's, which no run tends (ADR-0384 §1:3).
    """
    return UpkeepRun(tends=domain, sight=Sight.of_run(domain))


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
