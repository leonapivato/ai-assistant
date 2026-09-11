"""The canonical ``ParkedReads`` fake (ADR-0244 §3, §18).

The triad's third artifact. A non-persistent store over a list, holding the same
clauses a durable one holds and refusing everything it refuses, so a consumer verified
against this one is verified against the contract rather than against a convenience.

**It is deliberately not a filing cabinet.** ADR-0244 §3 makes ``park`` and ``settle``
active participants — one open park per conversation, one park per decision, a
compare-and-swap that answers ``True`` to exactly one caller, and a settlement that
clears the three content fields **in the same step** that moves the disposition — and
every one of those is here. A fake looser than the contract would certify consumers the
real implementation rejects (ADR-0026 §7).

**The exclusion is real, not asserted.** Every method runs inside a
:class:`~ai_assistant.testing.cancellation.SuspendableResource`, so this fake is a
subject for ADR-0060's cancellation clause at the lock sites a durable store has — and
the checks sit *inside* it, which is what makes the shared suite's concurrent ``park``
and concurrent ``settle`` cases real tests rather than vacuous ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from ai_assistant.core.errors import AssistantError
from ai_assistant.core.types import ParkedRead, ParkedReadDisposition
from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog, SuspendableResource

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

__all__ = ["FakeParkedReads"]

#: The three fields ADR-0244 §3's settlement clears, named once so the clearing and the
#: suite's assertion about it cannot come apart.
_CONTENT: tuple[str, ...] = ("parameters", "goal", "plan")


def _revalidated(record: ParkedRead) -> ParkedRead:
    """``record`` rebuilt through its own model, so nothing is shared with a caller.

    ADR-0244 §2's record is frozen, but its ``goal`` and ``plan`` are models whose own
    members a caller could reach; rebuilding on the way in and on the way out is the
    detachment obligation every store on this surface holds.
    """
    return ParkedRead.model_validate(record.model_dump())


@final
class FakeParkedReads:
    """A non-persistent, conforming ``ParkedReads`` test double.

    Structurally implements :class:`~ai_assistant.core.protocols.ParkedReads`.

    **What it keeps and what it hands back are different objects.** Every record is
    revalidated on the way in and every read rebuilds, so nothing a caller mutates
    reaches the store and nothing of the store's is reachable from what a caller
    receives.
    """

    def __init__(self, records: Sequence[ParkedRead] = ()) -> None:
        """Create the store.

        Args:
            records: The history it starts with, applied in order under the same
                invariants :meth:`park` applies — so a history a conforming store could
                not hold is refused here rather than at the first read. Terminal
                records are admitted directly, because a conforming store reaches them
                by settlement and a fixture has no settlement to replay.

        Raises:
            AssistantError: If ``records`` is not a history a conforming store could
                hold.
        """
        self._records: list[ParkedRead] = []
        self._resource = SuspendableResource()
        self._read_failure: Exception | None = None
        self._write_failure: Exception | None = None
        for held in records:
            if held.disposition is ParkedReadDisposition.OPEN:
                self._park(held)
                continue
            self._refuse_duplicates(held)
            self._records.append(_revalidated(held))

    # --- test-only hooks, deliberately off the seam ------------------------

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it.

        There is one modelled resource and every method enters it, so this suspends
        whichever call arrives next rather than a named operation. The hook ADR-0060
        §3's case takes; test-only, and not part of the contract — the Protocol grows no
        affordance for it.

        Returns:
            The handle to wait on and release.
        """
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log

    def fail_reads(self, error: Exception | None = None) -> None:
        """Arm every subsequent read to raise a store fault.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._read_failure = (
            error if error is not None else RuntimeError("fake: the store is unreadable")
        )

    def fail_writes(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`park`, :meth:`settle` and drop to raise.

        A **store fault** rather than a refusal: a refusal is what ``park`` and
        ``settle`` already answer ``False`` for, and what this scripts is the other
        failure — "the store could not be written" — which ADR-0244 §1's third clause
        makes indistinguishable from a refusal at the servicing site and which no
        well-formed input can provoke.

        Args:
            error: The underlying fault, preserved as ``__cause__``.
        """
        self._write_failure = (
            error if error is not None else RuntimeError("fake: the store is unwritable")
        )

    # --- internals ---------------------------------------------------------

    def _refuse_read(self) -> None:
        """Raise the scripted read fault, if one is armed.

        Raises:
            AssistantError: If :meth:`fail_reads` armed one.
        """
        if self._read_failure is not None:
            msg = "fake: the parked-read store could not be read"
            raise AssistantError(msg) from self._read_failure

    def _refuse_write(self) -> None:
        """Raise the scripted write fault, if one is armed.

        Raises:
            AssistantError: If :meth:`fail_writes` armed one.
        """
        if self._write_failure is not None:
            msg = "fake: the parked-read store could not be written"
            raise AssistantError(msg) from self._write_failure

    def _refuse_duplicates(self, record: ParkedRead) -> None:
        """Refuse a record whose id or decision the store already holds.

        The id is write-once for every store on this surface; the **decision** is what
        ADR-0244 §3 states in terms — "one park names one decision" — so that
        :meth:`park_of_decision` is a single answer rather than a listing.

        Raises:
            AssistantError: If either is already held.
        """
        for held in self._records:
            if held.id == record.id:
                msg = f"fake: park {record.id!r} is already recorded"
                raise AssistantError(msg)
            if held.decision_id == record.decision_id:
                msg = (
                    f"fake: a park already names decision {record.decision_id!r}; one park "
                    f"names one decision (ADR-0244 §3)"
                )
                raise AssistantError(msg)

    def _park(self, record: ParkedRead) -> bool:
        """Apply ADR-0244 §3's write invariants and append, as one act.

        The checks are here rather than in :meth:`park` so that they and the append
        share one body: there is no ``await`` between them, which is how the
        indivisibility §3 requires is obtained on a single event loop.

        Returns:
            Whether the park was written.

        Raises:
            AssistantError: If the record's id is already recorded.
        """
        snapshot = _revalidated(record)
        if snapshot.disposition is not ParkedReadDisposition.OPEN:
            msg = (
                f"fake: park {snapshot.id!r} is written OPEN; a terminal park is reached by "
                f"settlement and never by a write (ADR-0244 §2, §3)"
            )
            raise AssistantError(msg)
        for held in self._records:
            if held.id == snapshot.id:
                msg = f"fake: park {snapshot.id!r} is already recorded"
                raise AssistantError(msg)
            if held.decision_id == snapshot.decision_id:
                # **One park names one decision**, refused rather than admitted, so no
                # implementation can reach a state where two rows answer one decision id.
                return False
            if (
                held.conversation_id == snapshot.conversation_id
                and held.disposition is ParkedReadDisposition.OPEN
            ):
                # **A conversation holds at most one ``OPEN`` park**, and the
                # enforcement is the store's rather than a caller's (ADR-0244 §3).
                return False
        self._records.append(snapshot)
        return True

    # --- the contract ------------------------------------------------------

    async def park(self, record: ParkedRead, /) -> bool:
        """Write an ``OPEN`` park, or answer ``False`` where one already stands.

        The invariant checks are *inside* the resource, not before it: two turns of one
        conversation, two servicings of one turn and two engines over one data directory
        can none of them be admitted against the same conversation's park, and this is
        where "the read of the existing park and the write are one indivisible step" is
        actually kept.

        Returns:
            Whether this call wrote the park.

        Raises:
            AssistantError: If a store fault is scripted (:meth:`fail_writes`), if the
                record is not ``OPEN``, or if its id is already recorded.
        """
        self._refuse_write()
        async with self._resource.held():
            return self._park(record)

    async def get(self, park_id: str, /) -> ParkedRead | None:
        """The park under that id, or ``None``.

        Raises:
            AssistantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            for held in self._records:
                if held.id == park_id:
                    return _revalidated(held)
            return None

    async def open_park(self, conversation_id: str, /) -> ParkedRead | None:
        """This conversation's open park, or ``None``.

        Raises:
            AssistantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            for held in self._records:
                if (
                    held.conversation_id == conversation_id
                    and held.disposition is ParkedReadDisposition.OPEN
                ):
                    return _revalidated(held)
            return None

    async def park_of_decision(self, decision_id: str, /) -> ParkedRead | None:
        """The park naming that decision, whatever its disposition, or ``None``.

        Raises:
            AssistantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            for held in self._records:
                if held.decision_id == decision_id:
                    return _revalidated(held)
            return None

    async def outstanding(self) -> tuple[ParkedRead, ...]:
        """Every ``OPEN`` park, in ``parked_at`` order.

        **It takes no view of the clock.** An expired park is still ``OPEN`` until
        something settles it, and settling it is the engine's (ADR-0244 §5); a store
        that read a clock would be deciding a lifetime it does not own.

        Raises:
            AssistantError: If a read fault is scripted (:meth:`fail_reads`).
        """
        self._refuse_read()
        async with self._resource.held():
            live = [
                held for held in self._records if held.disposition is ParkedReadDisposition.OPEN
            ]
            live.sort(key=lambda held: (held.parked_at, held.id))
            return tuple(_revalidated(held) for held in live)

    async def settle(
        self,
        park_id: str,
        /,
        *,
        disposition: ParkedReadDisposition,
        at: datetime,  # noqa: ARG002 — the contract's, and a settled park keeps no settled-at fact for this fake to put it in (ADR-0244 §3); the clause it serves is that the caller supplies the instant rather than the store reading a clock
    ) -> bool:
        """Move an ``OPEN`` park to a terminal member and clear its content.

        **The resolve-once gate.** The read, the comparison and the write share one body
        with no ``await`` between them, so exactly one caller is answered ``True``; a
        ``settle`` on an already-terminal park answers ``False`` and changes nothing.

        **``at`` lands in no field here, and that is ADR-0244 §3 rather than a gap.**
        The terminal facts a settled park keeps are its ``id``, ``conversation_id``,
        ``decision_id``, ``parked_at``, ``expires_at`` and ``disposition`` — there is no
        settled-at member on :class:`~ai_assistant.core.types.ParkedRead` and this fake
        mints none. A durable store may stamp its own row from it; what the **contract**
        obliges is that the caller supplies the instant rather than the store reading a
        clock, which is the rule every store on this surface holds.

        Args:
            park_id: The park to settle.
            disposition: The terminal member to move it to.
            at: The instant the caller took the settlement at.

        Returns:
            Whether this call moved the park.

        Raises:
            AssistantError: If a store fault is scripted (:meth:`fail_writes`).
            ValueError: If ``disposition`` is ``OPEN``, which is not a settlement.
        """
        if disposition is ParkedReadDisposition.OPEN:
            msg = (
                "settle moves a park to a terminal disposition; OPEN is not a settlement "
                "and no transition leaves a terminal member (ADR-0244 §2, §3)"
            )
            raise ValueError(msg)
        self._refuse_write()
        async with self._resource.held():
            for position, held in enumerate(self._records):
                if held.id != park_id:
                    continue
                if held.disposition is not ParkedReadDisposition.OPEN:
                    return False
                # **The content is cleared in the same step that moves the
                # disposition** (ADR-0244 §3), which is what bounds it in time rather
                # than in principle — and no copy, digest, snapshot or archive of it is
                # retained anywhere in this object.
                self._records[position] = _revalidated(
                    held.model_copy(update={"disposition": disposition, **dict.fromkeys(_CONTENT)})
                )
                return True
            return False

    async def drop_for_conversation(self, conversation_id: str, /) -> int:
        """Remove every park of that conversation and answer how many rows went.

        Open and terminal alike, content and terminal facts alike. Idempotent: a second
        call answers ``0``.

        Raises:
            AssistantError: If a store fault is scripted (:meth:`fail_writes`).
        """
        self._refuse_write()
        async with self._resource.held():
            kept = [held for held in self._records if held.conversation_id != conversation_id]
            removed = len(self._records) - len(kept)
            self._records = kept
            return removed
