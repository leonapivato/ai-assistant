"""What a phases activation was given or obtained, and ADR-0204 §2's value over it.

ADR-0309 §5:10: "For an activation the phases plan, ADR-0204 §2's two terms are
evaluated over the memory records and context facets the activation was given or
obtained: its windows' records, what either recall run kept and what its calls
returned, digested ones included. On a pass whose output channel's audience is
unbounded the windows' records are left out, as ADR-0210 §1:1 leaves out the
conversation's own turns, and on any other pass nothing is left out (ADR-0210 §1:5).
The value is taken once, at capture, over every round, and written as ADR-0217 §3:12
writes it."

**A non-phase helper** (ADR-0309 §2:3). The phases' glue holds one
:class:`SuppliedRecords` in each activation's working set, hands it every record as the
activation is given or obtains it, round after round, and asks it for the value at the
freeze. No phase module imports it.

**One predicate** (ADR-0204 §2:7). The value is ADR-0199 §3's placement applied to
recorded origin, and nothing here decides it: a record counts where
:func:`~ai_assistant.orchestration.disclosure.admitted_to_understanding` would not admit
it to a channel of unbounded audience. That predicate refuses a record whose
``placement`` is already narrowed, so ADR-0204 §2's second term, a supplied record
already stamped, is answered by the same read as the first (ADR-0217 §1:3).

**Nothing is read but recorded origin, and nothing is fetched** (ADR-0204 §2:7-§2:8).
No ``content``, no rendered text, no goal, no plan; no ``MemoryStore``, no store
query of any kind. It is a predicate over records the
activation already holds, so a record the activation never held, such as one a memory
search named by id that was never fetched, is not among them.

**The two sets, and the audience that separates them** (ADR-0210 §1). The windows'
records are held apart from the rest. On a pass of unbounded audience they are left out
of the evaluation and set nothing; on a pass of bounded audience the evaluation ranges
over everything held. A record that both stands in a window and was obtained some other
way is held in both, and so counts on either pass, as ADR-0210 §1:2 counts a record both
the tail and a relevance read carry.

**Context facets** (ADR-0204 §2:2's first term). The phases give an activation no
context facets, so the value ranges over records alone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from ai_assistant.orchestration.disclosure import (
    UnboundedAudienceSupply,
    admitted_to_understanding,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.core.types import SuppliedRecord
    from ai_assistant.orchestration.disclosure import TurnSupply

__all__ = ["SuppliedRecords"]


@final
class SuppliedRecords:
    """Every memory record one activation was given or obtained.

    Held in the activation's working set for the whole pass and added to as each record
    arrives, so the value :meth:`withheld` takes at the freeze ranges over every round.
    A record handed in twice is held once.
    """

    def __init__(self) -> None:
        """Hold nothing yet."""
        # Keyed by the object, so a record handed in again each round is held once;
        # two versions of one stored record are two objects and both count.
        self._windows: dict[int, SuppliedRecord] = {}
        self._obtained: dict[int, SuppliedRecord] = {}

    def windows(self, records: Iterable[SuppliedRecord]) -> None:
        """Hold the records of the activation's windows (ADR-0276 §3-§4).

        Args:
            records: The stored records a window gave the activation.
        """
        self._windows.update((id(one), one) for one in records)

    def obtained(self, records: Iterable[SuppliedRecord]) -> None:
        """Hold records the activation obtained other than through its windows.

        What either recall run kept, what a call returned, a digest's records included,
        and what a story view showed.

        Args:
            records: The records, as the activation held them.
        """
        self._obtained.update((id(one), one) for one in records)

    def withheld(self, audience: TurnSupply) -> bool:
        """ADR-0204 §2's disjunction over what is held, as ADR-0309 §5:10 sets it.

        Args:
            audience: The pass's audience posture. On an unbounded one the windows'
                records are left out (ADR-0210 §1:1); on a bounded one nothing is
                (§1:5). It decides only the set: the predicate is the same on both.

        Returns:
            Whether any record held is one a channel of unbounded audience withholds, a
            record already placed for the owner alone included.
        """
        records = list(self._obtained.values())
        if not isinstance(audience, UnboundedAudienceSupply):
            records.extend(self._windows.values())
        sources = audience.speakable_attested_sources
        unbounded = UnboundedAudienceSupply(speakable_attested_sources=sources)
        return len(admitted_to_understanding(unbounded, records)) < len(records)
