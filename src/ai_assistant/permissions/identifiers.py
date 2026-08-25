"""Identifiers for the trail's invocation rows, and what makes one unambiguous.

ADR-0192 §2 has the ledger mint each row's ``id`` from an **injected factory**
rather than take one from a caller. That answers three questions at once. A
``PermissionDecision.id`` has to exist before the write, because it is the name
the rest of the system already knows a ruling by — a step's ``approval_ref``, a
``ToolCall``'s decision, an invocation row's ``decision_id``. An invocation row's
id names nothing outside the store: it is minted at the append, learned from the
returned row, and used once, to point a completion at its claim. Neither
``ToolCall`` nor the seam has an id source; deriving one from ``decision_id``
collides across the two rows of one attempt and again across a retry; and
inventing one inline would put unseeded randomness on the write path, which
``CONTRIBUTING.md`` forbids.

**The obligation is the process, and never the instance.** A factory returns no
value it has already returned, or has been given to *reserve*, for the life of the
process it runs in — because a completion names its claim by ``id`` alone, so an id
reissued after the row it first named was erased would let a completion held by one
call land on a **different** call's claim and be recorded as that call's outcome
and cost. Nothing makes a factory unreplaceable and ADR-0192 §3 adds no lifecycle
obligation to ``ToolInvoker``, so a second instance can be constructed while an
``invoke`` call still holds a claim's id; under instance scope that second instance
may legally reissue it once ``clear()`` has erased the row, and the ledger's redraw
**cannot see it** — the store holds no row under that id, so there is nothing to
draw away from. The state below therefore lives on the *space*, one per process,
and every factory over a store shares it.

**And it is fork-safe, which a nonce and a counter alone are not.** ADR-0049 §3
solved this hazard for ``execution_id`` and its answer is taken unchanged: the
current process id is read **at allocation time** and folded in, never frozen at
construction, because "a nonce frozen at construction is copied by ``fork``".
Without it the parent claims an id, ``clear()`` erases the row, and the child's
copied nonce and counter mint the same value — the failure this module exists to
prevent, arriving through the one door the redraw cannot see.

**Satisfied by construction and never by improbability.** ADR-0045 §4 already
rules on the shape a bare ``uuid4`` draw takes here — it "makes a collision
unlikely, not impossible" — and this is not a property an unlikely failure is
acceptable in, because the collision it prevents records one call's outcome and
cost against another call's claim, silently.

**What is remembered is an identifier, not an act** (ADR-0192 §6). The space holds
no row, no decision, no outcome and no count of executions a user erased; it is
consulted at no admission, so a decision re-recorded after ``clear()`` still admits
a claim; and it dies with the process, which a generation or a high-water mark
would have had to outlive in order to do the job §6 refuses to give it.
"""

from __future__ import annotations

import itertools
import os
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


@runtime_checkable
class IdentifierFactory(Protocol):
    """What the ledger mints row ids from (ADR-0192 §2).

    Deliberately **not** a Protocol in ``core/protocols.py``: the factory,
    ``open_invocations`` and ``complete_invocation`` are all ``permissions/``, so
    no id crosses a subsystem boundary to be reserved and no consumer is handed a
    reservation call. A structural type here is what lets a test inject a
    non-conforming collaborator and pin what the ledger does with it.
    """

    def __call__(self) -> str:
        """Return an identifier this process has neither issued nor reserved."""
        ...

    def reserve(self, ids: Iterable[str]) -> None:
        """Promise that none of ``ids`` will be returned by any later call."""
        ...


class IdentifierSpace:
    """The per-process state a conforming factory draws from.

    Held apart from the factory so that two factories constructed in one process —
    which nothing prevents — draw from **one** sequence and share **one**
    reservation set. A factory whose issued ids are process-global but whose
    reservations are instance-local still reissues: instance A reserves the
    persisted claim ``x``, ``clear()`` erases it, and instance B mints it.
    """

    def __init__(self, *, nonce: str | None = None) -> None:
        """Open a fresh space.

        Args:
            nonce: The per-space component, drawn once. Injectable **so a test can
                pin the sequence rather than race it**; production takes the
                default. It is not what makes the space fork-safe — the pid folded
                in at allocation is — which is exactly why a test may fix it.
        """
        self._nonce: Final = nonce if nonce is not None else uuid4().hex
        self._counter: Iterator[int] = itertools.count()
        self._reserved: set[str] = set()

    def mint(self) -> str:
        """Return the next identifier this space has neither issued nor reserved."""
        while True:
            # `os.getpid()` is read here and not in `__init__`: a child of a
            # `fork` inherits the nonce and the counter, and the pid is the only
            # component that can differ (ADR-0049 §3).
            candidate = f"inv-{os.getpid()}-{self._nonce}-{next(self._counter)}"
            if candidate not in self._reserved:
                return candidate

    def reserve(self, ids: Iterable[str]) -> None:
        """Take ``ids`` out of this space for the life of the process."""
        self._reserved.update(ids)


#: The one space a process draws from unless a caller says otherwise. Built at
#: import, so every store opened in one process shares it and two ledgers over one
#: store never mint from independent sequences (ADR-0192 §2).
PROCESS_SPACE: Final = IdentifierSpace()


class ProcessIdentifiers:
    """A conforming :class:`IdentifierFactory` over an :class:`IdentifierSpace`.

    Constructed with no arguments by the composition root, so two of them in one
    process share :data:`PROCESS_SPACE` and every id either returns differs from
    every id the other returned.
    """

    def __init__(self, *, space: IdentifierSpace | None = None) -> None:
        """Draw from ``space``, or from the process's own.

        Args:
            space: The state to draw from. Injectable so a suite can pin a
                sequence; production never passes it.
        """
        self._space = space if space is not None else PROCESS_SPACE

    def __call__(self) -> str:
        """Return a fresh identifier."""
        return self._space.mint()

    def reserve(self, ids: Iterable[str]) -> None:
        """Take ``ids`` out of the space for the life of the process."""
        self._space.reserve(ids)
